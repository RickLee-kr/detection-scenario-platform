"""DNS validation and reporting profile tests."""

from __future__ import annotations

from dsp.protocols.dns import dns_report_profile, dns_validation_profile
from dsp.protocols.dns.reporting import build_dns_report_section
from dsp.event_store import ValidationDecision, ValidationResult


def test_dns_validation_profile_structure():
    profile = dns_validation_profile()
    assert profile["profile_version"] == "1.0.0"
    assert len(profile["metrics"]) >= 5
    assert "dns_query_sent_count" in profile["success"]
    assert "SOT_EMPTY_AFTER_EXECUTE" in profile["fail_fast"]


def test_dns_report_profile_has_protocol_tag():
    profile = dns_report_profile()
    assert profile["protocol"] == "dns"
    assert "dns_query_sent_count" in profile["highlight_metrics"]


def test_dns_report_section_traceability():
    result = ValidationResult(
        run_id="r1",
        scenario_id="dns_dummy",
        decision=ValidationDecision.SUCCESS,
        reason="thresholds_met",
        metrics={
            "dns_query_sent_count": 5,
            "dns_response_count": 4,
            "dns_timeout_count": 1,
            "dns_nxdomain_count": 0,
            "dns_error_count": 0,
        },
    )
    lines = build_dns_report_section(result)
    text = "\n".join(lines)
    assert "dns_query_sent_count" in text
    assert "event=dns_query_sent" in text
    assert "success" in text
