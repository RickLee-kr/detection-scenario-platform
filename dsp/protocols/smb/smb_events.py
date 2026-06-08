"""SMB login failure event definitions and Event Store mapping."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dsp.event_store import Event
from dsp.protocols.types import SmbAttempt, SmbAttemptResult

SMB_SCENARIO_STARTED = "smb_scenario_started"
SMB_AUTH_ATTEMPT = "smb_auth_attempt"
SMB_AUTH_FAILED = "smb_auth_failed"
SMB_CONNECTION_OPENED = "smb_connection_opened"
SMB_CONNECTION_FAILED = "smb_connection_failed"
SMB_SCENARIO_COMPLETED = "smb_scenario_completed"

SMB_LOGIN_FAILURE_TRAFFIC_EVENTS = frozenset(
    {
        SMB_AUTH_ATTEMPT,
        SMB_AUTH_FAILED,
        SMB_CONNECTION_OPENED,
        SMB_CONNECTION_FAILED,
    }
)

CONNECTION_ERROR_STATUSES = frozenset({"error", "timeout", "connection_refused"})


def build_smb_scenario_started_event(
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
        event=SMB_SCENARIO_STARTED,
        status="info",
        target=target,
        artifact="smb_login_failure_session",
        evidence=dict(evidence),
        source=source,
    )


def build_smb_connection_opened_event(
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
        event=SMB_CONNECTION_OPENED,
        status="sent",
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_smb_connection_failed_event(
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
        event=SMB_CONNECTION_FAILED,
        status=status,
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_smb_auth_attempt_event(
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
        event=SMB_AUTH_ATTEMPT,
        status="sent",
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_smb_auth_failed_event(
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
        event=SMB_AUTH_FAILED,
        status="auth_failed",
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_smb_scenario_completed_event(
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
        event=SMB_SCENARIO_COMPLETED,
        status="info",
        target=target,
        artifact="smb_login_failure_session",
        evidence=dict(evidence),
        source=source,
    )


def append_outcome_events(
    *,
    run_id: str,
    scenario_id: str,
    attempt: SmbAttempt,
    result: SmbAttemptResult,
    source: str,
    password_label: str,
) -> list[Event]:
    """Build connection and auth outcome events from an SMB attempt result."""
    events: list[Event] = []
    base_evidence: dict[str, Any] = {
        "host": attempt.host,
        "port": attempt.port,
        "username": attempt.username,
        "password_label": password_label,
        "attempt_id": result.attempt_id,
        "outcome": result.outcome,
        "dry_run": result.dry_run,
        "safe_mode": attempt.safe_mode,
    }
    if result.evidence:
        base_evidence.update(result.evidence)

    artifact = f"{attempt.username}@{attempt.host}:{attempt.port}"

    if result.connection_opened:
        events.append(
            build_smb_connection_opened_event(
                run_id=run_id,
                scenario_id=scenario_id,
                target=attempt.host,
                artifact=artifact,
                source=source,
                evidence=dict(base_evidence),
            )
        )
    elif result.outcome in CONNECTION_ERROR_STATUSES:
        status = result.outcome if result.outcome in CONNECTION_ERROR_STATUSES else "error"
        events.append(
            build_smb_connection_failed_event(
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
            build_smb_auth_failed_event(
                run_id=run_id,
                scenario_id=scenario_id,
                target=attempt.host,
                artifact=artifact,
                source=source,
                evidence=dict(base_evidence),
            )
        )

    return events
