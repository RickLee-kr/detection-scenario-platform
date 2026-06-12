"""Scenario host selection — discovery capability hosts only (no CIDR .1/.2 fallback)."""

from __future__ import annotations

from dataclasses import dataclass, field

from dsp.engine.scenario_engine import TargetSet

HTTP_PLAIN_PORTS = (80, 8080, 8000, 8888, 9000, 9090)
HTTPS_PORTS = (443, 8443)


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


def select_hosts_for_capability(
    targets: TargetSet,
    config: dict,
    *,
    capability: str,
    max_hosts: int,
) -> list[str]:
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


def _endpoints_for_capability(
    targets: TargetSet,
    capability: str,
    *,
    port_order: tuple[int, ...],
) -> list[tuple[str, int]]:
    endpoints = _dedupe_endpoints(targets.endpoints_for_capability(capability))
    if endpoints:
        return endpoints
    hosts = targets.hosts_for_capability(capability)
    if not hosts:
        return []
    return [(host, port_order[i % len(port_order)]) for i, host in enumerate(hosts)]


def _sort_http_endpoints(endpoints: list[tuple[str, int]], port_order: tuple[int, ...]) -> list[tuple[str, int]]:
    rank = {port: idx for idx, port in enumerate(port_order)}

    def sort_key(ep: tuple[str, int]) -> tuple:
        host, port = ep
        return (rank.get(port, len(port_order)), tuple(int(p) for p in host.split(".")))

    return sorted(endpoints, key=sort_key)


def _collect_candidate_triples(targets: TargetSet) -> list[tuple[str, int, str]]:
    http_eps = _sort_http_endpoints(
        _endpoints_for_capability(targets, "http_targets", port_order=HTTP_PLAIN_PORTS),
        HTTP_PLAIN_PORTS,
    )
    https_eps = _sort_http_endpoints(
        _endpoints_for_capability(targets, "https_targets", port_order=HTTPS_PORTS),
        HTTPS_PORTS,
    )
    # Interleave HTTP/HTTPS so probe budget reaches 443/8443 (404-prone) endpoints.
    candidates: list[tuple[str, int, str]] = []
    max_len = max(len(http_eps), len(https_eps))
    for idx in range(max_len):
        if idx < len(http_eps):
            host, port = http_eps[idx]
            candidates.append((host, port, "http"))
        if idx < len(https_eps):
            host, port = https_eps[idx]
            candidates.append((host, port, "https"))
    return candidates


def select_http_followup_endpoints(
    targets: TargetSet,
    config: dict,
    *,
    max_hosts: int,
    client=None,
) -> tuple[list[HttpFollowupEndpoint], str | None]:
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
    if config.get("hosts"):
        from dsp.protocols.http.urls import select_port_for_host

        hosts = [str(h) for h in config["hosts"]][:max_hosts]
        endpoints = [
            HttpFollowupEndpoint(
                host=h,
                port=select_port_for_host(i),
                scheme="https" if select_port_for_host(i) in HTTPS_PORTS else "http",
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
        return HttpFollowupSelection(endpoints=[], skip_reason="skipped_no_http_service")

    if client is None:
        return _select_without_probe(candidates, max_hosts=max_hosts)

    from dsp.protocols.http.target_probe import (
        rank_probe_candidates,
        selection_reason_for,
        selection_tier,
    )

    max_probe = int(config.get("max_probe_candidates", 20))
    ranked = rank_probe_candidates(candidates, client=client, max_probe=max_probe)
    if not ranked:
        return HttpFollowupSelection(endpoints=[], skip_reason="skipped_no_http_service")

    ordered = sorted(
        ranked,
        key=lambda item: (selection_tier(item[0]), -item[1]),
    )

    selected: list[HttpFollowupEndpoint] = []
    probe_summaries: list[dict[str, int | str]] = []
    redirect_labels: list[str] = []
    selected_keys: set[tuple[str, int]] = set()
    selected_hosts: set[str] = set()

    for stats, _score in ordered:
        probe_summaries.append(stats.to_summary())
        label = f"{stats.scheme}://{stats.host}:{stats.port}"
        if stats.is_redirect_only:
            redirect_labels.append(label)

    def _append_endpoint(stats: HttpEndpointProbeStats) -> None:
        key = (stats.host, stats.port)
        if key in selected_keys or len(selected) >= max_hosts:
            return
        selected_keys.add(key)
        selected_hosts.add(stats.host)
        selected.append(
            HttpFollowupEndpoint(
                host=stats.host,
                port=stats.port,
                scheme=stats.scheme,
                selection_reason=selection_reason_for(stats),
            )
        )

    if max_hosts == 1:
        for stats, _score in ordered:
            _append_endpoint(stats)
            break
    else:
        for stats, _score in ordered:
            if stats.host in selected_hosts:
                continue
            _append_endpoint(stats)

        for stats, _score in ordered:
            _append_endpoint(stats)

    primary_reason = selected[0].selection_reason if selected else ""
    return HttpFollowupSelection(
        endpoints=selected,
        selected_http_target_reason=primary_reason,
        probe_summaries=probe_summaries,
        redirect_only_candidates=redirect_labels,
    )


def _pick_diverse_endpoints(
    endpoints: list[tuple[str, int, str]],
    *,
    max_hosts: int,
) -> list[tuple[str, int, str]]:
    picked: list[tuple[str, int, str]] = []
    seen_keys: set[tuple[str, int]] = set()
    seen_hosts: set[str] = set()

    def _append(ep: tuple[str, int, str]) -> None:
        host, port, _scheme = ep
        key = (host, port)
        if key in seen_keys or len(picked) >= max_hosts:
            return
        seen_keys.add(key)
        seen_hosts.add(host)
        picked.append(ep)

    for ep in endpoints:
        if ep[0] not in seen_hosts:
            _append(ep)
    for ep in endpoints:
        _append(ep)
    return picked


def _select_without_probe(
    candidates: list[tuple[str, int, str]],
    *,
    max_hosts: int,
) -> HttpFollowupSelection:
    http_eps = [(h, p, s) for h, p, s in candidates if s == "http"]
    if http_eps:
        picked = _pick_diverse_endpoints(http_eps, max_hosts=max_hosts)
        return HttpFollowupSelection(
            endpoints=[
                HttpFollowupEndpoint(host=h, port=p, scheme=s, selection_reason="not_redirect_only")
                for h, p, s in picked
            ],
            selected_http_target_reason="not_redirect_only",
        )

    https_eps = [(h, p, s) for h, p, s in candidates if s == "https"]
    if https_eps:
        picked = _pick_diverse_endpoints(https_eps, max_hosts=max_hosts)
        return HttpFollowupSelection(
            endpoints=[
                HttpFollowupEndpoint(host=h, port=p, scheme=s, selection_reason="not_redirect_only")
                for h, p, s in picked
            ],
            selected_http_target_reason="not_redirect_only",
        )

    return HttpFollowupSelection(endpoints=[], skip_reason="skipped_no_http_service")
