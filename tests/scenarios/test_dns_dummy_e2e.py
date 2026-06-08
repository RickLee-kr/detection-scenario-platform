"""DNS dummy scenario E2E tests."""

from __future__ import annotations

import json

from dsp.runner import RunManager


def test_dns_dummy_dry_run_e2e(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["dns_dummy"],
        target_net="10.10.10.0/24",
        dry_run=True,
    )

    assert run.status.value == "completed"
    assert exit_code == 0
    assert (run_dir / "events.db").exists()
    assert (run_dir / "validation.json").exists()
    assert (run_dir / "report.md").exists()

    validation = json.loads((run_dir / "validation.json").read_text())
    result = validation["results"][0]
    assert result["scenario_id"] == "dns_dummy"
    assert result["decision"] == "success"
    assert result["metrics"]["dns_query_sent_count"] >= 3
    assert result["metrics"]["dns_response_count"] >= 3
    assert result["metrics"]["dns_timeout_count"] >= 1

    report = (run_dir / "report.md").read_text()
    assert "## DNS Protocol Details" in report
    assert "dns_query_sent_count" in report


def test_dns_dummy_plugins_list():
    from dsp.plugins import PluginLoader, PluginStatus

    registry = PluginLoader().discover_and_load()
    record = registry.get("dns_dummy")
    assert record is not None
    assert record.status == PluginStatus.ACTIVE
