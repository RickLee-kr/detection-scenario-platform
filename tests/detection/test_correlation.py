"""Correlation logic tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dsp.detection.correlation import (
    build_correlation_context,
    build_time_window,
    correlate,
    determine_s3_status,
    score_evidence_item,
)
from dsp.detection.models import (
    AlertEvidence,
    CorrelationContext,
    EntityEvidence,
    EvidencePack,
    S3Status,
)
from dsp.event_store import Event, EventStore, Run, RunStatus, ValidationDecision, ValidationResult


def _store_with_dns_tunnel_events(run_id: str) -> EventStore:
    store = EventStore(":memory:")
    store.open_run(run_id)
    now = datetime.now(timezone.utc)
    for event_name in ("scenario_started", "scenario_completed"):
        store.append(
            Event(
                run_id=run_id,
                scenario_id="dns_tunnel",
                timestamp=now,
                stage="orchestrator",
                event=event_name,
                status="info",
            )
        )
    store.append(
        Event(
            run_id=run_id,
            scenario_id="dns_tunnel",
            timestamp=now,
            stage="executor",
            event="dns_tunnel_query_sent",
            status="sent",
            target="10.10.10.53:53",
            evidence={"source_ip": "10.10.10.5", "resolver_ip": "10.10.10.53"},
        )
    )
    return store


def test_build_time_window():
    start = datetime(2026, 6, 5, 10, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 5, 10, 5, 0, tzinfo=timezone.utc)
    run = Run(
        run_id="tw_run",
        started_at=start,
        ended_at=end,
        status=RunStatus.COMPLETED,
    )
    window_start, window_end = build_time_window(run)
    assert window_start == start - timedelta(minutes=2)
    assert window_end == end + timedelta(minutes=30)


def test_build_correlation_context_from_event_store():
    run_id = "corr_ctx_run"
    store = _store_with_dns_tunnel_events(run_id)
    run = Run(
        run_id=run_id,
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
        status=RunStatus.COMPLETED,
    )
    vr = ValidationResult(
        run_id=run_id,
        scenario_id="dns_tunnel",
        decision=ValidationDecision.SUCCESS,
        reason="thresholds_met",
        metrics={"dns_tunnel_query_sent_count": 1},
        validated_at=datetime.now(timezone.utc),
    )

    ctx = build_correlation_context(run=run, validation_result=vr, store=store)
    assert ctx.run_id == run_id
    assert ctx.source_ip == "10.10.10.5"
    assert ctx.destination_ip == "10.10.10.53"
    assert ctx.s2_decision == "success"


def test_correlation_uses_run_id_time_ips_not_alert_name_only():
    now = datetime.now(timezone.utc)
    context = CorrelationContext(
        run_id="20260605_corr01",
        scenario_id="dns_tunnel",
        time_window_start=now - timedelta(minutes=1),
        time_window_end=now + timedelta(minutes=1),
        source_ip="10.10.10.5",
        destination_ip="10.10.10.53",
        scenario_type="dns_tunnel",
        s2_decision="success",
    )
    alert = AlertEvidence(
        evidence_id="a1",
        vendor="stellar",
        collected_at=now,
        run_id=context.run_id,
        scenario_id=context.scenario_id,
        alert_name="Unrelated Alert Name",
        observed_at=now,
        entity_refs=["10.10.10.5", "10.10.10.53"],
        attributes={"detection_model_id": "stellar.dns_tunnel"},
    )
    score = score_evidence_item(alert, context, detection_model_id="stellar.dns_tunnel")
    assert score >= 0.70

    evidence = EvidencePack(
        run_id=context.run_id,
        scenario_id=context.scenario_id,
        vendor="stellar",
        alerts=[alert],
    )
    status, aggregate, _reason = correlate(
        context,
        evidence,
        detection_model_id="stellar.dns_tunnel",
    )
    assert status == S3Status.S3_CONFIRMED
    assert aggregate >= 0.70


def test_s3_not_observed_when_no_evidence():
    now = datetime.now(timezone.utc)
    context = CorrelationContext(
        run_id="empty_run",
        scenario_id="dga",
        time_window_start=now,
        time_window_end=now,
        s2_decision="success",
    )
    evidence = EvidencePack(run_id="empty_run", scenario_id="dga", vendor="stellar")
    status = determine_s3_status(0.0, evidence, s2_decision="success")
    assert status == S3Status.S3_NOT_OBSERVED


def test_s3_inconclusive_when_s2_failed():
    now = datetime.now(timezone.utc)
    context = CorrelationContext(
        run_id="failed_s2",
        scenario_id="dga",
        time_window_start=now,
        time_window_end=now,
        s2_decision="failed",
    )
    entity = EntityEvidence(
        evidence_id="e1",
        vendor="stellar",
        collected_at=now,
        run_id="failed_s2",
        scenario_id="dga",
        entity_type="ip",
        entity_value="10.10.10.5",
    )
    evidence = EvidencePack(
        run_id="failed_s2",
        scenario_id="dga",
        vendor="stellar",
        entities=[entity],
    )
    status, _score, reason = correlate(context, evidence)
    assert status == S3Status.S3_INCONCLUSIVE
    assert "s2_decision" in reason
