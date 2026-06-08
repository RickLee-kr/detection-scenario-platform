"""Release 1.0 Flow A — local execution path E2E harness."""

from __future__ import annotations

from pathlib import Path

import pytest

from dsp.engine import RunConfig, RunContext, resolve_targets
from dsp.event_store import EventQuery, EventStore
from dsp.execution import ExecutionContext, LocalExecutionProvider
from dsp.plugins import PluginLoader
from tests.e2e.conftest import (
    assert_event_store_has_events,
    assert_evidence_exports_exist,
    assert_harness_excludes_validation_runtime,
    assert_manual_verification_package_exists,
    export_evidence,
    generate_manual_verification,
)

pytestmark = pytest.mark.e2e

RUN_ID = "release_1_0_local_run"
SCENARIO_ID = "dummy"


@pytest.fixture
def local_event_store(tmp_path: Path) -> EventStore:
    store = EventStore(tmp_path / "local_events.db")
    store.open_run(RUN_ID)
    return store


def test_local_execution_reaches_event_store(
    local_event_store: EventStore,
    e2e_output_dir: Path,
    tmp_path: Path,
) -> None:
    loader = PluginLoader()
    record = loader.discover_and_load().get(SCENARIO_ID)
    assert record is not None

    run_ctx = RunContext(
        run_id=RUN_ID,
        target_net="10.10.10.0/24",
        event_store=local_event_store,
        config=RunConfig(dry_run=True),
        dry_run=True,
    )
    targets = resolve_targets("10.10.10.0/24")
    provider = LocalExecutionProvider()
    exec_ctx = ExecutionContext(
        run_id=RUN_ID,
        target_net="10.10.10.0/24",
        dry_run=True,
        provider_type="local",
        scenario_id=SCENARIO_ID,
    )

    provider.prepare(exec_ctx)
    summary = provider.execute(
        exec_ctx,
        record,
        run_ctx,
        targets,
        snapshot_dir=tmp_path / "snapshots",
    )
    provider.cleanup(exec_ctx)

    assert summary is not None
    assert summary.scenario_id == SCENARIO_ID
    event_count = assert_event_store_has_events(local_event_store, RUN_ID, minimum=3)
    assert local_event_store.count(
        EventQuery(run_id=RUN_ID, scenario_id=SCENARIO_ID, event="synthetic_action")
    ) >= 3

    export_result = export_evidence(local_event_store, RUN_ID, e2e_output_dir)
    assert_evidence_exports_exist(e2e_output_dir, RUN_ID)
    assert export_result.export_metadata["event_count"] == event_count

    manual_result = generate_manual_verification(
        local_event_store,
        RUN_ID,
        e2e_output_dir,
    )
    assert_manual_verification_package_exists(e2e_output_dir)
    assert manual_result.run_id == RUN_ID
    assert len(manual_result.generated_files) == 3


def test_local_flow_excludes_validation_runtime() -> None:
    assert_harness_excludes_validation_runtime(Path(__file__))
