"""Path Equality and Validation Engine tests."""

from __future__ import annotations

from datetime import datetime, timezone

from dsp.event_store import Event, EventStore, ValidationDecision
from dsp.plugins import PluginLoader
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


def _append_traffic(store: EventStore, run_id: str, scenario_id: str, count: int) -> None:
    now = datetime.now(timezone.utc)
    for seq in range(1, count + 1):
        store.append(
            Event(
                run_id=run_id,
                scenario_id=scenario_id,
                timestamp=now,
                stage="executor",
                event="synthetic_action",
                status="sent",
                artifact=f"art-{seq}",
                source="dry_run",
            )
        )


def test_path_equality_synthetic_events():
    store = EventStore(":memory:")
    run_id = "test_run"
    store.open_run(run_id)
    _append_lifecycle(store, run_id, "dummy")
    _append_traffic(store, run_id, "dummy", 5)

    loader = PluginLoader()
    registry = loader.discover_and_load()
    validator = ValidationEngine(store, registry)
    result = validator.validate(run_id, "dummy")

    reporter = ReportingEngine(store, registry)
    report = reporter.generate(run_id, [result])
    table = reporter.build_primary_table_rows([result])

    assert result.metrics["synthetic_action_count"] == 5
    assert result.decision == ValidationDecision.SUCCESS
    assert table[0]["metrics"] == result.metrics
    assert report.traffic_validation[0].metrics == result.metrics


def test_stdout_only_rejected():
    """events=0 after execute marker → code_failure via SOT_EMPTY_AFTER_EXECUTE."""
    store = EventStore(":memory:")
    run_id = "empty_run"
    store.open_run(run_id)
    _append_lifecycle(store, run_id, "dummy")

    loader = PluginLoader()
    registry = loader.discover_and_load()
    validator = ValidationEngine(store, registry)
    result = validator.validate(run_id, "dummy")

    assert result.decision == ValidationDecision.CODE_FAILURE
    assert "SOT_EMPTY_AFTER_EXECUTE" in result.fail_fast_codes


def test_report_regeneration(tmp_path):
    store = EventStore(":memory:")
    run_id = "regen_run"
    store.open_run(run_id)
    _append_lifecycle(store, run_id, "dummy")
    _append_traffic(store, run_id, "dummy", 5)
    store.close_run()

    loader = PluginLoader()
    registry = loader.discover_and_load()
    validator = ValidationEngine(store, registry)
    results = validator.validate_run(run_id, ["dummy"])
    validator.write_validation_json(tmp_path / "validation.json", results)

    reporter = ReportingEngine(store, registry)
    report1 = reporter.generate(run_id, results)
    reporter.write_report_md(tmp_path / "report1.md", report1)

    results2 = validator.validate_run(run_id, ["dummy"])
    report2 = reporter.generate(run_id, results2)
    reporter.write_report_md(tmp_path / "report2.md", report2)

    t1 = tmp_path / "report1.md"
    t2 = tmp_path / "report2.md"
    content1 = t1.read_text().split("**Generated:**")[0]
    content2 = t2.read_text().split("**Generated:**")[0]
    assert content1 == content2


def test_runner_exit_from_validation():
    from dsp.runner import compute_exit_code
    from dsp.event_store import ValidationResult

    success = ValidationResult(
        run_id="r", scenario_id="d", decision=ValidationDecision.SUCCESS,
        reason="ok", metrics={},
    )
    failed = ValidationResult(
        run_id="r", scenario_id="d", decision=ValidationDecision.FAILED,
        reason="bad", metrics={},
    )
    code_fail = ValidationResult(
        run_id="r", scenario_id="d", decision=ValidationDecision.CODE_FAILURE,
        reason="SOT_EMPTY", metrics={},
    )
    assert compute_exit_code([success]) == 0
    assert compute_exit_code([failed]) == 1
    assert compute_exit_code([code_fail]) == 2
