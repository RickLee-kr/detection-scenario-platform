"""Tests for dsp.runtime.traffic_profiles."""

from __future__ import annotations

import pytest

from dsp.runtime.traffic_profiles import (
    SUPPORTED_TRAFFIC_PROFILES,
    build_scenario_params,
    parse_traffic_profile,
    profile_for_scenario,
    resolve_traffic_profile,
    scenario_params_for_profile,
)


@pytest.mark.parametrize("name", sorted(SUPPORTED_TRAFFIC_PROFILES))
def test_parse_traffic_profile_accepts_supported_names(name: str) -> None:
    assert parse_traffic_profile(name) == name
    assert parse_traffic_profile(name.upper()) == name


def test_parse_traffic_profile_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="unknown traffic profile"):
        parse_traffic_profile("aggressive")


def test_resolve_traffic_profile_metadata() -> None:
    profile = resolve_traffic_profile("normal")
    assert profile.name == "normal"
    assert profile.intensity == 2
    assert "moderate" in profile.description.lower()


def test_parse_traffic_profile_accepts_legacy_aliases() -> None:
    assert parse_traffic_profile("balanced") == "normal"
    assert parse_traffic_profile("burst") == "high"


def test_dns_tunnel_profile_mapping_increases_with_intensity() -> None:
    low = scenario_params_for_profile("dns_tunnel", "low")
    normal = scenario_params_for_profile("dns_tunnel", "normal")
    high = scenario_params_for_profile("dns_tunnel", "high")

    assert low["max_chunks"] < normal["max_chunks"] < high["max_chunks"]
    assert low["traffic_profile"] == "low"
    assert high["traffic_profile"] == "high"


def test_build_scenario_params_wraps_scenario_id() -> None:
    params = build_scenario_params("dummy", "low")
    assert "dummy" in params
    assert params["dummy"]["action_count"] == 3


def test_build_scenario_params_applies_overrides() -> None:
    params = build_scenario_params("dummy", "low", overrides={"action_count": 2})
    assert params["dummy"]["action_count"] == 2


def test_profile_for_scenario_includes_scenario_params() -> None:
    profile = profile_for_scenario("http_followup", "high")
    assert profile.name == "high"
    assert profile.scenario_params["max_total"] == 300
    assert profile.scenario_params["max_hosts"] == 1
