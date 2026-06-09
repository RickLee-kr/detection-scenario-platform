"""Tests for dsp.runtime.operational_profiles."""

from __future__ import annotations

import pytest

from dsp.runtime.operational_profiles import (
    SUPPORTED_OPERATIONAL_PROFILES,
    build_operational_scenario_params,
    discover_host_count,
    parse_operational_profile,
    resolve_runnable_scenarios,
    scenarios_for_profile,
)


@pytest.mark.parametrize("name", sorted(SUPPORTED_OPERATIONAL_PROFILES))
def test_parse_operational_profile_accepts_supported_names(name: str) -> None:
    assert parse_operational_profile(name) == name


def test_parse_operational_profile_accepts_legacy_aliases() -> None:
    assert parse_operational_profile("balanced") == "normal"
    assert parse_operational_profile("burst") == "high"


def test_low_profile_scenario_coverage() -> None:
    assert scenarios_for_profile("low") == [
        "port_sweep",
        "dns_tunnel",
        "http_followup",
    ]


def test_normal_profile_includes_auth_and_protocol_scenarios() -> None:
    scenarios = scenarios_for_profile("normal")
    assert "ldap_enumeration" in scenarios
    assert "kerberos_failure" in scenarios
    assert scenarios.index("port_sweep") < scenarios.index("dns_tunnel")


def test_high_profile_matches_normal_coverage() -> None:
    assert scenarios_for_profile("high") == scenarios_for_profile("normal")


def test_resolve_runnable_scenarios_filters_inactive() -> None:
    resolved = resolve_runnable_scenarios(
        "normal",
        ["dns_tunnel", "missing_scenario", "http_followup"],
    )
    assert resolved == ["dns_tunnel", "http_followup"]


def test_discover_host_count_expands_cidr() -> None:
    assert discover_host_count("192.168.55.0/30") == 2


def test_build_operational_scenario_params_caps_hosts_for_normal() -> None:
    params = build_operational_scenario_params(
        "normal",
        ["http_followup", "dns_tunnel"],
        target_net="10.10.10.0/24",
    )
    assert params["http_followup"]["max_hosts"] == 2
    assert params["dns_tunnel"]["traffic_profile"] == "normal"


def test_build_operational_scenario_params_uses_all_hosts_for_high() -> None:
    params = build_operational_scenario_params(
        "high",
        ["http_followup"],
        target_net="192.168.55.0/30",
    )
    assert params["http_followup"]["max_hosts"] == 2
    assert params["http_followup"]["traffic_profile"] == "high"


def test_build_operational_scenario_params_low_limits_hosts() -> None:
    params = build_operational_scenario_params(
        "low",
        ["port_sweep"],
        target_net="10.10.10.0/24",
    )
    assert params["port_sweep"]["max_hosts"] == 1


def test_build_operational_scenario_params_max_hosts_override_caps_high() -> None:
    params = build_operational_scenario_params(
        "high",
        ["http_followup"],
        target_net="10.10.10.0/24",
        max_hosts=3,
    )
    assert params["http_followup"]["max_hosts"] == 3
