"""Run metadata consistency across run.json, report.json, and report.md."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from dsp.event_store import ValidationDecision, ValidationResult
from dsp.runner import RunManager
from dsp.validation import ValidationEngine


def _extract_run_metadata_from_report_md(report_md: str) -> dict:
    marker = "## Run Metadata"
    start = report_md.find(marker)
    assert start != -1, "Run Metadata section not found in report.md"
    fence_start = report_md.find("```json", start)
    assert fence_start != -1
    body_start = report_md.find("\n", fence_start) + 1
    fence_end = report_md.find("```", body_start)
    return json.loads(report_md[body_start:fence_end].strip())


def test_completed_run_metadata_consistent_across_artifacts(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["dummy"],
        dry_run=True,
    )

    assert exit_code == 0
    assert run.status.value == "completed"
    assert run.ended_at is not None

    run_json = json.loads((run_dir / "run.json").read_text())
    report_json = json.loads((run_dir / "report.json").read_text())
    report_md = (run_dir / "report.md").read_text()
    run_md_meta = _extract_run_metadata_from_report_md(report_md)

    for artifact_status in (
        run_json["status"],
        report_json["run_metadata"]["status"],
        run_md_meta["status"],
    ):
        assert artifact_status == "completed"

    for artifact_ended_at in (
        run_json["ended_at"],
        report_json["run_metadata"]["ended_at"],
        run_md_meta["ended_at"],
    ):
        assert artifact_ended_at is not None
        assert artifact_ended_at.endswith("Z") or "+" in artifact_ended_at

    assert run_json["run_id"] == report_json["run_id"] == run_md_meta["run_id"]


def test_confirm_detection_run_metadata_still_consistent(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["dummy"],
        dry_run=True,
        confirm_detection=True,
    )

    assert exit_code == 0

    run_json = json.loads((run_dir / "run.json").read_text())
    report_json = json.loads((run_dir / "report.json").read_text())
    run_md_meta = _extract_run_metadata_from_report_md((run_dir / "report.md").read_text())

    assert run_json["status"] == report_json["run_metadata"]["status"] == run_md_meta["status"] == "completed"
    assert run_json["ended_at"] == report_json["run_metadata"]["ended_at"] == run_md_meta["ended_at"]


def test_validation_failure_metadata_still_consistent(tmp_runs_dir, monkeypatch):
    def mock_validate_run(self, run_id, scenario_ids):
        return [
            ValidationResult(
                run_id=run_id,
                scenario_id=scenario_ids[0],
                decision=ValidationDecision.FAILED,
                reason="test_failure",
                metrics={},
                validated_at=datetime.now(timezone.utc),
            )
        ]

    monkeypatch.setattr(ValidationEngine, "validate_run", mock_validate_run)

    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["dummy"],
        dry_run=True,
    )

    assert exit_code == 1
    assert run.status.value == "completed"
    assert run.ended_at is not None

    run_json = json.loads((run_dir / "run.json").read_text())
    report_json = json.loads((run_dir / "report.json").read_text())
    run_md_meta = _extract_run_metadata_from_report_md((run_dir / "report.md").read_text())

    assert run_json["status"] == report_json["run_metadata"]["status"] == run_md_meta["status"] == "completed"
    assert run_json["ended_at"] is not None
    assert report_json["run_metadata"]["ended_at"] is not None
    assert run_md_meta["ended_at"] is not None

    validation = json.loads((run_dir / "validation.json").read_text())
    assert validation["results"][0]["decision"] == "failed"


def test_report_does_not_contain_running_status(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    _, run_dir, _ = manager.run(scenario_ids=["dummy"], dry_run=True)

    report_md = (run_dir / "report.md").read_text()
    report_json = json.loads((run_dir / "report.json").read_text())

    assert '"status": "running"' not in report_md
    assert report_json["run_metadata"]["status"] != "running"
    assert report_json["run_metadata"]["ended_at"] is not None
