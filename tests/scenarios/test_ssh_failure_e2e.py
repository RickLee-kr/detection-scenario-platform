"""SSH login failure scenario E2E tests."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from dsp.runner import RunManager

SSH_TEST_PARAMS = {
    "ssh_failure": {
        "hosts": ["10.10.10.20"],
        "max_total": 5,
        "max_per_host": 5,
    }
}


@pytest.fixture
def mock_ssh_subprocess():
    completed = MagicMock()
    completed.returncode = 255
    completed.stderr = "Permission denied (publickey)."

    with patch("subprocess.run", return_value=completed) as run_mock:
        yield run_mock


def test_ssh_failure_dry_run_e2e(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["ssh_failure"],
        target_net="10.10.10.0/24",
        dry_run=True,
        scenario_params=SSH_TEST_PARAMS,
    )

    assert run.status.value == "completed"
    assert exit_code == 0
    assert (run_dir / "events.db").exists()
    assert (run_dir / "validation.json").exists()
    assert (run_dir / "report.md").exists()

    validation = json.loads((run_dir / "validation.json").read_text())
    result = validation["results"][0]
    assert result["scenario_id"] == "ssh_failure"
    assert result["decision"] == "success"
    assert result["metrics"]["ssh_auth_attempt_count"] == 5
    assert result["metrics"]["ssh_auth_failed_count"] == 5

    report = (run_dir / "report.md").read_text()
    assert "## SSH Login Failure Details" in report
    assert "ssh_auth_attempt_count" in report
    assert "admin" in report or "root" in report


def test_ssh_failure_live_e2e(tmp_runs_dir, mock_ssh_subprocess):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["ssh_failure"],
        target_net="10.10.10.0/24",
        dry_run=False,
        scenario_params=SSH_TEST_PARAMS,
    )

    assert run.status.value == "completed"
    assert exit_code == 0
    assert mock_ssh_subprocess.called

    validation = json.loads((run_dir / "validation.json").read_text())
    result = validation["results"][0]
    assert result["decision"] == "success"
    assert result["metrics"]["ssh_auth_attempt_count"] == 5
    assert result["metrics"]["ssh_auth_failed_count"] == 5


def test_ssh_failure_plugins_list():
    from dsp.plugins import PluginLoader, PluginStatus

    registry = PluginLoader().discover_and_load()
    record = registry.get("ssh_failure")
    assert record is not None
    assert record.status == PluginStatus.ACTIVE
