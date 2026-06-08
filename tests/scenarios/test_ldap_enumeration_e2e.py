"""LDAP enumeration scenario E2E tests."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from dsp.runner import RunManager

LDAP_TEST_PARAMS = {
    "ldap_enumeration": {
        "hosts": ["10.10.10.30"],
        "ports": [389],
        "max_queries_per_host": 3,
    }
}


@pytest.fixture
def mock_ldap_socket():
    with patch("socket.create_connection") as connect_mock:
        connect_mock.return_value.__enter__.return_value = object()
        yield connect_mock


def test_ldap_enumeration_dry_run_e2e(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["ldap_enumeration"],
        target_net="10.10.10.0/24",
        dry_run=True,
        scenario_params=LDAP_TEST_PARAMS,
    )

    assert run.status.value == "completed"
    assert exit_code == 0
    assert (run_dir / "events.db").exists()
    assert (run_dir / "validation.json").exists()
    assert (run_dir / "report.md").exists()

    validation = json.loads((run_dir / "validation.json").read_text())
    result = validation["results"][0]
    assert result["scenario_id"] == "ldap_enumeration"
    assert result["decision"] == "success"
    assert result["metrics"]["ldap_connection_attempt_count"] == 1
    assert result["metrics"]["ldap_bind_or_search_attempt_count"] >= 1

    report = (run_dir / "report.md").read_text()
    assert "## LDAP Enumeration Details" in report
    assert "ldap_connection_attempt_count" in report
    assert "10.10.10.30" in report


def test_ldap_enumeration_live_e2e(tmp_runs_dir, mock_ldap_socket):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["ldap_enumeration"],
        target_net="10.10.10.0/24",
        dry_run=False,
        scenario_params=LDAP_TEST_PARAMS,
    )

    assert run.status.value == "completed"
    assert exit_code == 0
    assert mock_ldap_socket.called

    validation = json.loads((run_dir / "validation.json").read_text())
    result = validation["results"][0]
    assert result["decision"] == "success"
    assert result["metrics"]["ldap_connection_attempt_count"] == 1


def test_ldap_enumeration_plugins_list():
    from dsp.plugins import PluginLoader, PluginStatus

    registry = PluginLoader().discover_and_load()
    record = registry.get("ldap_enumeration")
    assert record is not None
    assert record.status == PluginStatus.ACTIVE
