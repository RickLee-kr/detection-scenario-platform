"""Port sweep validation and reporting unit tests."""

from __future__ import annotations

from dsp.event_store import ValidationDecision, ValidationResult
from dsp.protocols.recon.port_sweep_reporting import build_port_sweep_report_section
from dsp.protocols.recon.port_sweep_validation import (
    PORT_SWEEP_METRIC_NAMES,
    port_sweep_validation_profile,
)


def test_validation_profile_metrics():
    profile = port_sweep_validation_profile()
    metric_names = [m["name"] for m in profile["metrics"]]
    assert metric_names == PORT_SWEEP_METRIC_NAMES
    assert profile["success"]["port_probe_count"]["min"] == 1
    assert profile["success"]["port_connection_attempt_count"]["min"] == 1


def test_report_section_includes_hosts_ports_and_validation_status():
    result = ValidationResult(
        run_id="run_ps",
        scenario_id="port_sweep",
        decision=ValidationDecision.SUCCESS,
        reason="thresholds met",
        metrics={
            "port_probe_count": 13,
            "port_connection_attempt_count": 13,
            "port_connection_success_count": 2,
            "port_connection_failure_count": 11,
        },
    )
    lines = build_port_sweep_report_section(
        result,
        summary={
            "hosts": ["10.10.10.30"],
            "ports": [22, 80, 443],
            "probe_count": 13,
            "connection_success_count": 2,
            "connection_failure_count": 11,
            "duration_sec": 0.5,
        },
    )
    text = "\n".join(lines)
    assert "Hosts targeted" in text
    assert "10.10.10.30" in text
    assert "Ports targeted" in text
    assert "22" in text
    assert "Probe count" in text
    assert "Connection success count" in text
    assert "Connection failure count" in text
    assert "Validation status" in text
    assert "success" in text
