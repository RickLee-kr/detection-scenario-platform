"""Scenario host selection — discovery capability hosts only (no CIDR .1/.2 fallback)."""

from __future__ import annotations

from dataclasses import dataclass, field

from dsp.engine.scenario_engine import TargetSet
from dsp.protocols.http.urls import HTTP_DETECTION_PORTS, HTTP_PORT_PRIORITY

# HTTP-only detection mode — no HTTPS fallback for URL scan / SQLi
HTTP_PLAIN_PORTS = HTTP_PORT_PRIORITY
SKIP_REASON_HTTP_TARGETS_NOT_FOUND = "HTTP_TARGETS_NOT_FOUND"


@dataclass(frozen=True)
class HttpFollowupEndpoint:
    host: str
    port: int
    scheme: str
    selection_reason: str = ""


@dataclass
class HttpFollowupSelection:
    endpoints: list[HttpFollowupEndpoint]
    skip_reason: str | None = None
    selected_http_target_reason: str = ""
    probe_summaries: list[dict[str, int | str]] = field(default_factory=list)
    redirect_only_candidates: list[str] = field(default_factory=list)
    https_targets_skipped: list[str] = field(default_factory=list)


def select_hosts_for_capability(
    targets: TargetSet,
    config: dict,
    *,
    capability: str,
    max_hosts: int,
) -> list[str]:
    """
    Select hosts from discovery capability bucket only.

    Does not fall back to CIDR expansion (.1, .2, …) — mirrors bash usable_* files.
    """
    if config.get("hosts"):
        return [str(h) for h in config["hosts"]][:max_hosts]

    discovered = targets.hosts_for_capability(capability)
    if discovered:
        return discovered[:max_hosts]

    return []


def select_merged_http_hosts(
    targets: TargetSet,
    config: dict,
    *,
    max_hosts: int,
) -> list[str]:
    """HTTP URL scan: http_targets + https_targets from discovery only."""
    if config.get("hosts"):
        return [str(h) for h in config["hosts"]][:max_hosts]

    merged = targets.merged_http_hosts()
    if merged:
        return merged[:max_hosts]

    return []


def _dedupe_endpoints(endpoints: list[tuple[str, int]]) -> list[tuple[str, int]]:
    seen: set[tuple[str, int]] = set()
    ordered: list[tuple[str, int]] = []
    for host, port in endpoints:
        key = (host, port)
        if key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered


def _sort_http_endpoints(endpoints: list[tuple[str, int]], port_order: tuple[int, ...]) -> list[tuple[str, int]]:
    rank = {port: idx for idx, port in enumerate(port_order)}

    def sort_key(ep: tuple[str, int]) -> tuple:
        host, port = ep
        return (rank.get(port, len(port_order)), tuple(int(p) for p in host.split(".")))

    return sorted(endpoints, key=sort_key)


def _filter_http_detection_endpoints(endpoints: list[tuple[str, int]]) -> list[tuple[str, int]]:
    return [(host, port) for host, port in endpoints if port in HTTP_DETECTION_PORTS]


def _https_targets_skipped_list(targets: TargetSet) -> list[str]:
    labels: list[str] = []
    for host, port in _dedupe_endpoints(targets.endpoints_for_capability("https_targets")):
        labels.append(f"{host}:{port}")
    return sorted(labels)


def _http_only_skip_selection(targets: TargetSet) -> HttpFollowupSelection:
    """Skip when discovery has HTTPS targets but no HTTP detection endpoints."""
    return HttpFollowupSelection(
        endpoints=[],
        skip_reason=SKIP_REASON_HTTP_TARGETS_NOT_FOUND,
        https_targets_skipped=_https_targets_skipped_list(targets),
    )


def _collect_candidate_triples(targets: TargetSet) -> list[tuple[str, int, str]]:
    """HTTP-only candidates — allowed plain-HTTP ports only."""
    candidates: list[tuple[str, int, str]] = []
    http_endpoints = _filter_http_detection_endpoints(
        _dedupe_endpoints(targets.endpoints_for_capability("http_targets"))
    )
    for host, port in _sort_http_endpoints(http_endpoints, HTTP_PLAIN_PORTS):
        candidates.append((host, port, "http"))
    return candidates


def format_selected_target_labels(endpoints: list[HttpFollowupEndpoint]) -> list[str]:
    """Format selected targets with probe-based selection reason."""
    return [f"{ep.host}:{ep.port} ({ep.selection_reason})" for ep in endpoints]


def select_http_followup_endpoints(
    targets: TargetSet,
    config: dict,
    *,
    max_hosts: int,
    client=None,
) -> tuple[list[HttpFollowupEndpoint], str | None]:
    """Backward-compatible wrapper — returns (endpoints, skip_reason)."""
    selection = probe_and_select_http_followup_endpoints(
        targets, config, max_hosts=max_hosts, client=client
    )
    return selection.endpoints, selection.skip_reason


def probe_and_select_http_followup_endpoints(
    targets: TargetSet,
    config: dict,
    *,
    max_hosts: int,
    client=None,
) -> HttpFollowupSelection:
    """
    Select HTTP follow-up endpoints with optional probe scoring.

    Plain HTTP first; deprioritize redirect-only (301-only) targets.
    """
    if config.get("hosts"):
        from dsp.protocols.http.urls import select_port_for_host

        hosts = [str(h) for h in config["hosts"]][:max_hosts]
        endpoints = [
            HttpFollowupEndpoint(
                host=h,
                port=select_port_for_host(i, HTTP_PORT_PRIORITY),
                scheme="http",
                selection_reason="explicit_hosts",
            )
            for i, h in enumerate(hosts)
        ]
        return HttpFollowupSelection(
            endpoints=endpoints,
            selected_http_target_reason="explicit_hosts",
        )

    candidates = _collect_candidate_triples(targets)
    if not candidates:
        if _https_targets_skipped_list(targets):
            return _http_only_skip_selection(targets)
        return HttpFollowupSelection(endpoints=[], skip_reason="skipped_no_http_service")

    if client is None:
        from dsp.protocols.http.client import HttpClient

        client = HttpClient(mode="mock")

    from dsp.protocols.http.target_probe import (
        pick_best_endpoint_per_host,
        probe_all_http_candidates,
        probe_quality_sort_key,
        selection_reason_for,
    )

    probed = probe_all_http_candidates(candidates, client=client)
    if not probed:
        if _https_targets_skipped_list(targets):
            return _http_only_skip_selection(targets)
        return HttpFollowupSelection(endpoints=[], skip_reason="skipped_no_http_service")

    probe_summaries = [stats.to_summary() for stats in probed]
    redirect_labels = [
        f"{stats.scheme}://{stats.host}:{stats.port}"
        for stats in probed
        if stats.is_redirect_only
    ]

    best_per_host = pick_best_endpoint_per_host(probed)
    hosts_ranked = sorted(best_per_host.values(), key=probe_quality_sort_key)

    selected: list[HttpFollowupEndpoint] = []
    if max_hosts == 1:
        if hosts_ranked:
            stats = hosts_ranked[0]
            selected.append(
                HttpFollowupEndpoint(
                    host=stats.host,
                    port=stats.port,
                    scheme=stats.scheme,
                    selection_reason=selection_reason_for(stats),
                )
            )
    else:
        for stats in hosts_ranked[:max_hosts]:
            selected.append(
                HttpFollowupEndpoint(
                    host=stats.host,
                    port=stats.port,
                    scheme=stats.scheme,
                    selection_reason=selection_reason_for(stats),
                )
            )

    primary_reason = selected[0].selection_reason if selected else ""

    return HttpFollowupSelection(
        endpoints=selected,
        selected_http_target_reason=primary_reason,
        probe_summaries=probe_summaries,
        redirect_only_candidates=redirect_labels,
    )
