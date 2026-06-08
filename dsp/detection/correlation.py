"""Correlation logic — run_id, time window, IPs, scenario type."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from dsp.detection.models import (
    AlertEvidence,
    AnalyticsEvidence,
    ArtifactEvidence,
    CorrelationContext,
    EntityEvidence,
    EvidencePack,
    S3Status,
    TimelineEvidence,
)
from dsp.event_store import EventStore, Run, ValidationDecision, ValidationResult

TIME_WINDOW_PRE_BUFFER = timedelta(minutes=2)
TIME_WINDOW_POST_BUFFER = timedelta(minutes=30)

CORRELATION_WEIGHTS = {
    "run_id": 0.30,
    "time_window": 0.25,
    "source_ip": 0.15,
    "destination_ip": 0.15,
    "scenario_type": 0.15,
}

CONFIRMED_THRESHOLD = 0.70
INCONCLUSIVE_THRESHOLD = 0.40


def build_time_window(
    run: Run,
    *,
    pre_buffer: timedelta = TIME_WINDOW_PRE_BUFFER,
    post_buffer: timedelta = TIME_WINDOW_POST_BUFFER,
) -> tuple[datetime, datetime]:
    """Derive correlation window from run metadata."""
    now = datetime.now(timezone.utc)
    start = run.started_at or now
    end = run.ended_at or now
    return start - pre_buffer, end + post_buffer


def extract_ips_from_events(
    store: EventStore,
    run_id: str,
    scenario_id: str,
) -> tuple[str | None, str | None]:
    """Best-effort source/destination IP extraction from Event Store evidence."""
    source_ip: str | None = None
    destination_ip: str | None = None

    for event in store.list_events(run_id, scenario_id):
        ev = event.evidence or {}
        if not source_ip:
            source_ip = ev.get("source_ip") or ev.get("src_ip") or ev.get("client_ip")
        if not destination_ip:
            destination_ip = (
                ev.get("destination_ip")
                or ev.get("dst_ip")
                or ev.get("resolver_ip")
                or ev.get("target_ip")
            )
        if event.target and not destination_ip:
            destination_ip = event.target.split(":")[0] if ":" in event.target else event.target

    return source_ip, destination_ip


def build_correlation_context(
    *,
    run: Run,
    validation_result: ValidationResult,
    store: EventStore,
    scenario_type: str | None = None,
) -> CorrelationContext:
    """Build correlation context from authoritative Event Store + ValidationResult."""
    window_start, window_end = build_time_window(run)
    source_ip, destination_ip = extract_ips_from_events(
        store,
        validation_result.run_id,
        validation_result.scenario_id,
    )
    return CorrelationContext(
        run_id=validation_result.run_id,
        scenario_id=validation_result.scenario_id,
        time_window_start=window_start,
        time_window_end=window_end,
        source_ip=source_ip,
        destination_ip=destination_ip,
        scenario_type=scenario_type or validation_result.scenario_id,
        dry_run=run.dry_run,
        s2_decision=validation_result.decision.value,
        metadata={
            "target_net": run.target_net,
            "validation_reason": validation_result.reason,
        },
    )


def _in_time_window(observed_at: datetime | None, context: CorrelationContext) -> bool:
    if observed_at is None:
        return False
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    return context.time_window_start <= observed_at <= context.time_window_end


def _entity_matches_ip(entity: EntityEvidence, ip: str | None) -> bool:
    if not ip:
        return False
    return entity.entity_type in {"ip", "host", "endpoint"} and entity.entity_value == ip


def score_evidence_item(
    item: AlertEvidence | AnalyticsEvidence | EntityEvidence | TimelineEvidence | ArtifactEvidence,
    context: CorrelationContext,
    *,
    detection_model_id: str | None = None,
) -> float:
    """Score a single evidence item against correlation rules (not alert name alone)."""
    score = 0.0

    if item.run_id == context.run_id:
        score += CORRELATION_WEIGHTS["run_id"]

    observed_at: datetime | None = None
    if isinstance(item, (AlertEvidence, AnalyticsEvidence, TimelineEvidence)):
        observed_at = item.observed_at
    if _in_time_window(observed_at, context):
        score += CORRELATION_WEIGHTS["time_window"]

    if isinstance(item, EntityEvidence):
        if _entity_matches_ip(item, context.source_ip) or _entity_matches_ip(
            item, context.destination_ip
        ):
            score += CORRELATION_WEIGHTS["source_ip"] + CORRELATION_WEIGHTS["destination_ip"]
    elif isinstance(item, AlertEvidence):
        for ref in item.entity_refs:
            if context.source_ip and ref == context.source_ip:
                score += CORRELATION_WEIGHTS["source_ip"]
            if context.destination_ip and ref == context.destination_ip:
                score += CORRELATION_WEIGHTS["destination_ip"]

    model_ref = item.attributes.get("detection_model_id") or detection_model_id
    if model_ref and context.scenario_type and model_ref.endswith(context.scenario_type.replace("_", ".")):
        score += CORRELATION_WEIGHTS["scenario_type"]
    elif item.scenario_id == context.scenario_id:
        score += CORRELATION_WEIGHTS["scenario_type"]

    item.correlation_score = min(score, 1.0)
    return item.correlation_score


def score_evidence_pack(
    evidence: EvidencePack,
    context: CorrelationContext,
    *,
    detection_model_id: str | None = None,
) -> float:
    """Return aggregate correlation score for an evidence pack."""
    scores: list[float] = []
    for item in evidence.all_items():
        scores.append(
            score_evidence_item(item, context, detection_model_id=detection_model_id)
        )
    if not scores:
        return 0.0
    return max(scores)


def determine_s3_status(
    aggregate_score: float,
    evidence: EvidencePack,
    *,
    s2_decision: str | None = None,
) -> S3Status:
    """Map correlation score + evidence presence to S3 status."""
    if s2_decision and s2_decision != ValidationDecision.SUCCESS.value:
        return S3Status.S3_INCONCLUSIVE

    if evidence.evidence_count == 0:
        return S3Status.S3_NOT_OBSERVED

    if aggregate_score >= CONFIRMED_THRESHOLD:
        return S3Status.S3_CONFIRMED

    if aggregate_score >= INCONCLUSIVE_THRESHOLD:
        return S3Status.S3_INCONCLUSIVE

    return S3Status.S3_NOT_OBSERVED


def correlate(
    context: CorrelationContext,
    evidence: EvidencePack,
    *,
    detection_model_id: str | None = None,
) -> tuple[S3Status, float, str]:
    """Full correlation pass — returns status, score, reason."""
    aggregate = score_evidence_pack(evidence, context, detection_model_id=detection_model_id)
    status = determine_s3_status(aggregate, evidence, s2_decision=context.s2_decision)

    if status == S3Status.S3_CONFIRMED:
        reason = f"correlation_score={aggregate:.2f} meets confirmed threshold"
    elif status == S3Status.S3_NOT_OBSERVED:
        if evidence.evidence_count == 0:
            reason = "no vendor evidence returned"
        else:
            reason = f"correlation_score={aggregate:.2f} below not_observed threshold"
    else:
        if context.s2_decision != ValidationDecision.SUCCESS.value:
            reason = f"s2_decision={context.s2_decision}; detection poll skipped"
        else:
            reason = f"correlation_score={aggregate:.2f} inconclusive"

    return status, aggregate, reason
