"""Stellar response normalization tests."""

from __future__ import annotations

from datetime import datetime, timezone

from dsp.detection.models import CorrelationContext
from dsp.detection.providers.stellar.normalization import (
    build_evidence_pack,
    normalize_alerts,
    sanitize_raw_record,
)


def _context() -> CorrelationContext:
    now = datetime.now(timezone.utc)
    return CorrelationContext(
        run_id="20260605_norm",
        scenario_id="dns_tunnel",
        time_window_start=now,
        time_window_end=now,
        source_ip="10.10.10.5",
        destination_ip="10.10.10.53",
    )


def test_normalize_alerts_to_vendor_neutral():
    context = _context()
    alerts = normalize_alerts(
        [
            {
                "id": "alert-1",
                "name": "DNS Tunnel",
                "severity": "high",
                "observed_at": "2026-06-05T12:00:00Z",
                "entity_refs": ["10.10.10.5"],
                "detection_model_id": "stellar.dns_tunnel",
            }
        ],
        context=context,
    )
    assert len(alerts) == 1
    assert alerts[0].alert_name == "DNS Tunnel"
    assert alerts[0].vendor == "stellar"
    assert alerts[0].attributes["detection_model_id"] == "stellar.dns_tunnel"


def test_build_evidence_pack_uses_normalized_models():
    context = _context()
    pack = build_evidence_pack(
        context=context,
        alerts=[
            {
                "id": "alert-1",
                "name": "DNS Tunnel",
                "severity": "high",
                "observed_at": "2026-06-05T12:00:00Z",
                "entity_refs": ["10.10.10.5"],
            }
        ],
        analytics=[
            {
                "id": "incident-1",
                "analytic_type": "dns_query_volume_anomaly",
                "observed_at": "2026-06-05T12:00:00Z",
                "summary": "burst",
            }
        ],
        entities=[
            {
                "id": "entity-1",
                "entity_type": "ip",
                "entity_value": "10.10.10.5",
                "role": "source_ip",
            }
        ],
        timeline=[
            {
                "id": "timeline-1",
                "event_type": "dns_detection",
                "observed_at": "2026-06-05T12:00:00Z",
                "description": "detected",
            }
        ],
    )
    assert pack.evidence_count == 4
    assert all(item.vendor == "stellar" for item in pack.all_items())


def test_sanitize_raw_record_redacts_secrets():
    sanitized = sanitize_raw_record(
        {
            "id": "alert-1",
            "api_token": "secret",
            "nested": {"authorization": "Bearer abc"},
        }
    )
    assert sanitized["api_token"] == "***REDACTED***"
    assert sanitized["nested"]["authorization"] == "***REDACTED***"
