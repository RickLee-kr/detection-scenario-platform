"""Scenario host selection — discovery capability hosts only (no CIDR .1/.2 fallback)."""

from __future__ import annotations

from dataclasses import dataclass

from dsp.engine.scenario_engine import TargetSet

# Plain HTTP ports for URL scan / UA anomaly (sensor-visible payload)
HTTP_PLAIN_PORTS = (80, 8080, 8000, 8888, 9000, 9090)
HTTPS_PORTS = (443, 8443)


@dataclass(frozen=True)
class HttpFollowupEndpoint:
    host: str
    port: int
    scheme: str


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


def select_http_followup_endpoints(
    targets: TargetSet,
    config: dict,
    *,
    max_hosts: int,
) -> tuple[list[HttpFollowupEndpoint], str | None]:
    """
    Select HTTP follow-up endpoints — plain HTTP first, HTTPS fallback.

    Returns (endpoints, skip_reason). skip_reason is set when no web service found.
    """
    if config.get("hosts"):
        from dsp.protocols.http.urls import select_port_for_host

        hosts = [str(h) for h in config["hosts"]][:max_hosts]
        return (
            [
                HttpFollowupEndpoint(
                    host=h,
                    port=select_port_for_host(i),
                    scheme="https" if select_port_for_host(i) in HTTPS_PORTS else "http",
                )
                for i, h in enumerate(hosts)
            ],
            None,
        )

    http_eps = _sort_http_endpoints(
        _endpoints_for_capability(targets, "http_targets", port_order=HTTP_PLAIN_PORTS),
        HTTP_PLAIN_PORTS,
    )
    if http_eps:
        selected = http_eps[:max_hosts]
        return (
            [HttpFollowupEndpoint(host=h, port=p, scheme="http") for h, p in selected],
            None,
        )

    https_eps = _sort_http_endpoints(
        _endpoints_for_capability(targets, "https_targets", port_order=HTTPS_PORTS),
        HTTPS_PORTS,
    )
    if https_eps:
        selected = https_eps[:max_hosts]
        return (
            [HttpFollowupEndpoint(host=h, port=p, scheme="https") for h, p in selected],
            None,
        )

    return [], "skipped_no_http_service"
