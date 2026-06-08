"""Evidence and S3 model tests."""

from __future__ import annotations

from datetime import datetime, timezone

from dsp.detection.models import (
    AlertEvidence,
    AnalyticsEvidence,
    CorrelationContext,
    EntityEvidence,
    EvidencePack,
    S3Result,
    S3Status,
    TimelineEvidence,
)


def _ctx() -> CorrelationContext:
    now = datetime.now(timezone.utc)
    return CorrelationContext(
        run_id="20260605_abc123",
        scenario_id="dns_tunnel",
        time_window_start=now,
        time_window_end=now,
        source_ip="10.10.10.5",
        destination_ip="10.10.10.53",
    )


def test_s3_status_values():
    assert S3Status.S3_CONFIRMED.value == "S3_CONFIRMED"
    assert S3Status.S3_NOT_OBSERVED.value == "S3_NOT_OBSERVED"
    assert S3Status.S3_INCONCLUSIVE.value == "S3_INCONCLUSIVE"


def test_evidence_pack_count():
    now = datetime.now(timezone.utc)
    ctx = _ctx()
    pack = EvidencePack(
        run_id=ctx.run_id,
        scenario_id=ctx.scenario_id,
        vendor="stellar",
        alerts=[
            AlertEvidence(
                evidence_id="a1",
                vendor="stellar",
                collected_at=now,
                run_id=ctx.run_id,
                scenario_id=ctx.scenario_id,
                alert_name="DNS Tunnel",
            )
        ],
        analytics=[
            AnalyticsEvidence(
                evidence_id="an1",
                vendor="stellar",
                collected_at=now,
                run_id=ctx.run_id,
                scenario_id=ctx.scenario_id,
                analytic_type="dns_query_volume_anomaly",
            )
        ],
        entities=[
            EntityEvidence(
                evidence_id="e1",
                vendor="stellar",
                collected_at=now,
                run_id=ctx.run_id,
                scenario_id=ctx.scenario_id,
                entity_type="ip",
                entity_value="10.10.10.5",
            )
        ],
        timeline=[
            TimelineEvidence(
                evidence_id="t1",
                vendor="stellar",
                collected_at=now,
                run_id=ctx.run_id,
                scenario_id=ctx.scenario_id,
                event_type="dns_detection",
            )
        ],
    )
    assert pack.evidence_count == 4
    assert len(pack.all_items()) == 4


def test_s3_result_to_dict():
    now = datetime.now(timezone.utc)
    result = S3Result(
        run_id="20260605_abc123",
        scenario="dns_tunnel",
        status=S3Status.S3_CONFIRMED,
        vendor="stellar",
        evidence_count=4,
        timestamp=now,
    )
    data = result.to_dict()
    assert data["status"] == "S3_CONFIRMED"
    assert data["vendor"] == "stellar"
    assert data["evidence_count"] == 4
