"""Phase 8 — optional S3 detection confirmation integration tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from dsp.event_store import ValidationDecision, ValidationResult
from dsp.runner import RunManager
from dsp.runner.cli import main
from dsp.validation import ValidationEngine


def test_run_without_confirm_detection_unchanged(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["dummy"],
        dry_run=True,
    )

    assert exit_code == 0
    assert not (run_dir / "evidence").exists()

    report_md = (run_dir / "report.md").read_text()
    assert "## Detection Confirmation" not in report_md

    report_json = json.loads((run_dir / "report.json").read_text())
    assert report_json["detection_confirmation"] is None


def test_run_with_confirm_detection_creates_evidence(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["dummy"],
        dry_run=True,
        confirm_detection=True,
        detection_provider="stellar",
    )

    assert exit_code == 0
    evidence_dir = run_dir / "evidence" / run.run_id / "manual"
    assert evidence_dir.is_dir()
    assert (evidence_dir / "s3_result_manual.json").exists()
    assert (evidence_dir / "s3_manual_checklist.md").exists()

    s3_payload = json.loads((evidence_dir / "s3_result_manual.json").read_text())
    assert s3_payload["vendor"] == "manual"
    assert len(s3_payload["results"]) == 1
    assert s3_payload["results"][0]["status"] == "S3_INCONCLUSIVE"
    assert s3_payload["results"][0]["reason"] == "manual_review_required"

    report_md = (run_dir / "report.md").read_text()
    assert "## Detection Confirmation" in report_md
    assert "S3_INCONCLUSIVE" in report_md

    report_json = json.loads((run_dir / "report.json").read_text())
    assert report_json["detection_confirmation"] is not None
    assert report_json["detection_confirmation"][0]["provider"] == "manual"


def test_unsupported_provider_fails_cleanly(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["dummy"],
        dry_run=True,
        confirm_detection=True,
        detection_provider="splunk",
    )

    assert exit_code == 2
    assert run.status.value == "config_error"
    assert not (run_dir / "events.db").exists()


def test_s2_failure_produces_s3_inconclusive(tmp_runs_dir, monkeypatch):
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
        confirm_detection=True,
    )

    assert exit_code == 1

    validation = json.loads((run_dir / "validation.json").read_text())
    assert validation["results"][0]["decision"] == "failed"

    s3_payload = json.loads(
        (run_dir / "evidence" / run.run_id / "manual" / "s3_result_manual.json").read_text()
    )
    assert s3_payload["results"][0]["status"] == "S3_INCONCLUSIVE"
    assert s3_payload["results"][0]["evidence_count"] == 0


def test_validation_result_unchanged_by_s3(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    _, run_dir, _ = manager.run(
        scenario_ids=["dummy"],
        dry_run=True,
        confirm_detection=True,
    )

    validation = json.loads((run_dir / "validation.json").read_text())
    result = validation["results"][0]
    assert result["decision"] == "success"
    assert result["metrics"]["synthetic_action_count"] >= 3


def test_exit_code_remains_s2_based(tmp_runs_dir, monkeypatch):
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
    _, _, exit_code = manager.run(
        scenario_ids=["dummy"],
        dry_run=True,
        confirm_detection=True,
    )

    assert exit_code == 1


def test_cli_without_confirm_detection(tmp_runs_dir):
    exit_code = main(
        ["run", "--scenarios", "dummy", "--dry-run"],
    )
    assert exit_code == 0

    runs = list(tmp_runs_dir.iterdir())
    assert len(runs) == 1
    run_dir = runs[0]
    assert not (run_dir / "evidence").exists()


def test_cli_with_confirm_detection(tmp_runs_dir):
    exit_code = main(
        [
            "run",
            "--scenarios",
            "dummy",
            "--dry-run",
            "--confirm-detection",
            "--detection-provider",
            "stellar",
        ],
    )
    assert exit_code == 0

    runs = list(tmp_runs_dir.iterdir())
    run_dir = runs[0]
    run_id = run_dir.name
    assert (run_dir / "evidence" / run_id / "manual" / "s3_result_manual.json").exists()


def test_cli_unsupported_provider(tmp_runs_dir):
    exit_code = main(
        [
            "run",
            "--scenarios",
            "dummy",
            "--dry-run",
            "--confirm-detection",
            "--detection-provider",
            "splunk",
        ],
    )
    assert exit_code == 2
