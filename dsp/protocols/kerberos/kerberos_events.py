"""Kerberos failure event definitions and Event Store mapping."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dsp.event_store import Event
from dsp.protocols.types import KerberosAttempt, KerberosAttemptResult

KERBEROS_SCENARIO_STARTED = "kerberos_scenario_started"
KERBEROS_SCENARIO_COMPLETED = "kerberos_scenario_completed"
KERBEROS_CONNECTION_ATTEMPT = "kerberos_connection_attempt"
KERBEROS_CONNECTION_OPENED = "kerberos_connection_opened"
KERBEROS_CONNECTION_FAILED = "kerberos_connection_failed"
KERBEROS_AUTH_ATTEMPT = "kerberos_auth_attempt"
KERBEROS_AUTH_FAILED = "kerberos_auth_failed"

KERBEROS_FAILURE_TRAFFIC_EVENTS = frozenset(
    {
        KERBEROS_CONNECTION_ATTEMPT,
        KERBEROS_CONNECTION_OPENED,
        KERBEROS_CONNECTION_FAILED,
        KERBEROS_AUTH_ATTEMPT,
        KERBEROS_AUTH_FAILED,
    }
)

CONNECTION_ERROR_STATUSES = frozenset({"error", "timeout", "connection_refused"})


def build_kerberos_scenario_started_event(
    *,
    run_id: str,
    scenario_id: str,
    target: str,
    source: str,
    evidence: dict[str, Any],
) -> Event:
    return Event(
        run_id=run_id,
        scenario_id=scenario_id,
        timestamp=datetime.now(timezone.utc),
        stage="executor",
        event=KERBEROS_SCENARIO_STARTED,
        status="info",
        target=target,
        artifact="kerberos_failure_session",
        evidence=dict(evidence),
        source=source,
    )


def build_kerberos_connection_attempt_event(
    *,
    run_id: str,
    scenario_id: str,
    target: str,
    artifact: str,
    source: str,
    evidence: dict[str, Any],
) -> Event:
    return Event(
        run_id=run_id,
        scenario_id=scenario_id,
        timestamp=datetime.now(timezone.utc),
        stage="executor",
        event=KERBEROS_CONNECTION_ATTEMPT,
        status="sent",
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_kerberos_connection_opened_event(
    *,
    run_id: str,
    scenario_id: str,
    target: str,
    artifact: str,
    source: str,
    evidence: dict[str, Any],
) -> Event:
    return Event(
        run_id=run_id,
        scenario_id=scenario_id,
        timestamp=datetime.now(timezone.utc),
        stage="executor",
        event=KERBEROS_CONNECTION_OPENED,
        status="sent",
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_kerberos_connection_failed_event(
    *,
    run_id: str,
    scenario_id: str,
    target: str,
    artifact: str,
    source: str,
    evidence: dict[str, Any],
    status: str = "connection_refused",
) -> Event:
    return Event(
        run_id=run_id,
        scenario_id=scenario_id,
        timestamp=datetime.now(timezone.utc),
        stage="executor",
        event=KERBEROS_CONNECTION_FAILED,
        status=status,
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_kerberos_auth_attempt_event(
    *,
    run_id: str,
    scenario_id: str,
    target: str,
    artifact: str,
    source: str,
    evidence: dict[str, Any],
) -> Event:
    return Event(
        run_id=run_id,
        scenario_id=scenario_id,
        timestamp=datetime.now(timezone.utc),
        stage="executor",
        event=KERBEROS_AUTH_ATTEMPT,
        status="sent",
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_kerberos_auth_failed_event(
    *,
    run_id: str,
    scenario_id: str,
    target: str,
    artifact: str,
    source: str,
    evidence: dict[str, Any],
) -> Event:
    return Event(
        run_id=run_id,
        scenario_id=scenario_id,
        timestamp=datetime.now(timezone.utc),
        stage="executor",
        event=KERBEROS_AUTH_FAILED,
        status="auth_failed",
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_kerberos_scenario_completed_event(
    *,
    run_id: str,
    scenario_id: str,
    target: str,
    source: str,
    evidence: dict[str, Any],
) -> Event:
    return Event(
        run_id=run_id,
        scenario_id=scenario_id,
        timestamp=datetime.now(timezone.utc),
        stage="executor",
        event=KERBEROS_SCENARIO_COMPLETED,
        status="info",
        target=target,
        artifact="kerberos_failure_session",
        evidence=dict(evidence),
        source=source,
    )


def append_outcome_events(
    *,
    run_id: str,
    scenario_id: str,
    attempt: KerberosAttempt,
    result: KerberosAttemptResult,
    source: str,
) -> list[Event]:
    """Build connection and auth outcome events from a Kerberos attempt result."""
    events: list[Event] = []
    base_evidence: dict[str, Any] = {
        "host": attempt.host,
        "port": attempt.port,
        "username": attempt.username,
        "realm": attempt.realm,
        "attempt_id": result.attempt_id,
        "outcome": result.outcome,
        "dry_run": result.dry_run,
        "safe_mode": attempt.safe_mode,
    }
    if result.evidence:
        base_evidence.update(result.evidence)

    artifact = f"{attempt.username}@{attempt.realm}@{attempt.host}:{attempt.port}"

    if result.connection_opened:
        events.append(
            build_kerberos_connection_opened_event(
                run_id=run_id,
                scenario_id=scenario_id,
                target=attempt.host,
                artifact=artifact,
                source=source,
                evidence=dict(base_evidence),
            )
        )
    elif result.outcome in CONNECTION_ERROR_STATUSES:
        status = (
            result.outcome if result.outcome in CONNECTION_ERROR_STATUSES else "error"
        )
        events.append(
            build_kerberos_connection_failed_event(
                run_id=run_id,
                scenario_id=scenario_id,
                target=attempt.host,
                artifact=artifact,
                source=source,
                evidence=dict(base_evidence),
                status=status,
            )
        )

    if result.outcome == "auth_failed":
        events.append(
            build_kerberos_auth_failed_event(
                run_id=run_id,
                scenario_id=scenario_id,
                target=attempt.host,
                artifact=artifact,
                source=source,
                evidence=dict(base_evidence),
            )
        )

    return events
