"""Port sweep Path Equality tests — Store-only validation and reporting."""

from __future__ import annotations

from datetime import datetime, timezone

from dsp.event_store import Event, EventStore, ValidationDecision
from dsp.plugins import PluginLoader
from dsp.protocols.recon.port_sweep_events import (
    build_port_connection_failed_event,
    build_port_probe_sent_event,
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


def test_port_sweep_path_equality():
    store = EventStore(":memory:")
    run_id = "port_sweep_pe_run"
    store.open_run(run_id)
    _append_lifecycle(store, run_id, "port_sweep")

    artifact = "10.10.10.30:22"
    for seq in (1, 2, 3):
        store.append(
            build_port_probe_sent_event(
                run_id=run_id,
                scenario_id="port_sweep",
                target="10.10.10.30",
                artifact=artifact,
                source="dry_run",
                evidence={"seq": seq, "port": 22},
            )
        )
        store.append(
            build_port_connection_failed_event(
                run_id=run_id,
                scenario_id="port_sweep",
                target="10.10.10.30",
                artifact=artifact,
                source="dry_run",
                evidence={"seq": seq, "port": 22},
            )
        )

    loader = PluginLoader()
    registry = loader.discover_and_load()
    validator = ValidationEngine(store, registry)
    result = validator.validate(run_id, "port_sweep")

    reporter = ReportingEngine(store, registry)
    report = reporter.generate(run_id, [result])
    table = reporter.build_primary_table_rows([result])

    assert result.decision == ValidationDecision.SUCCESS
    assert result.metrics["port_probe_count"] == 3
    assert result.metrics["port_connection_attempt_count"] == 3
    assert table[0]["metrics"] == result.metrics
    assert report.traffic_validation[0].metrics == result.metrics


def test_port_sweep_empty_traffic_code_failure():
    store = EventStore(":memory:")
    run_id = "port_sweep_empty"
    store.open_run(run_id)
    _append_lifecycle(store, run_id, "port_sweep")

    loader = PluginLoader()
    registry = loader.discover_and_load()
    result = ValidationEngine(store, registry).validate(run_id, "port_sweep")

    assert result.decision == ValidationDecision.CODE_FAILURE
    assert "SOT_EMPTY_AFTER_EXECUTE" in result.fail_fast_codes
