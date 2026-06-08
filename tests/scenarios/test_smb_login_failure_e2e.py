"""SMB login failure scenario E2E tests."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from dsp.runner import RunManager

SMB_TEST_PARAMS = {
    "smb_login_failure": {
        "hosts": ["10.10.10.30"],
        "attempts_per_host": 5,
    }
}


@pytest.fixture
def mock_smb_socket():
    with patch("socket.create_connection") as connect_mock:
        connect_mock.return_value.__enter__.return_value = object()
        yield connect_mock


def test_smb_login_failure_dry_run_e2e(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["smb_login_failure"],
        target_net="10.10.10.0/24",
        dry_run=True,
        scenario_params=SMB_TEST_PARAMS,
    )

    assert run.status.value == "completed"
    assert exit_code == 0
    assert (run_dir / "events.db").exists()
    assert (run_dir / "validation.json").exists()
    assert (run_dir / "report.md").exists()

    validation = json.loads((run_dir / "validation.json").read_text())
    result = validation["results"][0]
    assert result["scenario_id"] == "smb_login_failure"
    assert result["decision"] == "success"
    assert result["metrics"]["smb_auth_attempt_count"] == 5
    assert result["metrics"]["smb_auth_failed_count"] == 5

    report = (run_dir / "report.md").read_text()
    assert "## SMB Login Failure Details" in report
    assert "smb_auth_attempt_count" in report
    assert "administrator" in report or "admin" in report


def test_smb_login_failure_live_e2e(tmp_runs_dir, mock_smb_socket):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["smb_login_failure"],
        target_net="10.10.10.0/24",
        dry_run=False,
        scenario_params=SMB_TEST_PARAMS,
    )

    assert run.status.value == "completed"
    assert exit_code == 0
    assert mock_smb_socket.called

    validation = json.loads((run_dir / "validation.json").read_text())
    result = validation["results"][0]
    assert result["decision"] == "success"
    assert result["metrics"]["smb_auth_attempt_count"] == 5
    assert result["metrics"]["smb_auth_failed_count"] == 5


def test_smb_login_failure_plugins_list():
    from dsp.plugins import PluginLoader, PluginStatus

    registry = PluginLoader().discover_and_load()
    record = registry.get("smb_login_failure")
    assert record is not None
    assert record.status == PluginStatus.ACTIVE
