"""LDAP enumeration event definitions and Event Store mapping."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dsp.event_store import Event
from dsp.protocols.types import LdapAction, LdapActionResult

LDAP_ENUM_STARTED = "ldap_enum_started"
LDAP_ENUM_COMPLETED = "ldap_enum_completed"
LDAP_CONNECTION_ATTEMPT = "ldap_connection_attempt"
LDAP_CONNECTION_OPENED = "ldap_connection_opened"
LDAP_CONNECTION_FAILED = "ldap_connection_failed"
LDAP_BIND_ATTEMPT = "ldap_bind_attempt"
LDAP_BIND_FAILED = "ldap_bind_failed"
LDAP_SEARCH_ATTEMPT = "ldap_search_attempt"
LDAP_SEARCH_FAILED = "ldap_search_failed"

LDAP_ENUM_TRAFFIC_EVENTS = frozenset(
    {
        LDAP_CONNECTION_ATTEMPT,
        LDAP_CONNECTION_OPENED,
        LDAP_CONNECTION_FAILED,
        LDAP_BIND_ATTEMPT,
        LDAP_BIND_FAILED,
        LDAP_SEARCH_ATTEMPT,
        LDAP_SEARCH_FAILED,
    }
)

CONNECTION_ERROR_STATUSES = frozenset({"error", "timeout", "connection_refused"})


def build_ldap_enum_started_event(
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
        event=LDAP_ENUM_STARTED,
        status="info",
        target=target,
        artifact="ldap_enum_session",
        evidence=dict(evidence),
        source=source,
    )


def build_ldap_connection_attempt_event(
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
        event=LDAP_CONNECTION_ATTEMPT,
        status="sent",
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_ldap_connection_opened_event(
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
        event=LDAP_CONNECTION_OPENED,
        status="sent",
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_ldap_connection_failed_event(
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
        event=LDAP_CONNECTION_FAILED,
        status=status,
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_ldap_bind_attempt_event(
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
        event=LDAP_BIND_ATTEMPT,
        status="sent",
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_ldap_bind_failed_event(
    *,
    run_id: str,
    scenario_id: str,
    target: str,
    artifact: str,
    source: str,
    evidence: dict[str, Any],
    status: str = "auth_failed",
) -> Event:
    return Event(
        run_id=run_id,
        scenario_id=scenario_id,
        timestamp=datetime.now(timezone.utc),
        stage="executor",
        event=LDAP_BIND_FAILED,
        status=status,
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_ldap_search_attempt_event(
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
        event=LDAP_SEARCH_ATTEMPT,
        status="sent",
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_ldap_search_failed_event(
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
        event=LDAP_SEARCH_FAILED,
        status=status,
        target=target,
        artifact=artifact,
        evidence=dict(evidence),
        source=source,
    )


def build_ldap_enum_completed_event(
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
        event=LDAP_ENUM_COMPLETED,
        status="info",
        target=target,
        artifact="ldap_enum_session",
        evidence=dict(evidence),
        source=source,
    )


def build_attempt_event(
    *,
    run_id: str,
    scenario_id: str,
    action: LdapAction,
    source: str,
    evidence: dict[str, Any],
) -> Event:
    artifact = f"{action.host}:{action.port}:{action.action_type}"
    if action.action_type == "search":
        artifact = f"{action.host}:{action.port}:{action.search_filter}"
    builders = {
        "connection": build_ldap_connection_attempt_event,
        "bind": build_ldap_bind_attempt_event,
        "search": build_ldap_search_attempt_event,
    }
    builder = builders.get(action.action_type)
    if builder is None:
        raise ValueError(f"unknown action_type: {action.action_type}")
    return builder(
        run_id=run_id,
        scenario_id=scenario_id,
        target=action.host,
        artifact=artifact,
        source=source,
        evidence=evidence,
    )


def append_outcome_events(
    *,
    run_id: str,
    scenario_id: str,
    action: LdapAction,
    result: LdapActionResult,
    source: str,
) -> list[Event]:
    """Build LDAP outcome events from an action result."""
    events: list[Event] = []
    base_evidence: dict[str, Any] = {
        "host": action.host,
        "port": action.port,
        "action_type": action.action_type,
        "action_id": result.action_id,
        "outcome": result.outcome,
        "dry_run": result.dry_run,
        "safe_mode": action.safe_mode,
    }
    if action.search_filter:
        base_evidence["filter"] = action.search_filter
    if action.base_dn:
        base_evidence["base_dn"] = action.base_dn
    if result.evidence:
        base_evidence.update(result.evidence)

    artifact = f"{action.host}:{action.port}:{action.action_type}"
    if action.action_type == "search":
        artifact = f"{action.host}:{action.port}:{action.search_filter}"

    if action.action_type == "connection":
        if result.connection_opened or result.outcome == "connection_opened":
            events.append(
                build_ldap_connection_opened_event(
                    run_id=run_id,
                    scenario_id=scenario_id,
                    target=action.host,
                    artifact=artifact,
                    source=source,
                    evidence=dict(base_evidence),
                )
            )
        else:
            status = result.outcome if result.outcome in CONNECTION_ERROR_STATUSES else "error"
            events.append(
                build_ldap_connection_failed_event(
                    run_id=run_id,
                    scenario_id=scenario_id,
                    target=action.host,
                    artifact=artifact,
                    source=source,
                    evidence=dict(base_evidence),
                    status=status,
                )
            )
    elif action.action_type == "bind":
        if result.outcome in ("auth_failed", "error", "timeout", "connection_refused"):
            status = "auth_failed" if result.outcome == "auth_failed" else result.outcome
            if status not in CONNECTION_ERROR_STATUSES and status != "auth_failed":
                status = "error"
            events.append(
                build_ldap_bind_failed_event(
                    run_id=run_id,
                    scenario_id=scenario_id,
                    target=action.host,
                    artifact=artifact,
                    source=source,
                    evidence=dict(base_evidence),
                    status=status if status == "auth_failed" else "error",
                )
            )
    elif action.action_type == "search":
        if result.outcome != "search_success":
            status = result.outcome if result.outcome in CONNECTION_ERROR_STATUSES else "error"
            events.append(
                build_ldap_search_failed_event(
                    run_id=run_id,
                    scenario_id=scenario_id,
                    target=action.host,
                    artifact=artifact,
                    source=source,
                    evidence=dict(base_evidence),
                    status=status,
                )
            )

    return events
