"""RunManager integration with ExecutionProvider — artifact/validation/report parity."""

from __future__ import annotations

import json

from dsp.runner import RunManager


def test_run_manager_uses_execution_provider(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["dummy"],
        target_net="10.10.10.0/24",
        dry_run=True,
    )

    assert run.status.value == "completed"
    assert exit_code == 0
    assert (run_dir / "events.db").exists()
    assert (run_dir / "validation.json").exists()
    assert (run_dir / "report.md").exists()
    assert (run_dir / "report.json").exists()
    assert (run_dir / "events.jsonl").exists()
    assert (run_dir / "run.json").exists()


def test_validation_parity_via_run_manager(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    _, run_dir, exit_code = manager.run(
        scenario_ids=["dummy"],
        dry_run=True,
    )

    assert exit_code == 0
    validation = json.loads((run_dir / "validation.json").read_text())
    results = validation["results"]
    assert len(results) == 1
    assert results[0]["decision"] == "success"
    assert results[0]["metrics"]["synthetic_action_count"] >= 3


def test_report_parity_via_run_manager(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    _, run_dir, _ = manager.run(
        scenario_ids=["dummy"],
        dry_run=True,
    )

    report_md = (run_dir / "report.md").read_text()
    report_json = json.loads((run_dir / "report.json").read_text())

    assert "success" in report_md
    assert "synthetic_action_count" in report_md
    assert report_json["traffic_validation"][0]["decision"] == "success"
    assert report_json["traffic_validation"][0]["metrics"]["synthetic_action_count"] >= 3


def test_artifact_parity_lifecycle_events(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    _, run_dir, _ = manager.run(
        scenario_ids=["dummy"],
        dry_run=True,
    )

    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text().strip().splitlines()
    ]
    lifecycle = [
        e["event"]
        for e in events
        if e["scenario_id"] == "dummy" and e["event"].startswith("scenario_")
    ]
    assert "scenario_started" in lifecycle
    assert "scenario_completed" in lifecycle
