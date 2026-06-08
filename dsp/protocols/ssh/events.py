"""SSH login failure event definitions and Event Store mapping."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dsp.event_store import Event
from dsp.protocols.types import SshAttempt, SshAttemptResult

SSH_FAILURE_STARTED = "ssh_failure_started"
SSH_AUTH_ATTEMPT = "ssh_auth_attempt"
SSH_AUTH_FAILED = "ssh_auth_failed"
SSH_CONNECTION_ERROR = "ssh_connection_error"
SSH_FAILURE_COMPLETED = "ssh_failure_completed"

SSH_FAILURE_TRAFFIC_EVENTS = frozenset(
    {
        SSH_AUTH_ATTEMPT,
        SSH_AUTH_FAILED,
        SSH_CONNECTION_ERROR,
    }
)

CONNECTION_ERROR_STATUSES = frozenset({"error", "timeout", "connection_refused"})


def build_ssh_failure_started_event(
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
        event=SSH_FAILURE_STARTED,
        status="info",
        target=target,
        artifact="ssh_failure_session",
        evidence=dict(evidence),
        source=source,
    )


def build_ssh_auth_attempt_event(
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
        event=SSH_AUTH_ATTEMPT,
        status="sent",
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_ssh_auth_failed_event(
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
        event=SSH_AUTH_FAILED,
        status="auth_failed",
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_ssh_connection_error_event(
    *,
    run_id: str,
    scenario_id: str,
    target: str,
    artifact: str,
    source: str,
    evidence: dict[str, Any],
    status: str = "error",
) -> Event:
    return Event(
        run_id=run_id,
        scenario_id=scenario_id,
        timestamp=datetime.now(timezone.utc),
        stage="executor",
        event=SSH_CONNECTION_ERROR,
        status=status,
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_ssh_failure_completed_event(
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
        event=SSH_FAILURE_COMPLETED,
        status="info",
        target=target,
        artifact="ssh_failure_session",
        evidence=dict(evidence),
        source=source,
    )


def append_outcome_event(
    *,
    run_id: str,
    scenario_id: str,
    attempt: SshAttempt,
    result: SshAttemptResult,
    source: str,
    password_label: str,
) -> Event:
    """Build auth_failed or connection_error event from SSH attempt result."""
    evidence: dict[str, Any] = {
        "host": attempt.host,
        "port": attempt.port,
        "username": attempt.username,
        "password_label": password_label,
        "attempt_id": result.attempt_id,
        "outcome": result.outcome,
        "dry_run": result.dry_run,
    }
    if result.evidence:
        evidence.update(result.evidence)

    artifact = f"{attempt.username}@{attempt.host}:{attempt.port}"

    if result.outcome == "auth_failed":
        return build_ssh_auth_failed_event(
            run_id=run_id,
            scenario_id=scenario_id,
            target=attempt.host,
            artifact=artifact,
            source=source,
            evidence=evidence,
        )

    status = result.outcome if result.outcome in CONNECTION_ERROR_STATUSES else "error"
    return build_ssh_connection_error_event(
        run_id=run_id,
        scenario_id=scenario_id,
        target=attempt.host,
        artifact=artifact,
        source=source,
        evidence=evidence,
        status=status,
    )
