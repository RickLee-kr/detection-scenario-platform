"""RunManager webshell execution path integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dsp.event_store import EventQuery, EventStore
from dsp.runner import RunManager
from tests.e2e.conftest import (
    assert_evidence_exports_exist,
    assert_manual_verification_package_exists,
)
from tests.e2e.fixtures.bundle_helpers import remote_bundle_path_for_run
from tests.e2e.fixtures.webshell_test_server import WebshellTestServer


@pytest.fixture
def webshell_server(tmp_path: Path):
    server = WebshellTestServer(storage_dir=tmp_path / "remote-storage")
    server.start()
    try:
        yield server
    finally:
        server.stop()


def test_run_manager_webshell_path_produces_full_artifacts(
    tmp_runs_dir: Path,
    webshell_server: WebshellTestServer,
) -> None:
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["dummy"],
        target_net="10.10.10.0/24",
        dry_run=True,
        execution_provider="webshell",
        webshell_family="jsp",
        webshell_url=webshell_server.webshell_url,
        remote_work_dir="/tmp/dsp",
    )

    assert run.status.value == "completed"
    assert exit_code == 0
    assert webshell_server.command_calls, "remote scenario command was not delivered"

    remote_bundle_path = remote_bundle_path_for_run(run.run_id)
    assert remote_bundle_path in webshell_server.download_calls

    assert (run_dir / "events.db").exists()
    assert (run_dir / "validation.json").exists()
    assert (run_dir / "report.md").exists()
    assert (run_dir / "report.json").exists()
    assert (run_dir / "events.jsonl").exists()
    assert (run_dir / "run.json").exists()

    store = EventStore.open_existing(run_dir / "events.db")
    try:
        event_count = store.count(EventQuery(run_id=run.run_id))
        assert event_count >= 3
        synthetic_count = store.count(
            EventQuery(
                run_id=run.run_id,
                scenario_id="dummy",
                event="synthetic_action",
            )
        )
        assert synthetic_count >= 3
    finally:
        store.close()

    validation = json.loads((run_dir / "validation.json").read_text())
    assert validation["results"][0]["decision"] == "success"

    assert_evidence_exports_exist(run_dir, run.run_id)
    assert_manual_verification_package_exists(run_dir)


def test_run_manager_webshell_requires_webshell_config(tmp_runs_dir: Path) -> None:
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, _, exit_code = manager.run(
        scenario_ids=["dummy"],
        execution_provider="webshell",
    )

    assert run.status.value == "config_error"
    assert exit_code == 3
