"""Plugin Loader tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import yaml

from dsp.plugins import PluginLoader, PluginStatus


def test_dummy_plugin_active():
    loader = PluginLoader()
    registry = loader.discover_and_load()
    record = registry.get("dummy")
    assert record is not None
    assert record.status == PluginStatus.ACTIVE
    assert record.scenario_class is not None


def test_disabled_plugin(tmp_path):
    scenario_dir = tmp_path / "disabled_test"
    scenario_dir.mkdir()
    manifest = {
        "manifest_schema_version": "1.0.0",
        "id": "disabled_test",
        "name": "Disabled",
        "version": "1.0.0",
        "description": "Disabled plugin test",
        "category": "endpoint",
        "enabled": False,
        "supported_targets": {"requires": ["alive_host"]},
        "supported_protocols": ["http"],
        "validation_profile": {
            "profile_version": "1.0.0",
            "metrics": [
                {
                    "name": "synthetic_action_count",
                    "event_filter": {"event": "synthetic_action", "status": "sent"},
                    "aggregate": "count",
                }
            ],
            "success": {"synthetic_action_count": {"min": 1}},
        },
        "report_profile": {
            "profile_version": "1.0.0",
            "highlight_metrics": ["synthetic_action_count"],
        },
        "safety": {
            "max_events": 10,
            "max_duration_sec": 60,
            "forbidden_actions": [],
        },
        "executor": {"module": "scenario", "entrypoint": "execute"},
    }
    (scenario_dir / "manifest.yaml").write_text(yaml.dump(manifest))
    (scenario_dir / "scenario.py").write_text(
        textwrap.dedent(
            '''
            from dsp.engine.scenario_engine import RunContext, Scenario, ScenarioSummary, TargetSet
            class DisabledTestScenario(Scenario):
                @classmethod
                def scenario_id(cls): return "disabled_test"
                def prepare(self, ctx, targets): pass
                def execute(self, ctx, targets): pass
                def summarize(self, ctx):
                    return ScenarioSummary("disabled_test", {}, 0)
            '''
        )
    )
    loader = PluginLoader(scenarios_dir=tmp_path)
    registry = loader.discover_and_load()
    record = registry.get("disabled_test")
    assert record.status == PluginStatus.DISABLED


def test_bad_schema_version_rejected(tmp_path):
    scenario_dir = tmp_path / "bad_schema"
    scenario_dir.mkdir()
    (scenario_dir / "manifest.yaml").write_text("manifest_schema_version: '2.0.0'\nid: bad_schema\n")
    (scenario_dir / "scenario.py").write_text("pass")
    loader = PluginLoader(scenarios_dir=tmp_path)
    registry = loader.discover_and_load()
    record = registry.get("bad_schema")
    assert record.status == PluginStatus.REJECTED


def test_duplicate_id_conflict(tmp_path):
    """Registry conflict when second plugin shares an already-registered id."""
    from dsp.plugins.models import Manifest, PluginRecord, PluginStatus
    from dsp.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    manifest_a = Manifest(raw={"id": "shared_id", "version": "1.0.0"}, path=tmp_path / "a")
    registry.register(
        PluginRecord(id="shared_id", manifest=manifest_a, status=PluginStatus.ACTIVE)
    )
    manifest_b = Manifest(raw={"id": "shared_id", "version": "1.0.0"}, path=tmp_path / "b")
    conflict = PluginRecord(id="shared_id", manifest=manifest_b, status=PluginStatus.ACTIVE)
    registry.register(conflict)
    assert conflict.status == PluginStatus.CONFLICT
    assert registry.get("shared_id").status == PluginStatus.ACTIVE
