"""DNS Path Equality tests — Store-only validation and reporting."""

from __future__ import annotations

from datetime import datetime, timezone

from dsp.event_store import Event, EventStore, ValidationDecision
from dsp.plugins import PluginLoader
from dsp.protocols.dns import build_dns_events
from dsp.protocols.dns.client import DnsClient
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


def test_dns_path_equality():
    store = EventStore(":memory:")
    run_id = "dns_pe_run"
    store.open_run(run_id)
    _append_lifecycle(store, run_id, "dns_dummy")

    client = DnsClient(dry_run=True, mock=True)
    for fqdn in ("a.lab.example", "b.lab.example", "c.lab.example"):
        query = client.make_query("10.10.10.20", fqdn)
        result = client.query("10.10.10.20", fqdn)
        for ev in build_dns_events(
            run_id=run_id,
            scenario_id="dns_dummy",
            query=query,
            result=result,
        ):
            store.append(ev)

    loader = PluginLoader()
    registry = loader.discover_and_load()
    validator = ValidationEngine(store, registry)
    result = validator.validate(run_id, "dns_dummy")

    reporter = ReportingEngine(store, registry)
    report = reporter.generate(run_id, [result])
    table = reporter.build_primary_table_rows([result])

    assert result.decision == ValidationDecision.SUCCESS
    assert result.metrics["dns_query_sent_count"] == 3
    assert table[0]["metrics"] == result.metrics
    assert report.traffic_validation[0].metrics == result.metrics


def test_dns_empty_traffic_code_failure():
    store = EventStore(":memory:")
    run_id = "dns_empty"
    store.open_run(run_id)
    _append_lifecycle(store, run_id, "dns_dummy")

    loader = PluginLoader()
    registry = loader.discover_and_load()
    result = ValidationEngine(store, registry).validate(run_id, "dns_dummy")

    assert result.decision == ValidationDecision.CODE_FAILURE
    assert "SOT_EMPTY_AFTER_EXECUTE" in result.fail_fast_codes
