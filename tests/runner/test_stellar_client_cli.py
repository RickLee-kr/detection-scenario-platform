"""CLI and RunManager integration for --stellar-client."""

from __future__ import annotations

import json
from unittest.mock import patch

from dsp.detection.providers.stellar.http_client import HttpResponse
from dsp.detection.providers.stellar.stellar_config import ENV_API_TOKEN, ENV_BASE_URL
from dsp.runner import RunManager
from dsp.runner.cli import main


class _AllOkTransport:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, **kwargs) -> HttpResponse:
        self.calls += 1
        body = json.dumps({"items": []}).encode()
        return HttpResponse(status_code=200, body=body, headers={})


def test_stellar_client_manual_is_default(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["dummy"],
        dry_run=True,
        confirm_detection=True,
    )

    assert exit_code == 0
    manual_dir = run_dir / "evidence" / run.run_id / "manual"
    assert manual_dir.is_dir()
    s3_payload = json.loads((manual_dir / "s3_result_manual.json").read_text())
    assert s3_payload["results"][0]["status"] == "S3_INCONCLUSIVE"
    assert s3_payload["results"][0]["reason"] == "manual_review_required"


def test_stellar_client_mock_explicit(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["dummy"],
        dry_run=True,
        confirm_detection=True,
        stellar_client="mock",
    )

    assert exit_code == 0
    s3_payload = json.loads(
        (run_dir / "evidence" / run.run_id / "stellar" / "s3_result.json").read_text()
    )
    assert s3_payload["results"][0]["status"] == "S3_CONFIRMED"


def test_stellar_client_http_missing_config_is_inconclusive(tmp_runs_dir, monkeypatch):
    monkeypatch.delenv(ENV_BASE_URL, raising=False)
    monkeypatch.delenv(ENV_API_TOKEN, raising=False)

    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["dummy"],
        dry_run=True,
        confirm_detection=True,
        stellar_client="http",
    )

    assert exit_code == 0
    s3_payload = json.loads(
        (run_dir / "evidence" / run.run_id / "stellar" / "s3_result.json").read_text()
    )
    assert s3_payload["results"][0]["status"] == "S3_INCONCLUSIVE"

    evidence_md = (
        run_dir / "evidence" / run.run_id / "stellar" / "evidence.md"
    ).read_text()
    assert "S3 Inconclusive" in evidence_md


def test_stellar_client_http_with_mocked_responses(tmp_runs_dir, monkeypatch):
    transport = _AllOkTransport()
    monkeypatch.setenv(ENV_BASE_URL, "https://stellar.example")
    monkeypatch.setenv(ENV_API_TOKEN, "secret-token")

    with patch(
        "dsp.detection.providers.stellar.http_client.UrllibHttpTransport",
        return_value=transport,
    ):
        manager = RunManager(runs_dir=tmp_runs_dir)
        run, run_dir, exit_code = manager.run(
            scenario_ids=["dummy"],
            dry_run=True,
            confirm_detection=True,
            stellar_client="http",
        )

    assert exit_code == 0
    assert transport.calls >= 4
    s3_payload = json.loads(
        (run_dir / "evidence" / run.run_id / "stellar" / "s3_result.json").read_text()
    )
    assert s3_payload["results"][0]["status"] == "S3_NOT_OBSERVED"


def test_http_client_failure_does_not_change_s2_exit_code(tmp_runs_dir, monkeypatch):
    monkeypatch.delenv(ENV_BASE_URL, raising=False)
    monkeypatch.delenv(ENV_API_TOKEN, raising=False)

    manager = RunManager(runs_dir=tmp_runs_dir)
    _, _, exit_code = manager.run(
        scenario_ids=["dummy"],
        dry_run=True,
        confirm_detection=True,
        stellar_client="http",
    )
    assert exit_code == 0


def test_cli_stellar_client_manual_default(tmp_runs_dir):
    exit_code = main(["run", "--scenarios", "dummy", "--dry-run", "--confirm-detection"])
    assert exit_code == 0


def test_cli_stellar_client_http(tmp_runs_dir, monkeypatch):
    monkeypatch.delenv(ENV_BASE_URL, raising=False)
    monkeypatch.delenv(ENV_API_TOKEN, raising=False)

    exit_code = main(
        [
            "run",
            "--scenarios",
            "dummy",
            "--dry-run",
            "--confirm-detection",
            "--stellar-client",
            "http",
        ]
    )
    assert exit_code == 0


def test_unsupported_stellar_client_mode_fails_cleanly(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, _, exit_code = manager.run(
        scenario_ids=["dummy"],
        dry_run=True,
        confirm_detection=True,
        stellar_client="splunk",
    )
    assert exit_code == 2
    assert run.status.value == "config_error"
