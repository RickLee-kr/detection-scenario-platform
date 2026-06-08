"""DNS Tunnel event definitions and Event Store mapping."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dsp.event_store import Event

DNS_TUNNEL_STARTED = "dns_tunnel_started"
DNS_TUNNEL_CHUNK_CREATED = "dns_tunnel_chunk_created"
DNS_TUNNEL_QUERY_SENT = "dns_tunnel_query_sent"
DNS_TUNNEL_COMPLETED = "dns_tunnel_completed"

DNS_TUNNEL_TRAFFIC_EVENTS = frozenset(
    {
        DNS_TUNNEL_CHUNK_CREATED,
        DNS_TUNNEL_QUERY_SENT,
    }
)


def build_tunnel_started_event(
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
        event=DNS_TUNNEL_STARTED,
        status="info",
        target=target,
        artifact="tunnel_session",
        evidence=dict(evidence),
        source=source,
    )


def build_tunnel_chunk_created_event(
    *,
    run_id: str,
    scenario_id: str,
    target: str,
    fqdn: str,
    source: str,
    evidence: dict[str, Any],
) -> Event:
    return Event(
        run_id=run_id,
        scenario_id=scenario_id,
        timestamp=datetime.now(timezone.utc),
        stage="executor",
        event=DNS_TUNNEL_CHUNK_CREATED,
        status="info",
        target=target,
        artifact=fqdn,
        evidence=dict(evidence),
        source=source,
    )


def build_tunnel_query_sent_event(
    *,
    run_id: str,
    scenario_id: str,
    target: str,
    fqdn: str,
    source: str,
    evidence: dict[str, Any],
) -> Event:
    return Event(
        run_id=run_id,
        scenario_id=scenario_id,
        timestamp=datetime.now(timezone.utc),
        stage="executor",
        event=DNS_TUNNEL_QUERY_SENT,
        status="sent",
        target=target,
        artifact=fqdn,
        evidence=dict(evidence),
        source=source,
    )


def build_tunnel_completed_event(
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
        event=DNS_TUNNEL_COMPLETED,
        status="info",
        target=target,
        artifact="tunnel_session",
        evidence=dict(evidence),
        source=source,
    )
