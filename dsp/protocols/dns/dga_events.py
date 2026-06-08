"""DGA event definitions and Event Store mapping."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dsp.event_store import Event

DGA_STARTED = "dga_started"
DGA_DOMAIN_GENERATED = "dga_domain_generated"
DGA_NXDOMAIN_OBSERVED = "dga_nxdomain_observed"
DGA_RESOLVED_OBSERVED = "dga_resolved_observed"
DGA_COMPLETED = "dga_completed"

DGA_TRAFFIC_EVENTS = frozenset(
    {
        DGA_DOMAIN_GENERATED,
        DGA_NXDOMAIN_OBSERVED,
        DGA_RESOLVED_OBSERVED,
    }
)


def build_dga_started_event(
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
        event=DGA_STARTED,
        status="info",
        target=target,
        artifact="dga_session",
        evidence=dict(evidence),
        source=source,
    )


def build_dga_domain_generated_event(
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
        event=DGA_DOMAIN_GENERATED,
        status="info",
        target=target,
        artifact=fqdn,
        evidence=dict(evidence),
        source=source,
    )


def build_dga_nxdomain_observed_event(
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
        event=DGA_NXDOMAIN_OBSERVED,
        status="nxdomain",
        target=target,
        artifact=fqdn,
        evidence=dict(evidence),
        source=source,
    )


def build_dga_resolved_observed_event(
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
        event=DGA_RESOLVED_OBSERVED,
        status="response",
        target=target,
        artifact=fqdn,
        evidence=dict(evidence),
        source=source,
    )


def build_dga_completed_event(
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
        event=DGA_COMPLETED,
        status="info",
        target=target,
        artifact="dga_session",
        evidence=dict(evidence),
        source=source,
    )
