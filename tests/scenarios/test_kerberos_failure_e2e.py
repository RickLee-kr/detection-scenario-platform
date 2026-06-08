"""Kerberos failure scenario E2E tests."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from dsp.runner import RunManager

KERBEROS_TEST_PARAMS = {
    "kerberos_failure": {
        "hosts": ["10.10.10.30"],
        "attempts_per_host": 5,
    }
}


@pytest.fixture
def mock_kerberos_udp():
    mock_sock = MagicMock()
    mock_sock.recvfrom.return_value = (b"\x7e\x00", ("10.10.10.30", 88))
    with patch("socket.socket", return_value=mock_sock):
        yield mock_sock


def test_kerberos_failure_dry_run_e2e(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["kerberos_failure"],
        target_net="10.10.10.0/24",
        dry_run=True,
        scenario_params=KERBEROS_TEST_PARAMS,
    )

    assert run.status.value == "completed"
    assert exit_code == 0
    assert (run_dir / "events.db").exists()
    assert (run_dir / "validation.json").exists()
    assert (run_dir / "report.md").exists()

    validation = json.loads((run_dir / "validation.json").read_text())
    result = validation["results"][0]
    assert result["scenario_id"] == "kerberos_failure"
    assert result["decision"] == "success"
    assert result["metrics"]["kerberos_auth_attempt_count"] == 5
    assert result["metrics"]["kerberos_auth_failed_count"] == 5

    report = (run_dir / "report.md").read_text()
    assert "## Kerberos Failure Details" in report
    assert "kerberos_auth_attempt_count" in report
    assert "administrator" in report or "admin" in report


def test_kerberos_failure_live_e2e(tmp_runs_dir, mock_kerberos_udp):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["kerberos_failure"],
        target_net="10.10.10.0/24",
        dry_run=False,
        scenario_params=KERBEROS_TEST_PARAMS,
    )

    assert run.status.value == "completed"
    assert exit_code == 0
    assert mock_kerberos_udp.sendto.called

    validation = json.loads((run_dir / "validation.json").read_text())
    result = validation["results"][0]
    assert result["decision"] == "success"
    assert result["metrics"]["kerberos_auth_attempt_count"] == 5
    assert result["metrics"]["kerberos_auth_failed_count"] == 5


def test_kerberos_failure_plugins_list():
    from dsp.plugins import PluginLoader, PluginStatus

    registry = PluginLoader().discover_and_load()
    record = registry.get("kerberos_failure")
    assert record is not None
    assert record.status == PluginStatus.ACTIVE
