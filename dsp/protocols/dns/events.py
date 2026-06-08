"""DNS protocol event definitions and Event Store mapping."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dsp.event_store import Event
from dsp.protocols.types import DnsQuery, DnsQueryResult

# Frozen DNS event verbs (Phase 1B)
DNS_QUERY_CREATED = "dns_query_created"
DNS_QUERY_SENT = "dns_query_sent"
DNS_RESPONSE_RECEIVED = "dns_response_received"
DNS_TIMEOUT = "dns_timeout"
DNS_ERROR = "dns_error"

DNS_TRAFFIC_EVENTS = frozenset(
    {
        DNS_QUERY_SENT,
        DNS_RESPONSE_RECEIVED,
        DNS_TIMEOUT,
        DNS_ERROR,
    }
)

OUTCOME_TO_EVENT: dict[str, tuple[str, str]] = {
    "sent": (DNS_QUERY_SENT, "sent"),
    "response": (DNS_RESPONSE_RECEIVED, "response"),
    "nxdomain": (DNS_RESPONSE_RECEIVED, "nxdomain"),
    "timeout": (DNS_TIMEOUT, "timeout"),
    "error": (DNS_ERROR, "error"),
}


def map_outcome_to_event(outcome: str) -> tuple[str, str]:
    """Map protocol outcome to (event_name, event.status)."""
    if outcome not in OUTCOME_TO_EVENT:
        raise ValueError(f"Unknown DNS outcome: {outcome}")
    return OUTCOME_TO_EVENT[outcome]


def build_dns_events(
    *,
    run_id: str,
    scenario_id: str,
    query: DnsQuery,
    result: DnsQueryResult,
    source: str = "dry_run",
    include_created: bool = True,
) -> list[Event]:
    """Build append-only Event list from a DNS query lifecycle."""
    now = datetime.now(timezone.utc)
    events: list[Event] = []

    base_evidence: dict[str, Any] = {
        "qtype": query.qtype,
        "resolver": query.resolver,
        "port": query.port,
        "query_id": result.query_id,
        "dry_run": result.dry_run,
    }
    if result.evidence:
        base_evidence.update(result.evidence)

    if include_created:
        events.append(
            Event(
                run_id=run_id,
                scenario_id=scenario_id,
                timestamp=now,
                stage="executor",
                event=DNS_QUERY_CREATED,
                status="info",
                target=query.resolver,
                artifact=query.fqdn,
                evidence=dict(base_evidence),
                source=source,
            )
        )

    events.append(
        Event(
            run_id=run_id,
            scenario_id=scenario_id,
            timestamp=now,
            stage="executor",
            event=DNS_QUERY_SENT,
            status="sent",
            target=query.resolver,
            artifact=query.fqdn,
            evidence=dict(base_evidence),
            source=source,
        )
    )

    if result.outcome == "sent":
        return events

    event_name, status = map_outcome_to_event(result.outcome)
    outcome_evidence = dict(base_evidence)
    if result.rcode is not None:
        outcome_evidence["rcode"] = result.rcode
    if result.response_summary:
        outcome_evidence["response"] = result.response_summary

    events.append(
        Event(
            run_id=run_id,
            scenario_id=scenario_id,
            timestamp=now,
            stage="executor",
            event=event_name,
            status=status,
            target=query.resolver,
            artifact=query.fqdn,
            evidence=outcome_evidence,
            source=source,
        )
    )
    return events
