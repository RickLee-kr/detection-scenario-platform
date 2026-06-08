"""Port sweep scenario E2E tests."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from dsp.runner import RunManager

PORT_SWEEP_TEST_PARAMS = {
    "port_sweep": {
        "hosts": ["10.10.10.30"],
        "max_ports": 5,
    }
}


@pytest.fixture
def mock_tcp_socket():
    with patch("socket.create_connection") as connect_mock:
        connect_mock.return_value.__enter__.return_value = object()
        yield connect_mock


def test_port_sweep_dry_run_e2e(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["port_sweep"],
        target_net="10.10.10.0/24",
        dry_run=True,
        scenario_params=PORT_SWEEP_TEST_PARAMS,
    )

    assert run.status.value == "completed"
    assert exit_code == 0
    assert (run_dir / "events.db").exists()
    assert (run_dir / "validation.json").exists()
    assert (run_dir / "report.md").exists()

    validation = json.loads((run_dir / "validation.json").read_text())
    result = validation["results"][0]
    assert result["scenario_id"] == "port_sweep"
    assert result["decision"] == "success"
    assert result["metrics"]["port_probe_count"] == 5
    assert result["metrics"]["port_connection_attempt_count"] == 5

    report = (run_dir / "report.md").read_text()
    assert "## Port Sweep Details" in report
    assert "port_probe_count" in report
    assert "10.10.10.30" in report


def test_port_sweep_live_e2e(tmp_runs_dir, mock_tcp_socket):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["port_sweep"],
        target_net="10.10.10.0/24",
        dry_run=False,
        scenario_params=PORT_SWEEP_TEST_PARAMS,
    )

    assert run.status.value == "completed"
    assert exit_code == 0
    assert mock_tcp_socket.called

    validation = json.loads((run_dir / "validation.json").read_text())
    result = validation["results"][0]
    assert result["decision"] == "success"
    assert result["metrics"]["port_probe_count"] == 5
    assert result["metrics"]["port_connection_attempt_count"] == 5


def test_port_sweep_plugins_list():
    from dsp.plugins import PluginLoader, PluginStatus

    registry = PluginLoader().discover_and_load()
    record = registry.get("port_sweep")
    assert record is not None
    assert record.status == PluginStatus.ACTIVE
