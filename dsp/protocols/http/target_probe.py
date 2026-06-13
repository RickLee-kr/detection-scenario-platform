"""HTTP endpoint probing for URL scan target selection — bash reachable_http parity."""

from __future__ import annotations

from dataclasses import dataclass, field

from dsp.protocols.http.client import HttpClient
from dsp.protocols.http.urls import HTTP_PORT_PRIORITY, PlannedHttpRequest
from dsp.protocols.http.user_agents import pick_rare_user_agent

# stellar_poc_followup.sh build_http_url_scan_probe_paths_remote_cmd paths
PROBE_PATHS = (
    "/WEB-INF/web.xml",
    "/.env",
    "/laravel/.env",
    "/.git/config",
    "/api/swagger",
    "/cmd.jsp",
    "/admin",
)

REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
ERROR_CODES = frozenset(range(400, 600))


@dataclass
class HttpEndpointProbeStats:
    host: str
    port: int
    scheme: str
    status_counts: dict[int, int] = field(default_factory=dict)
    timeouts: int = 0
    errors: int = 0

    @property
    def error_response_count(self) -> int:
        return sum(count for code, count in self.status_counts.items() if code in ERROR_CODES)

    @property
    def redirect_count(self) -> int:
        return sum(count for code, count in self.status_counts.items() if code in REDIRECT_CODES)

    @property
    def success_count(self) -> int:
        return sum(
            count for code, count in self.status_counts.items() if 200 <= code < 300
        )

    @property
    def useful_error_probe_count(self) -> int:
        return (
            self.status_counts.get(400, 0)
            + self.status_counts.get(403, 0)
            + self.status_counts.get(404, 0)
        )

    @property
    def is_redirect_only(self) -> bool:
        if self.timeouts and not self.status_counts:
            return False
        if self.error_response_count > 0 or self.success_count > 0:
            return False
        return self.redirect_count > 0

    def detection_score(self) -> int:
        """Bash http_url_scan_compute_target_detection_score parity."""
        p400 = self.status_counts.get(400, 0)
        p403 = self.status_counts.get(403, 0)
        p404 = self.status_counts.get(404, 0)
        p301 = self.status_counts.get(301, 0)
        p302 = sum(self.status_counts.get(code, 0) for code in (302, 303, 307, 308))
        return p400 * 1000 + p403 * 500 + p404 * 300 - p301 * 10000 - p302 * 10000 - self.timeouts * 100

    def to_summary(
        self,
        *,
        selected: bool = False,
        rejection_reason: str = "",
    ) -> dict[str, int | str | bool]:
        return {
            "host": self.host,
            "port": self.port,
            "scheme": self.scheme,
            "probe_400": self.status_counts.get(400, 0),
            "probe_403": self.status_counts.get(403, 0),
            "probe_404": self.status_counts.get(404, 0),
            "probe_success": self.success_count,
            "probe_timeout": self.timeouts,
            "probe_error": self.errors,
            "redirect_only": int(self.is_redirect_only),
            "detection_score": self.detection_score(),
            "selected": selected,
            "rejection_reason": rejection_reason,
        }


def _mock_probe_stats(host: str, port: int, scheme: str, index: int) -> HttpEndpointProbeStats:
    """Dry-run probe stats — bash run_http_url_scan_target_probe DRY_RUN branch."""
    stats = HttpEndpointProbeStats(host=host, port=port, scheme=scheme)
    case = index % 4
    if case == 0:
        stats.status_counts = {400: 2, 403: 1, 404: 1, 200: 1}
    elif case == 1:
        stats.status_counts = {403: 2, 404: 2, 200: 1}
    elif case == 2:
        stats.status_counts = {404: 3, 200: 2}
    else:
        stats.status_counts = {400: 1, 404: 1}
        stats.timeouts = 1
    return stats


def probe_http_endpoint(
    host: str,
    port: int,
    scheme: str,
    *,
    client: HttpClient,
    index: int = 0,
) -> HttpEndpointProbeStats:
    """Probe candidate endpoint with attack paths; count HTTP status codes."""
    stats = HttpEndpointProbeStats(host=host, port=port, scheme=scheme)
    if client.mode == "mock":
        return _mock_probe_stats(host, port, scheme, index)

    ua = pick_rare_user_agent()
    for path in PROBE_PATHS:
        plan = PlannedHttpRequest(host=host, port=port, path=path, headers={"User-Agent": ua})
        request = client.make_request(plan)
        result = client.request(request)
        if result.outcome != "response" or result.status_code is None:
            if result.outcome == "timeout":
                stats.timeouts += 1
            else:
                stats.errors += 1
            continue
        code = int(result.status_code)
        stats.status_counts[code] = stats.status_counts.get(code, 0) + 1
    return stats


def has_response_generating_probe(stats: HttpEndpointProbeStats) -> bool:
    """True when probe received at least one HTTP status code."""
    return bool(stats.status_counts)


def is_no_response_probe(stats: HttpEndpointProbeStats) -> bool:
    """True when probe saw only timeouts/resets with no HTTP status."""
    return not stats.status_counts


def has_useful_error_probe(stats: HttpEndpointProbeStats) -> bool:
    return stats.useful_error_probe_count > 0


def is_selectable_http_endpoint(stats: HttpEndpointProbeStats) -> bool:
    """
    Endpoint is selectable only after observed useful probe response.

    Priority tiers: 400/403/404 > 2xx success.
    Excludes redirect-only, timeout-only, reset-only, and no-response.
    """
    if is_no_response_probe(stats):
        return False
    if stats.is_redirect_only:
        return False
    if has_useful_error_probe(stats):
        return True
    return stats.success_count > 0


def port_priority_rank(port: int) -> int:
    """Lower rank = earlier in HTTP_PORT_PRIORITY (used as final tiebreaker)."""
    try:
        return HTTP_PORT_PRIORITY.index(port)
    except ValueError:
        return len(HTTP_PORT_PRIORITY)


def probe_quality_sort_key(stats: HttpEndpointProbeStats) -> tuple[int, int, int]:
    """
    Sort key for endpoint selection — lower tuple = higher priority.

    Priority: useful error probes > success probes > port priority.
    """
    if has_useful_error_probe(stats):
        tier = 0
    elif stats.success_count > 0:
        tier = 1
    else:
        tier = 2
    return (tier, -stats.detection_score(), port_priority_rank(stats.port))


def probe_all_http_candidates(
    candidates: list[tuple[str, int, str]],
    *,
    client: HttpClient,
    max_workers: int = 16,
) -> list[HttpEndpointProbeStats]:
    """Probe every HTTP candidate endpoint (all allowed ports per host)."""
    if not candidates:
        return []

    if len(candidates) == 1:
        host, port, scheme = candidates[0]
        return [probe_http_endpoint(host, port, scheme, client=client, index=0)]

    from concurrent.futures import ThreadPoolExecutor, as_completed

    indexed: list[HttpEndpointProbeStats | None] = [None] * len(candidates)
    worker_count = max(1, min(max_workers, len(candidates)))
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        future_map = {
            pool.submit(
                probe_http_endpoint,
                host,
                port,
                scheme,
                client=client,
                index=idx,
            ): idx
            for idx, (host, port, scheme) in enumerate(candidates)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            indexed[idx] = future.result()
    return [stats for stats in indexed if stats is not None]


def pick_best_endpoint_per_host(
    stats_list: list[HttpEndpointProbeStats],
) -> dict[str, HttpEndpointProbeStats]:
    """
    Pick the best selectable probed endpoint per host.

    Hosts with no selectable endpoint are omitted.
    Never returns a no-response endpoint when a selectable endpoint exists on the same host.
    """
    groups: dict[str, list[HttpEndpointProbeStats]] = {}
    for stats in stats_list:
        groups.setdefault(stats.host, []).append(stats)

    best: dict[str, HttpEndpointProbeStats] = {}
    for host, host_stats in groups.items():
        selectable = [s for s in host_stats if is_selectable_http_endpoint(s)]
        if not selectable:
            continue
        best[host] = min(selectable, key=probe_quality_sort_key)
    return best


def rejection_reason_for(
    stats: HttpEndpointProbeStats,
    *,
    selected_keys: set[tuple[str, int]],
    selectable_exists_globally: bool,
) -> str:
    key = (stats.host, stats.port)
    if key in selected_keys:
        return ""
    if is_selectable_http_endpoint(stats):
        return "lower_probe_quality_or_host_limit"
    if is_no_response_probe(stats):
        if stats.timeouts > 0 and stats.errors == 0:
            return "timeout_only"
        if stats.errors > 0 and stats.timeouts == 0:
            return "connection_error"
        if stats.timeouts > 0 or stats.errors > 0:
            return "timeout_or_connection_error"
        return "no_response"
    if stats.is_redirect_only:
        return "redirect_only"
    if has_response_generating_probe(stats) and selectable_exists_globally:
        return "no_useful_probe_response"
    return "no_useful_probe_response"


def build_probe_debug_summaries(
    probed: list[HttpEndpointProbeStats],
    selected: list[tuple[str, int]],
) -> list[dict[str, int | str | bool]]:
    selected_keys = set(selected)
    selectable_exists = any(is_selectable_http_endpoint(stats) for stats in probed)
    summaries: list[dict[str, int | str | bool]] = []
    for stats in probed:
        key = (stats.host, stats.port)
        summaries.append(
            stats.to_summary(
                selected=key in selected_keys,
                rejection_reason=rejection_reason_for(
                    stats,
                    selected_keys=selected_keys,
                    selectable_exists_globally=selectable_exists,
                ),
            )
        )
    return summaries


def rank_probe_candidates(
    candidates: list[tuple[str, int, str]],
    *,
    client: HttpClient,
    max_probe: int | None = None,
) -> list[tuple[HttpEndpointProbeStats, int]]:
    """Probe and rank endpoints; returns (stats, detection_score) best-first."""
    probe_set = candidates if max_probe is None else candidates[:max_probe]
    probed = probe_all_http_candidates(probe_set, client=client)
    ranked = sorted(probed, key=probe_quality_sort_key)
    return [(stats, stats.detection_score()) for stats in ranked]


def selection_reason_for(stats: HttpEndpointProbeStats) -> str:
    if has_useful_error_probe(stats):
        return "error_responses_available"
    if stats.success_count > 0:
        return "success_responses_available"
    if stats.is_redirect_only:
        return "redirect_only_low_priority"
    return "no_useful_probe_response"


def is_eligible_url_scan_target(stats: HttpEndpointProbeStats) -> bool:
    """
    URL scan target eligibility — must show 400 or 404 probe responses.

    Excludes timeout-only and connection-reset-only candidates (no HTTP status).
    """
    if not stats.status_counts:
        return False
    return stats.status_counts.get(400, 0) > 0 or stats.status_counts.get(404, 0) > 0
