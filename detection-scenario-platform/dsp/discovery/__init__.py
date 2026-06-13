"""Legacy bash-aligned discovery — TCP probe and service host mapping."""

from dsp.discovery.legacy_bash import (
    FAST_SAFE_DISCOVERY_PORTS,
    PORT_CAPABILITY_MAP,
    DiscoveryResult,
    discover_services,
    port_capability_key,
    probe_tcp_port,
)

__all__ = [
    "FAST_SAFE_DISCOVERY_PORTS",
    "PORT_CAPABILITY_MAP",
    "DiscoveryResult",
    "discover_services",
    "port_capability_key",
    "probe_tcp_port",
]
