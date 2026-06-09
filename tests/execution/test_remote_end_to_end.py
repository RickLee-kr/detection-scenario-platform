"""End-to-end remote execution via WebshellTestServer and real dsp-remote-scenario."""

from __future__ import annotations

from pathlib import Path

import pytest

from dsp.engine import RunConfig, RunContext, resolve_targets
from dsp.event_store import EventQuery, EventStore
from dsp.execution import ExecutionContext, WebshellExecutionProvider
from dsp.execution.providers.runtime.command import CommandExecutionPolicy
from dsp.execution.providers.runtime.transport import TransportRuntimeConfiguration
from dsp.execution.providers.webshell.jsp import JspWebshellProvider
from dsp.execution.remote import RemoteEventCollectionRequest, RemoteEventCollector
from dsp.execution.webshell.transport import RealHttpTransport, RetryPolicy
from dsp.execution.webshell_config import WebshellExecutionConfig
from dsp.plugins import PluginLoader
from tests.e2e.fixtures.bundle_helpers import remote_bundle_path_for_run
from tests.e2e.fixtures.webshell_test_server import WebshellTestServer

RUN_ID = "remote_e2e_run"
SCENARIO_ID = "dummy"


@pytest.fixture
def remote_e2e_server(tmp_path: Path):
    server = WebshellTestServer(storage_dir=tmp_path / "remote-storage")
    server.start()
    try:
        yield server
    finally:
        server.stop()


def _connected_webshell_provider(server: WebshellTestServer) -> WebshellExecutionProvider:
    transport = RealHttpTransport(retry_policy=RetryPolicy(max_retries=0))
    family_provider = JspWebshellProvider(
        transport=transport,
        webshell_url=server.webshell_url,
    )
    family_provider.create_runtime(
        config=TransportRuntimeConfiguration(
            enable_healthcheck_on_connect=True,
            command_policy=CommandExecutionPolicy(allow_command_execution=True),
        ),
    )
    family_provider.connect()
    config = WebshellExecutionConfig(
        provider_type="jsp",
        webshell_url=server.webshell_url,
        enable_healthcheck_on_connect=True,
    )
    return WebshellExecutionProvider(
        config,
        transport=transport,
        family_provider=family_provider,
    )


def test_remote_end_to_end_runner_collector_event_store(
    remote_e2e_server: WebshellTestServer,
    tmp_path: Path,
) -> None:
    loader = PluginLoader()
    record = loader.discover_and_load().get(SCENARIO_ID)
    assert record is not None

    store = EventStore(tmp_path / "events.db")
    store.open_run(RUN_ID)

    provider = _connected_webshell_provider(remote_e2e_server)
    exec_ctx = ExecutionContext(
        run_id=RUN_ID,
        target_net="10.10.10.0/24",
        dry_run=True,
        provider_type="webshell",
        scenario_id=SCENARIO_ID,
        execution_metadata={
            "remote_work_dir": "/tmp/dsp",
            "remote_bundle_path": remote_bundle_path_for_run(RUN_ID),
        },
    )
    run_ctx = RunContext(
        run_id=RUN_ID,
        target_net="10.10.10.0/24",
        event_store=store,
        config=RunConfig(dry_run=True),
        dry_run=True,
    )
    targets = resolve_targets("10.10.10.0/24")

    provider.prepare(exec_ctx)
    provider.execute(exec_ctx, record, run_ctx, targets)
    assert store.count(EventQuery(run_id=RUN_ID)) == 0
    assert remote_e2e_server.command_calls

    collection_result = RemoteEventCollector().collect(
        RemoteEventCollectionRequest(
            remote_execution_id=RUN_ID,
            remote_bundle_path=remote_bundle_path_for_run(RUN_ID),
        ),
        provider,
        store,
    )
    provider.cleanup(exec_ctx)

    assert collection_result.events_imported >= 3
    assert remote_e2e_server.download_calls == [remote_bundle_path_for_run(RUN_ID)]
    assert store.count(EventQuery(run_id=RUN_ID)) >= 3
    assert store.count(
        EventQuery(
            run_id=RUN_ID,
            scenario_id=SCENARIO_ID,
            event="synthetic_action",
        )
    ) >= 3
    assert store.count(
        EventQuery(
            run_id=RUN_ID,
            scenario_id=SCENARIO_ID,
            event="scenario_completed",
        )
    ) >= 1

    store.close()
