"""SMB login failure Path Equality tests — Store-only validation and reporting."""

from __future__ import annotations

from datetime import datetime, timezone

from dsp.event_store import Event, EventStore, ValidationDecision
from dsp.plugins import PluginLoader
from dsp.protocols.smb.smb_events import (
    build_smb_auth_attempt_event,
    build_smb_auth_failed_event,
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


def test_smb_login_failure_path_equality():
    store = EventStore(":memory:")
    run_id = "smb_login_failure_pe_run"
    store.open_run(run_id)
    _append_lifecycle(store, run_id, "smb_login_failure")

    artifact = "administrator@10.10.10.30:445"
    for seq in (1, 2, 3):
        store.append(
            build_smb_auth_attempt_event(
                run_id=run_id,
                scenario_id="smb_login_failure",
                target="10.10.10.30",
                artifact=artifact,
                source="dry_run",
                evidence={"seq": seq, "username": "administrator"},
            )
        )
        store.append(
            build_smb_auth_failed_event(
                run_id=run_id,
                scenario_id="smb_login_failure",
                target="10.10.10.30",
                artifact=artifact,
                source="dry_run",
                evidence={"seq": seq, "username": "administrator"},
            )
        )

    loader = PluginLoader()
    registry = loader.discover_and_load()
    validator = ValidationEngine(store, registry)
    result = validator.validate(run_id, "smb_login_failure")

    reporter = ReportingEngine(store, registry)
    report = reporter.generate(run_id, [result])
    table = reporter.build_primary_table_rows([result])

    assert result.decision == ValidationDecision.SUCCESS
    assert result.metrics["smb_auth_attempt_count"] == 3
    assert result.metrics["smb_auth_failed_count"] == 3
    assert table[0]["metrics"] == result.metrics
    assert report.traffic_validation[0].metrics == result.metrics


def test_smb_login_failure_empty_traffic_code_failure():
    store = EventStore(":memory:")
    run_id = "smb_login_failure_empty"
    store.open_run(run_id)
    _append_lifecycle(store, run_id, "smb_login_failure")

    loader = PluginLoader()
    registry = loader.discover_and_load()
    result = ValidationEngine(store, registry).validate(run_id, "smb_login_failure")

    assert result.decision == ValidationDecision.CODE_FAILURE
    assert "SOT_EMPTY_AFTER_EXECUTE" in result.fail_fast_codes
