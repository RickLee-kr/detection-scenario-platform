"""HTTP Follow-up scenario E2E tests."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from dsp.runner import RunManager

HTTP_TEST_PARAMS = {
    "http_followup": {
        "hosts": ["10.10.10.20"],
        "max_total": 5,
        "max_per_host": 5,
    }
}


@pytest.fixture
def mock_http_urlopen():
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    mock_resp.status = 200
    mock_resp.getcode.return_value = 200
    mock_resp.reason = "OK"
    mock_resp.read.return_value = b"ok"

    with patch("urllib.request.build_opener") as build_opener:
        opener = MagicMock()
        opener.open.return_value = mock_resp
        build_opener.return_value = opener
        yield


def test_http_followup_dry_run_e2e(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["http_followup"],
        target_net="10.10.10.0/24",
        dry_run=True,
        scenario_params=HTTP_TEST_PARAMS,
    )

    assert run.status.value == "completed"
    assert exit_code == 0
    assert (run_dir / "events.db").exists()
    assert (run_dir / "validation.json").exists()
    assert (run_dir / "report.md").exists()

    validation = json.loads((run_dir / "validation.json").read_text())
    result = validation["results"][0]
    assert result["scenario_id"] == "http_followup"
    assert result["decision"] == "success"
    assert result["metrics"]["http_request_sent_count"] == 5
    assert result["metrics"]["http_response_received_count"] == 5

    report = (run_dir / "report.md").read_text()
    assert "## HTTP Follow-up Details" in report
    assert "http_request_sent_count" in report
    assert "/login" in report or "https://" in report


def test_http_followup_live_e2e(tmp_runs_dir, mock_http_urlopen):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["http_followup"],
        target_net="10.10.10.0/24",
        dry_run=False,
        scenario_params=HTTP_TEST_PARAMS,
    )

    assert run.status.value == "completed"
    assert exit_code == 0

    validation = json.loads((run_dir / "validation.json").read_text())
    result = validation["results"][0]
    assert result["decision"] == "success"
    assert result["metrics"]["http_request_sent_count"] == 5


def test_http_followup_plugins_list():
    from dsp.plugins import PluginLoader, PluginStatus

    registry = PluginLoader().discover_and_load()
    record = registry.get("http_followup")
    assert record is not None
    assert record.status == PluginStatus.ACTIVE
