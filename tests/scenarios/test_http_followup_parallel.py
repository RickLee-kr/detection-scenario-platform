"""HTTP follow-up parallel burst tests."""

from __future__ import annotations

import time
from unittest.mock import patch

from dsp.engine.scenario_engine import RunConfig, RunContext, TargetSet
from dsp.event_store import EventStore
from dsp.protocols.http import HttpClient
from scenarios.http_followup.executor import run


def test_http_followup_parallel_burst_completes_quickly(tmp_path):
    store = EventStore(db_path=tmp_path / "events.db")
    store.open_run("parallel-test")
    ctx = RunContext(
        run_id="parallel-test",
        target_net="10.10.10.0/24",
        event_store=store,
        config=RunConfig(),
        dry_run=True,
    )
    targets = TargetSet(
        target_net="10.10.10.0/24",
        service_hosts={"http_targets": ["10.10.10.20"]},
        service_endpoints={"http_targets": [("10.10.10.20", 80)]},
        discovery_enabled=True,
    )

    original_mock = HttpClient._mock_request

    def slow_mock(self, planned, *, mock_status_code=200, mock_outcome=None):
        time.sleep(0.02)
        return original_mock(self, planned, mock_status_code=404, mock_outcome="response")

    t0 = time.monotonic()
    with patch.object(HttpClient, "_mock_request", slow_mock):
        run(
            ctx,
            targets,
            config={"max_total": 60, "max_per_host": 60, "concurrency": 32},
        )
    elapsed = time.monotonic() - t0

    events = store.list_events("parallel-test")
    completed = next(e for e in events if e.event == "http_followup_completed")
    assert completed.evidence["requests_sent"] == 60
    assert completed.evidence.get("concurrency") == 32
    assert completed.evidence.get("requests_per_second", 0) >= 3
    assert elapsed < 3.0
