"""Safety checks for operator-supplied --target-net CIDR."""

from __future__ import annotations

import ipaddress

LARGE_TARGET_ERROR = (
    "target-net is larger than /24. "
    "Use --allow-large-target and --max-hosts to continue."
)


def is_larger_than_slash24(target_net: str) -> bool:
    """Return True when the CIDR spans more than a /24 (IPv4) or /64 (IPv6)."""
    network = ipaddress.ip_network(target_net.strip(), strict=False)
    if network.version == 6:
        return network.prefixlen < 64
    return network.prefixlen < 24


def validate_target_net_scope(
    target_net: str,
    *,
    allow_large_target: bool,
    max_hosts: int | None,
) -> None:
    """Reject oversized target-net unless explicitly allowed with a host cap."""
    net = (target_net or "").strip()
    if not net or not is_larger_than_slash24(net):
        return
    if not allow_large_target or max_hosts is None or max_hosts < 1:
        raise ValueError(LARGE_TARGET_ERROR)
