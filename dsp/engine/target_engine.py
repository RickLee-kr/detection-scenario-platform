"""Target resolution from operator-supplied target_net CIDR."""

from __future__ import annotations

import ipaddress

from dsp.engine.scenario_engine import TargetSet

DEFAULT_LAB_TARGET_NET = "10.10.10.0/24"
DEFAULT_LAB_FALLBACK_HOST = "10.10.10.20"
MAX_EXPANDED_HOSTS = 32


def expand_target_net_hosts(target_net: str, *, max_hosts: int = MAX_EXPANDED_HOSTS) -> list[str]:
    """Return usable host IPs from a CIDR (network/broadcast excluded for IPv4)."""
    network = ipaddress.ip_network(target_net.strip(), strict=False)
    hosts: list[str] = []
    for addr in network.hosts():
        hosts.append(str(addr))
        if len(hosts) >= max_hosts:
            break
    return hosts


def host_in_target_net(host: str, target_net: str) -> bool:
    """Return True when host is a member of target_net."""
    return ipaddress.ip_address(host) in ipaddress.ip_network(target_net.strip(), strict=False)


def resolve_targets(target_net: str, required_capabilities: list[str] | None = None) -> TargetSet:
    """Build TargetSet from target_net; lab fallback only when target_net is absent."""
    caps = {cap: True for cap in (required_capabilities or [])}
    caps.setdefault("alive_host", True)

    net = (target_net or "").strip()
    if not net:
        return TargetSet(
            target_net=DEFAULT_LAB_TARGET_NET,
            hosts=[DEFAULT_LAB_FALLBACK_HOST],
            capabilities=caps,
        )

    hosts = expand_target_net_hosts(net)
    if not hosts:
        raise ValueError(f"target_net has no usable hosts: {net}")

    return TargetSet(
        target_net=net,
        hosts=hosts,
        capabilities=caps,
    )
