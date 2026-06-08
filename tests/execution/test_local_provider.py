"""LocalExecutionProvider behavior tests."""

from __future__ import annotations

import json
from pathlib import Path

from dsp.engine import RunConfig, RunContext, resolve_targets
from dsp.event_store import EventStore
from dsp.execution import ExecutionContext, LocalExecutionProvider
from dsp.plugins import PluginLoader


def test_local_provider_capabilities():
    provider = LocalExecutionProvider()
    caps = provider.capabilities()
    assert caps.provider_type == "local"
    assert caps.execution_mode == "local"
    assert caps.traffic_origin == "dsp_host"


def test_local_provider_prepare_sets_metadata():
    provider = LocalExecutionProvider()
    ctx = ExecutionContext(
        run_id="prep01",
        target_net="10.10.10.0/24",
        dry_run=True,
        provider_type="local",
    )
    provider.prepare(ctx)
    assert ctx.execution_metadata["traffic_origin_host"] == "local"


def test_local_provider_execute_dummy_scenario(tmp_path: Path):
    loader = PluginLoader()
    registry = loader.discover_and_load()
    record = registry.get("dummy")
    assert record is not None

    store = EventStore(":memory:")
    run_id = "local_exec01"
    store.open_run(run_id)

    run_ctx = RunContext(
        run_id=run_id,
        target_net="10.10.10.0/24",
        event_store=store,
        config=RunConfig(dry_run=True),
        dry_run=True,
    )
    targets = resolve_targets("10.10.10.0/24")

    provider = LocalExecutionProvider()
    exec_ctx = ExecutionContext(
        run_id=run_id,
        target_net="10.10.10.0/24",
        dry_run=True,
        provider_type="local",
        scenario_id="dummy",
    )
    provider.prepare(exec_ctx)
    summary = provider.execute(
        exec_ctx,
        record,
        run_ctx,
        targets,
        snapshot_dir=tmp_path,
    )
    provider.cleanup(exec_ctx)

    assert summary is not None
    assert summary.scenario_id == "dummy"
    assert summary.metrics["synthetic_action_count"] >= 3
    assert (tmp_path / "manifest.snapshot.dummy.json").exists()


def test_local_provider_cleanup_is_noop():
    provider = LocalExecutionProvider()
    ctx = ExecutionContext(
        run_id="cleanup01",
        target_net="10.10.10.0/24",
        dry_run=True,
        provider_type="local",
    )
    provider.cleanup(ctx)
