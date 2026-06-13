"""HTTP endpoint probing for URL scan target selection — bash reachable_http parity."""

from __future__ import annotations

from dataclasses import dataclass, field

from dsp.protocols.http.client import HttpClient
from dsp.protocols.http.urls import PlannedHttpRequest
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

    def to_summary(self) -> dict[str, int | str]:
        return {
            "host": self.host,
            "port": self.port,
            "scheme": self.scheme,
            "probe_400": self.status_counts.get(400, 0),
            "probe_403": self.status_counts.get(403, 0),
            "probe_404": self.status_counts.get(404, 0),
            "probe_301": self.status_counts.get(301, 0),
            "probe_success": self.success_count,
            "probe_timeout": self.timeouts,
            "detection_score": self.detection_score(),
            "redirect_only": int(self.is_redirect_only),
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
            stats.timeouts += 1
            continue
        code = int(result.status_code)
        stats.status_counts[code] = stats.status_counts.get(code, 0) + 1
    return stats


def rank_probe_candidates(
    candidates: list[tuple[str, int, str]],
    *,
    client: HttpClient,
    max_probe: int = 8,
) -> list[tuple[HttpEndpointProbeStats, int]]:
    """Probe and rank endpoints; returns (stats, combined_score) descending."""
    ranked: list[tuple[HttpEndpointProbeStats, int]] = []
    for idx, (host, port, scheme) in enumerate(candidates[:max_probe]):
        stats = probe_http_endpoint(host, port, scheme, client=client, index=idx)
        port_bonus = _port_priority_bonus(port)
        scheme_bonus = 10 if scheme == "http" else 0
        combined = stats.detection_score() + port_bonus + scheme_bonus
        ranked.append((stats, combined))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked


def _port_priority_bonus(port: int) -> int:
    """HTTP detection ports only — prefer non-80 when errors available."""
    return {
        8080: 700,
        8008: 680,
        8000: 600,
        8888: 580,
        9000: 550,
        80: 200,
    }.get(port, 100)


def selection_reason_for(stats: HttpEndpointProbeStats) -> str:
    if stats.error_response_count > 0:
        return "error_responses_available"
    if not stats.is_redirect_only:
        return "not_redirect_only"
    return "redirect_only_low_priority"


def is_eligible_url_scan_target(stats: HttpEndpointProbeStats) -> bool:
    """
    URL scan target eligibility — must show 400 or 404 probe responses.

    Excludes timeout-only and connection-reset-only candidates (no HTTP status).
    """
    if not stats.status_counts:
        return False
    return stats.status_counts.get(400, 0) > 0 or stats.status_counts.get(404, 0) > 0
