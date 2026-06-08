"""Stellar adapter and mapping tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from dsp.detection.models import S3Status
from dsp.detection.providers.stellar.stellar_adapter import StellarAdapter
from dsp.detection.providers.stellar.stellar_mapping import load_stellar_mapping


def test_scenario_mapping_externalized():
    mapping = load_stellar_mapping()
    assert mapping.vendor == "stellar"
    supported = mapping.supported_scenarios()
    assert supported == [
        "dga",
        "dns_tunnel",
        "http_followup",
        "kerberos_failure",
        "ldap_enumeration",
        "port_sweep",
        "smb_login_failure",
        "sql_injection",
        "ssh_failure",
    ]
    dns = mapping.get("dns_tunnel")
    assert dns is not None
    assert dns.detection_model_id == "stellar.dns_tunnel"
    assert "DNS Tunnel" in dns.alert_families


def test_stellar_adapter_s3_confirmed_with_mock(tmp_path: Path):
    now = datetime.now(timezone.utc)
    from dsp.detection.models import CorrelationContext

    context = CorrelationContext(
        run_id="20260605_stellar01",
        scenario_id="dns_tunnel",
        time_window_start=now - datetime.resolution,
        time_window_end=now + datetime.resolution,
        source_ip="10.10.10.5",
        destination_ip="10.10.10.53",
        s2_decision="success",
    )
    adapter = StellarAdapter(simulate_detection=True)
    evidence = adapter.collect_evidence(context)
    assert evidence.evidence_count >= 3

    result = adapter.validate_detection(context, evidence)
    assert result.status == S3Status.S3_CONFIRMED
    assert result.vendor == "stellar"
    assert result.evidence_count == evidence.evidence_count

    vendor_dir = adapter.build_evidence_pack(context, evidence, result, tmp_path)
    assert vendor_dir == tmp_path / "evidence" / context.run_id / "stellar"

    s3_data = json.loads((vendor_dir / "s3_result.json").read_text(encoding="utf-8"))
    assert s3_data["status"] == "S3_CONFIRMED"
    assert s3_data["scenario"] == "dns_tunnel"
    assert s3_data["run_id"] == context.run_id


def test_stellar_adapter_s3_not_observed_empty_mock(tmp_path: Path):
    now = datetime.now(timezone.utc)
    from dsp.detection.models import CorrelationContext

    context = CorrelationContext(
        run_id="20260605_empty01",
        scenario_id="dga",
        time_window_start=now,
        time_window_end=now,
        s2_decision="success",
    )
    adapter = StellarAdapter(simulate_empty=True)
    evidence = adapter.collect_evidence(context)
    assert evidence.evidence_count == 0

    result = adapter.validate_detection(context, evidence)
    assert result.status == S3Status.S3_NOT_OBSERVED
