"""Operational run profiles — scenario coverage and host selection for `dsp run --profile`."""

from __future__ import annotations

from typing import Any, Sequence

from dsp.engine.target_engine import expand_target_net_hosts, resolve_targets
from dsp.runtime.traffic_profiles import (
    build_scenario_params,
    parse_traffic_profile,
    scenario_params_for_profile,
)

SUPPORTED_OPERATIONAL_PROFILES = frozenset({"low", "normal", "high"})

_PROFILE_ALIASES: dict[str, str] = {
    "balanced": "normal",
    "burst": "high",
}

# Fixed execution order per profile (discovery-oriented scenarios first).
_PROFILE_SCENARIOS: dict[str, tuple[str, ...]] = {
    "low": ("port_sweep", "dns_tunnel", "http_followup"),
    "normal": (
        "port_sweep",
        "dns_tunnel",
        "dga",
        "http_followup",
        "sql_injection",
        "ldap_enumeration",
        "smb_login_failure",
        "ssh_failure",
        "kerberos_failure",
    ),
    "high": (
        "port_sweep",
        "dns_tunnel",
        "dga",
        "http_followup",
        "sql_injection",
        "ldap_enumeration",
        "smb_login_failure",
        "ssh_failure",
        "kerberos_failure",
    ),
}

_PROFILE_MAX_HOSTS: dict[str, int | None] = {
    "low": 1,
    "normal": 2,
    "high": None,  # use all discovered hosts
}

_SCENARIO_LABELS: dict[str, str] = {
    "port_sweep": "Port Sweep",
    "dns_tunnel": "DNS Tunnel",
    "dga": "DGA",
    "http_followup": "HTTP Follow-up",
    "sql_injection": "SQL Injection",
    "ldap_enumeration": "LDAP Enumeration",
    "smb_login_failure": "SMB Login Failure",
    "ssh_failure": "SSH Failure",
    "kerberos_failure": "Kerberos Failure",
    "dummy": "Dummy",
}


def parse_operational_profile(name: str) -> str:
    """Normalize and validate an operational profile name."""
    normalized = name.strip().lower()
    normalized = _PROFILE_ALIASES.get(normalized, normalized)
    if normalized not in SUPPORTED_OPERATIONAL_PROFILES:
        supported = ", ".join(sorted(SUPPORTED_OPERATIONAL_PROFILES))
        raise ValueError(
            f"unknown operational profile: {name!r}; choose from {supported}"
        )
    return normalized


def scenarios_for_profile(profile_name: str) -> list[str]:
    """Return ordered scenario IDs for an operational profile."""
    profile = parse_operational_profile(profile_name)
    return list(_PROFILE_SCENARIOS[profile])


def resolve_runnable_scenarios(
    profile_name: str,
    active_ids: Sequence[str],
) -> list[str]:
    """Filter profile scenarios to registry-active IDs, preserving order."""
    active = set(active_ids)
    return [sid for sid in scenarios_for_profile(profile_name) if sid in active]


def discover_host_count(target_net: str, *, max_hosts: int | None = None) -> int:
    """Return usable host count from target_net CIDR (Target Discovery)."""
    net = (target_net or "").strip()
    if not net:
        targets = resolve_targets("")
        return len(targets.hosts)
    cap = max_hosts if max_hosts is not None else 254
    return len(expand_target_net_hosts(net, max_hosts=cap))


def scenario_display_name(scenario_id: str) -> str:
    """Human-readable scenario label for progress output."""
    return _SCENARIO_LABELS.get(
        scenario_id,
        scenario_id.replace("_", " ").title(),
    )


def _host_limit_for_profile(
    profile: str,
    host_count: int,
    *,
    max_hosts_override: int | None = None,
) -> int:
    cap = _PROFILE_MAX_HOSTS[profile]
    if cap is None:
        limit = max(1, host_count)
    else:
        limit = max(1, min(cap, host_count))
    if max_hosts_override is not None:
        limit = min(limit, max_hosts_override)
    return max(1, limit)


def _apply_host_limit(
    params: dict[str, Any],
    profile: str,
    host_count: int,
    *,
    max_hosts_override: int | None = None,
) -> dict[str, Any]:
    merged = dict(params)
    limit = _host_limit_for_profile(
        profile,
        host_count,
        max_hosts_override=max_hosts_override,
    )
    if "max_hosts" in merged:
        if profile == "high":
            merged["max_hosts"] = limit
        else:
            merged["max_hosts"] = min(int(merged["max_hosts"]), limit)
    else:
        merged["max_hosts"] = limit
    return merged


def build_operational_scenario_params(
    profile_name: str,
    scenario_ids: Sequence[str],
    *,
    target_net: str,
    max_hosts: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Build RunManager scenario_params for an operational profile run."""
    profile = parse_operational_profile(profile_name)
    traffic_profile = parse_traffic_profile(profile)
    host_count = discover_host_count(target_net, max_hosts=max_hosts)

    params: dict[str, dict[str, Any]] = {}
    for scenario_id in scenario_ids:
        base = scenario_params_for_profile(scenario_id, traffic_profile)
        merged = _apply_host_limit(
            base,
            profile,
            host_count,
            max_hosts_override=max_hosts,
        )
        if scenario_id == "port_sweep":
            merged["max_hosts"] = min(254, host_count)
            merged["max_ports"] = 10
        if scenario_id == "http_followup":
            # Bash URL scan concentrates on one scored target; traffic profile caps hosts.
            merged["max_hosts"] = int(base.get("max_hosts", 1))
        params[scenario_id] = merged
    return params


def build_explicit_scenario_params_with_profile(
    scenario_ids: Sequence[str],
    profile_name: str,
    *,
    target_net: str,
    max_hosts: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Apply operational profile volume/host limits to explicit scenario IDs."""
    return build_operational_scenario_params(
        profile_name,
        scenario_ids,
        target_net=target_net,
        max_hosts=max_hosts,
    )
