"""LDAP enumeration Path Equality tests — Store-only validation and reporting."""

from __future__ import annotations

from datetime import datetime, timezone

from dsp.event_store import Event, EventStore, ValidationDecision
from dsp.plugins import PluginLoader
from dsp.protocols.ldap.ldap_events import (
    build_ldap_bind_attempt_event,
    build_ldap_bind_failed_event,
    build_ldap_connection_attempt_event,
    build_ldap_connection_opened_event,
)
from dsp.reporting import ReportingEngine
from dsp.validation import ValidationEngine


def _append_lifecycle(store: EventStore, run_id: str, scenario_id: str) -> None:
    now = datetime.now(timezone.utc)
    for event_name in ("scenario_started", "scenario_completed"):
        store.append(
            Event(
                run_id=run_id,
                scenario_id=scenario_id,
                timestamp=now,
                stage="executor",
                event=event_name,
                status="info",
                source="runner",
            )
        )


def test_ldap_enumeration_path_equality():
    store = EventStore(":memory:")
    run_id = "ldap_enum_pe_run"
    store.open_run(run_id)
    _append_lifecycle(store, run_id, "ldap_enumeration")

    artifact = "10.10.10.30:389:connection"
    store.append(
        build_ldap_connection_attempt_event(
            run_id=run_id,
            scenario_id="ldap_enumeration",
            target="10.10.10.30",
            artifact=artifact,
            source="dry_run",
            evidence={"seq": 1},
        )
    )
    store.append(
        build_ldap_connection_opened_event(
            run_id=run_id,
            scenario_id="ldap_enumeration",
            target="10.10.10.30",
            artifact=artifact,
            source="dry_run",
            evidence={"seq": 1},
        )
    )
    store.append(
        build_ldap_bind_attempt_event(
            run_id=run_id,
            scenario_id="ldap_enumeration",
            target="10.10.10.30",
            artifact="10.10.10.30:389:bind",
            source="dry_run",
            evidence={"seq": 2},
        )
    )
    store.append(
        build_ldap_bind_failed_event(
            run_id=run_id,
            scenario_id="ldap_enumeration",
            target="10.10.10.30",
            artifact="10.10.10.30:389:bind",
            source="dry_run",
            evidence={"seq": 2},
        )
    )

    loader = PluginLoader()
    registry = loader.discover_and_load()
    validator = ValidationEngine(store, registry)
    result = validator.validate(run_id, "ldap_enumeration")

    reporter = ReportingEngine(store, registry)
    report = reporter.generate(run_id, [result])
    table = reporter.build_primary_table_rows([result])

    assert result.decision == ValidationDecision.SUCCESS
    assert result.metrics["ldap_connection_attempt_count"] == 1
    assert result.metrics["ldap_bind_or_search_attempt_count"] == 1
    assert table[0]["metrics"] == result.metrics
    assert report.traffic_validation[0].metrics == result.metrics


def test_ldap_enumeration_empty_traffic_code_failure():
    store = EventStore(":memory:")
    run_id = "ldap_enum_empty"
    store.open_run(run_id)
    _append_lifecycle(store, run_id, "ldap_enumeration")

    loader = PluginLoader()
    registry = loader.discover_and_load()
    result = ValidationEngine(store, registry).validate(run_id, "ldap_enumeration")

    assert result.decision == ValidationDecision.CODE_FAILURE
    assert "SOT_EMPTY_AFTER_EXECUTE" in result.fail_fast_codes
