"""Manual S3 evidence pack generation tests."""

from __future__ import annotations

import json

from dsp.detection.providers.manual.manual_adapter import (
    MANUAL_REVIEW_REASON,
    ManualDetectionAdapter,
)
from dsp.detection.models import CorrelationContext, S3Status
from dsp.runner import RunManager
from dsp.runner.cli import main
from datetime import datetime, timezone


def test_manual_adapter_validate_detection_pending_review():
    adapter = ManualDetectionAdapter()
    context = CorrelationContext(
        run_id="20260606_abc123",
        scenario_id="dns_tunnel",
        time_window_start=datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc),
        time_window_end=datetime(2026, 6, 6, 12, 5, tzinfo=timezone.utc),
        source_ip="10.10.10.5",
        destination_ip="10.10.10.20",
        s2_decision="success",
    )
    evidence = adapter.collect_evidence(context)
    result = adapter.validate_detection(context, evidence)

    assert result.status == S3Status.S3_INCONCLUSIVE
    assert result.reason == MANUAL_REVIEW_REASON
    assert result.evidence_count == 0
    assert result.vendor == "manual"


def test_confirm_detection_generates_manual_evidence_pack(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["dummy"],
        dry_run=True,
        confirm_detection=True,
    )

    assert exit_code == 0
    manual_dir = run_dir / "evidence" / run.run_id / "manual"
    assert manual_dir.is_dir()
    assert (manual_dir / "s3_manual_checklist.md").exists()
    assert (manual_dir / "correlation_notes.md").exists()
    assert (manual_dir / "stellar_ui_evidence_template.md").exists()
    assert (manual_dir / "s3_result_manual.json").exists()

    s3_payload = json.loads((manual_dir / "s3_result_manual.json").read_text())
    assert s3_payload["vendor"] == "manual"
    assert s3_payload["results"][0]["status"] == "S3_INCONCLUSIVE"
    assert s3_payload["results"][0]["reason"] == MANUAL_REVIEW_REASON


def test_dsp_runs_without_stellar_env_vars(tmp_runs_dir, monkeypatch):
    monkeypatch.delenv("DSP_STELLAR_BASE_URL", raising=False)
    monkeypatch.delenv("DSP_STELLAR_API_TOKEN", raising=False)

    manager = RunManager(runs_dir=tmp_runs_dir)
    _, _, exit_code = manager.run(scenario_ids=["dummy"], dry_run=True)
    assert exit_code == 0


def test_confirm_detection_without_stellar_env_vars(tmp_runs_dir, monkeypatch):
    monkeypatch.delenv("DSP_STELLAR_BASE_URL", raising=False)
    monkeypatch.delenv("DSP_STELLAR_API_TOKEN", raising=False)

    exit_code = main(
        ["run", "--scenarios", "dummy", "--dry-run", "--confirm-detection"],
    )
    assert exit_code == 0


def test_http_mode_requires_explicit_stellar_client_http(tmp_runs_dir, monkeypatch):
    monkeypatch.delenv("DSP_STELLAR_BASE_URL", raising=False)
    monkeypatch.delenv("DSP_STELLAR_API_TOKEN", raising=False)

    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["dummy"],
        dry_run=True,
        confirm_detection=True,
    )
    assert exit_code == 0
    assert (run_dir / "evidence" / run.run_id / "manual").is_dir()
    assert not (run_dir / "evidence" / run.run_id / "stellar").exists()
