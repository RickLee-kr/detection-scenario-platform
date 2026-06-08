"""LDAP validation and reporting unit tests."""

from __future__ import annotations

from dsp.event_store import ValidationDecision, ValidationResult
from dsp.protocols.ldap.ldap_reporting import build_ldap_enumeration_report_section
from dsp.protocols.ldap.ldap_validation import (
    LDAP_ENUM_METRIC_NAMES,
    ldap_enumeration_validation_profile,
)


def test_validation_profile_metrics():
    profile = ldap_enumeration_validation_profile()
    metric_names = [m["name"] for m in profile["metrics"]]
    assert metric_names == LDAP_ENUM_METRIC_NAMES
    assert profile["success"]["ldap_connection_attempt_count"]["min"] == 1
    assert profile["success"]["ldap_bind_or_search_attempt_count"]["min"] == 1


def test_report_section_includes_hosts_and_validation_status():
    result = ValidationResult(
        run_id="run_ldap",
        scenario_id="ldap_enumeration",
        decision=ValidationDecision.SUCCESS,
        reason="thresholds met",
        metrics={
            "ldap_connection_attempt_count": 1,
            "ldap_bind_attempt_count": 1,
            "ldap_search_attempt_count": 5,
            "ldap_bind_or_search_attempt_count": 6,
            "ldap_bind_failed_count": 1,
            "ldap_search_failed_count": 5,
        },
    )
    lines = build_ldap_enumeration_report_section(
        result,
        summary={
            "hosts": ["10.10.10.30"],
            "ports": [389],
            "connection_attempt_count": 1,
            "bind_attempt_count": 1,
            "search_attempt_count": 5,
            "sample_filters": ["(objectClass=*)"],
            "duration_sec": 0.8,
        },
    )
    text = "\n".join(lines)
    assert "Hosts targeted" in text
    assert "10.10.10.30" in text
    assert "Bind attempts" in text
    assert "Search attempts" in text
    assert "Validation status" in text
    assert "success" in text
