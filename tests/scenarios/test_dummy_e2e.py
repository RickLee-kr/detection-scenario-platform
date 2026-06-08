"""Dummy scenario E2E integration tests."""

from __future__ import annotations

import json
import shutil
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dsp.event_store import Event, EventStore, RunClosedError
from dsp.runner import RunManager


def test_dummy_dry_run_e2e(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["dummy"],
        target_net="10.10.10.0/24",
        dry_run=True,
    )

    assert run.status.value == "completed"
    assert exit_code == 0
    assert (run_dir / "events.db").exists()
    assert (run_dir / "validation.json").exists()
    assert (run_dir / "report.md").exists()
    assert (run_dir / "run.json").exists()

    validation = json.loads((run_dir / "validation.json").read_text())
    results = validation["results"]
    assert len(results) == 1
    assert results[0]["decision"] == "success"
    assert results[0]["metrics"]["synthetic_action_count"] >= 3

    report = (run_dir / "report.md").read_text()
    assert "success" in report
    assert "synthetic_action_count" in report


def test_second_plugin_without_core_edit(tmp_path, tmp_runs_dir):
    """EC-6: add dummy2 without editing validation/engine.py."""
    scenarios = tmp_path / "scenarios"
    shutil.copytree(
        Path(__file__).resolve().parents[2] / "scenarios" / "dummy",
        scenarios / "dummy",
    )
    dummy2 = scenarios / "dummy2"
    shutil.copytree(scenarios / "dummy", dummy2)

    manifest_path = dummy2 / "manifest.yaml"
    text = manifest_path.read_text()
    text = text.replace("id: dummy\n", "id: dummy2\n")
    text = text.replace("Dummy Scenario", "Dummy2 Scenario")
    manifest_path.write_text(text)

    scenario_py = dummy2 / "scenario.py"
    scenario_py.write_text(
        textwrap.dedent(
            '''
            from datetime import datetime, timezone
            from dsp.engine.scenario_engine import RunContext, Scenario, ScenarioSummary, TargetSet
            from dsp.event_store import Event

            class Dummy2Scenario(Scenario):
                @classmethod
                def scenario_id(cls): return "dummy2"
                def prepare(self, ctx, targets): pass
                def execute(self, ctx, targets):
                    for seq in range(1, 4):
                        ctx.event_store.append(Event(
                            run_id=ctx.run_id, scenario_id="dummy2",
                            timestamp=datetime.now(timezone.utc),
                            stage="executor", event="synthetic_action",
                            status="sent", artifact=f"x{seq}", source="dry_run",
                        ))
                def summarize(self, ctx):
                    from dsp.event_store import EventQuery
                    c = ctx.event_store.count(EventQuery(
                        run_id=ctx.run_id, scenario_id="dummy2",
                        event="synthetic_action", status="sent"))
                    return ScenarioSummary("dummy2", {"synthetic_action_count": c}, c)
            '''
        )
    )

    manager = RunManager(runs_dir=tmp_runs_dir, scenarios_dir=scenarios)
    run, run_dir, exit_code = manager.run(scenario_ids=["dummy2"], dry_run=True)
    assert exit_code == 0
    validation = json.loads((run_dir / "validation.json").read_text())
    assert validation["results"][0]["decision"] == "success"


def test_completed_store_readonly(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    _, run_dir, _ = manager.run(scenario_ids=["dummy"], dry_run=True)

    store = EventStore.open_existing(run_dir / "events.db")
    with pytest.raises(RunClosedError):
        store.append(
            Event(
                run_id=store.run_id,
                scenario_id="dummy",
                timestamp=datetime.now(timezone.utc),
                stage="executor",
                event="synthetic_action",
                status="sent",
                source="dry_run",
            )
        )
    store.close()
