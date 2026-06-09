"""Tests for dsp-remote-scenario CLI and bundle export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dsp.execution.remote.models import ScenarioExecutionRequest
from dsp.execution.webshell.event_sync import load_jsonl_bundle, validate_bundle
from dsp.runner.remote_scenario_cli import execute_remote_scenario, main


def test_remote_scenario_cli_generates_valid_bundle(tmp_path: Path) -> None:
    run_id = "remote_cli_run"
    bundle_path = tmp_path / run_id / "events.jsonl"
    request = ScenarioExecutionRequest(
        scenario_id="dummy",
        scenario_params={"action_count": 3},
        execution_metadata={"remote_bundle_path": str(bundle_path)},
        run_id=run_id,
        target_net="10.10.10.0/24",
        dry_run=True,
    )

    result = execute_remote_scenario(request)

    assert result["exit_code"] == 0
    assert result["bundle_path"] == str(bundle_path)
    assert bundle_path.is_file()

    bundle = load_jsonl_bundle(bundle_path)
    validate_bundle(bundle)
    assert bundle.metadata.run_id == run_id
    assert bundle.metadata.scenario_id == "dummy"
    assert bundle.metadata.event_count == len(bundle.events)
    assert bundle.metadata.event_count >= 3
    assert all(event["source"] == "remote" for event in bundle.events)


def test_remote_scenario_cli_main_returns_zero_on_success(tmp_path: Path) -> None:
    run_id = "remote_cli_main"
    bundle_path = tmp_path / "events.jsonl"
    payload = {
        "scenario_id": "dummy",
        "scenario_params": {"action_count": 2},
        "execution_metadata": {"remote_bundle_path": str(bundle_path)},
        "run_id": run_id,
        "target_net": "10.10.10.0/24",
        "dry_run": True,
    }

    exit_code = main([json.dumps(payload)])

    assert exit_code == 0
    assert bundle_path.is_file()
    bundle = load_jsonl_bundle(bundle_path)
    assert bundle.metadata.event_count >= 2


def test_remote_scenario_cli_main_returns_error_on_invalid_payload() -> None:
    exit_code = main(["not-json"])
    assert exit_code == 1


def test_remote_scenario_cli_requires_bundle_path_metadata(tmp_path: Path) -> None:
    request = ScenarioExecutionRequest(
        scenario_id="dummy",
        run_id="missing_path",
        target_net="10.10.10.0/24",
        dry_run=True,
    )
    with pytest.raises(ValueError, match="remote_bundle_path or remote_work_dir"):
        execute_remote_scenario(request)
