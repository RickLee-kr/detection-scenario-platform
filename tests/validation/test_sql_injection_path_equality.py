"""SQL injection Path Equality tests — Store-only validation and reporting."""

from __future__ import annotations

from datetime import datetime, timezone

from dsp.event_store import Event, EventStore, ValidationDecision
from dsp.plugins import PluginLoader
from dsp.protocols.http.sqli_events import (
    build_sql_payload_generated_event,
    build_sql_request_sent_event,
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


def test_sql_injection_path_equality():
    store = EventStore(":memory:")
    run_id = "sql_injection_pe_run"
    store.open_run(run_id)
    _append_lifecycle(store, run_id, "sql_injection")

    url = "https://10.10.10.20/login?id=1' OR '1'='1"
    for seq in (1, 2, 3):
        store.append(
            build_sql_payload_generated_event(
                run_id=run_id,
                scenario_id="sql_injection",
                target="10.10.10.20",
                url=url,
                source="dry_run",
                evidence={"seq": seq, "query": "id=1' OR '1'='1"},
            )
        )
        store.append(
            build_sql_request_sent_event(
                run_id=run_id,
                scenario_id="sql_injection",
                target="10.10.10.20",
                url=url,
                source="dry_run",
                evidence={"seq": seq},
            )
        )

    loader = PluginLoader()
    registry = loader.discover_and_load()
    validator = ValidationEngine(store, registry)
    result = validator.validate(run_id, "sql_injection")

    reporter = ReportingEngine(store, registry)
    report = reporter.generate(run_id, [result])
    table = reporter.build_primary_table_rows([result])

    assert result.decision == ValidationDecision.SUCCESS
    assert result.metrics["sql_payload_generated_count"] == 3
    assert result.metrics["sql_request_sent_count"] == 3
    assert table[0]["metrics"] == result.metrics
    assert report.traffic_validation[0].metrics == result.metrics


def test_sql_injection_empty_traffic_code_failure():
    store = EventStore(":memory:")
    run_id = "sql_injection_empty"
    store.open_run(run_id)
    _append_lifecycle(store, run_id, "sql_injection")

    loader = PluginLoader()
    registry = loader.discover_and_load()
    result = ValidationEngine(store, registry).validate(run_id, "sql_injection")

    assert result.decision == ValidationDecision.CODE_FAILURE
    assert "SOT_EMPTY_AFTER_EXECUTE" in result.fail_fast_codes
