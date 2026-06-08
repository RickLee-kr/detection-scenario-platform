"""SQL injection event definitions and Event Store mapping."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dsp.event_store import Event
from dsp.protocols.types import HttpRequest, HttpResponseResult

SQL_INJECTION_STARTED = "sql_injection_started"
SQL_PAYLOAD_GENERATED = "sql_payload_generated"
SQL_REQUEST_SENT = "sql_request_sent"
SQL_RESPONSE_RECEIVED = "sql_response_received"
SQL_REQUEST_ERROR = "sql_request_error"
SQL_INJECTION_COMPLETED = "sql_injection_completed"

SQL_INJECTION_TRAFFIC_EVENTS = frozenset(
    {
        SQL_PAYLOAD_GENERATED,
        SQL_REQUEST_SENT,
        SQL_RESPONSE_RECEIVED,
        SQL_REQUEST_ERROR,
    }
)

OUTCOME_TO_STATUS: dict[str, str] = {
    "response": "response",
    "timeout": "error",
    "connection_refused": "connection_refused",
    "dns_failure": "dns_failure",
    "error": "error",
}


def build_sql_injection_started_event(
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
        event=SQL_INJECTION_STARTED,
        status="info",
        target=target,
        artifact="sql_injection_session",
        evidence=dict(evidence),
        source=source,
    )


def build_sql_payload_generated_event(
    *,
    run_id: str,
    scenario_id: str,
    target: str,
    url: str,
    source: str,
    evidence: dict[str, Any],
) -> Event:
    return Event(
        run_id=run_id,
        scenario_id=scenario_id,
        timestamp=datetime.now(timezone.utc),
        stage="executor",
        event=SQL_PAYLOAD_GENERATED,
        status="info",
        target=target,
        artifact=url,
        evidence=dict(evidence),
        source=source,
    )


def build_sql_request_sent_event(
    *,
    run_id: str,
    scenario_id: str,
    target: str,
    url: str,
    source: str,
    evidence: dict[str, Any],
) -> Event:
    return Event(
        run_id=run_id,
        scenario_id=scenario_id,
        timestamp=datetime.now(timezone.utc),
        stage="executor",
        event=SQL_REQUEST_SENT,
        status="sent",
        target=target,
        artifact=url,
        evidence=dict(evidence),
        source=source,
    )


def build_sql_response_received_event(
    *,
    run_id: str,
    scenario_id: str,
    target: str,
    url: str,
    source: str,
    evidence: dict[str, Any],
) -> Event:
    return Event(
        run_id=run_id,
        scenario_id=scenario_id,
        timestamp=datetime.now(timezone.utc),
        stage="executor",
        event=SQL_RESPONSE_RECEIVED,
        status="response",
        target=target,
        artifact=url,
        evidence=dict(evidence),
        source=source,
    )


def build_sql_request_error_event(
    *,
    run_id: str,
    scenario_id: str,
    target: str,
    url: str,
    source: str,
    evidence: dict[str, Any],
    status: str = "error",
) -> Event:
    return Event(
        run_id=run_id,
        scenario_id=scenario_id,
        timestamp=datetime.now(timezone.utc),
        stage="executor",
        event=SQL_REQUEST_ERROR,
        status=status,
        target=target,
        artifact=url,
        evidence=dict(evidence),
        source=source,
    )


def build_sql_injection_completed_event(
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
        event=SQL_INJECTION_COMPLETED,
        status="info",
        target=target,
        artifact="sql_injection_session",
        evidence=dict(evidence),
        source=source,
    )


def append_sqli_outcome_event(
    *,
    run_id: str,
    scenario_id: str,
    request: HttpRequest,
    result: HttpResponseResult,
    source: str,
    payload: str,
) -> Event:
    """Build sql_response_received or sql_request_error from HTTP result."""
    evidence: dict[str, Any] = {
        "method": request.method,
        "host": request.host,
        "port": request.port,
        "path": request.path,
        "payload": payload,
        "request_id": result.request_id,
        "outcome": result.outcome,
        "dry_run": result.dry_run,
    }
    if result.status_code is not None:
        evidence["status_code"] = result.status_code
    if result.response_summary:
        evidence["response"] = result.response_summary

    if result.outcome == "response":
        return build_sql_response_received_event(
            run_id=run_id,
            scenario_id=scenario_id,
            target=request.host,
            url=request.url,
            source=source,
            evidence=evidence,
        )

    status = OUTCOME_TO_STATUS.get(result.outcome, "error")
    return build_sql_request_error_event(
        run_id=run_id,
        scenario_id=scenario_id,
        target=request.host,
        url=request.url,
        source=source,
        evidence=evidence,
        status=status,
    )
