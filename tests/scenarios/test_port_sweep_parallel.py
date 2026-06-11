"""Port sweep parallel execution tests."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from dsp.runner import RunManager


@pytest.fixture
def mock_tcp_socket():
    with patch("socket.create_connection") as connect_mock:
        connect_mock.side_effect = ConnectionRefusedError("refused")
        yield connect_mock


def test_port_sweep_parallel_completes_with_timing_metrics(tmp_runs_dir, mock_tcp_socket):
    manager = RunManager(runs_dir=tmp_runs_dir)
    _, run_dir, exit_code = manager.run(
        scenario_ids=["port_sweep"],
        target_net="10.10.10.0/24",
        dry_run=False,
        operational_profile="normal",
        scenario_params={
            "port_sweep": {
                "hosts": [f"10.10.10.{i}" for i in range(1, 11)],
                "max_ports": 5,
                "concurrency": 8,
                "timeout": 0.1,
            }
        },
    )
    assert exit_code == 0
    summary = json.loads((run_dir / "traffic_summary.json").read_text())
    ps = summary["scenarios"]["port_sweep"]
    assert ps["probes_sent"] == 50
    assert ps["concurrency"] == 8
    assert ps["duration_sec"] is not None
    assert ps["probes_per_second"] is not None
    assert ps["probes_per_second"] > 1
