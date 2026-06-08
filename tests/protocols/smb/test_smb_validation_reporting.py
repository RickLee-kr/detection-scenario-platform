"""SMB validation and reporting unit tests."""

from __future__ import annotations

from dsp.event_store import ValidationDecision, ValidationResult
from dsp.protocols.smb.smb_reporting import build_smb_login_failure_report_section
from dsp.protocols.smb.smb_validation import (
    SMB_LOGIN_FAILURE_METRIC_NAMES,
    smb_login_failure_validation_profile,
)


def test_validation_profile_metrics():
    profile = smb_login_failure_validation_profile()
    metric_names = [m["name"] for m in profile["metrics"]]
    assert metric_names == SMB_LOGIN_FAILURE_METRIC_NAMES
    assert profile["success"]["smb_auth_attempt_count"]["min"] == 1
    assert profile["success"]["smb_auth_failed_count"]["min"] == 1


def test_report_section_includes_hosts_and_validation_status():
    result = ValidationResult(
        run_id="run_smb",
        scenario_id="smb_login_failure",
        decision=ValidationDecision.SUCCESS,
        reason="thresholds met",
        metrics={
            "smb_auth_attempt_count": 5,
            "smb_auth_failed_count": 5,
        },
    )
    lines = build_smb_login_failure_report_section(
        result,
        summary={
            "hosts": ["10.10.10.30"],
            "attempt_count": 5,
            "failure_count": 5,
            "duration_sec": 1.2,
            "sample_usernames": ["administrator"],
        },
    )
    text = "\n".join(lines)
    assert "Hosts targeted" in text
    assert "10.10.10.30" in text
    assert "Attempt count" in text
    assert "Failure count" in text
    assert "Validation status" in text
    assert "success" in text
