"""Event Store unit tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dsp.event_store import Event, EventQuery, EventStore, RunClosedError


def _event(**kwargs) -> Event:
    defaults = {
        "run_id": "test_run",
        "scenario_id": "dummy",
        "timestamp": datetime.now(timezone.utc),
        "stage": "executor",
        "event": "synthetic_action",
        "status": "sent",
        "source": "dry_run",
    }
    defaults.update(kwargs)
    return Event(**defaults)


def test_append_assigns_monotonic_id():
    store = EventStore(":memory:")
    store.open_run("test_run")
    id1 = store.append(_event())
    id2 = store.append(_event())
    assert id1 == 1
    assert id2 == 2


def test_append_rejects_forbidden_status():
    store = EventStore(":memory:")
    store.open_run("test_run")
    with pytest.raises(ValueError, match="Forbidden"):
        store.append(_event(status="success"))


def test_append_rejects_missing_run_id():
    store = EventStore(":memory:")
    store.open_run("test_run")
    with pytest.raises(ValueError):
        store.append(_event(run_id=""))


def test_aggregate_count_matches_manual():
    store = EventStore(":memory:")
    store.open_run("test_run")
    for i in range(5):
        store.append(_event(artifact=f"a{i}"))
    from dsp.event_store import MetricDef

    metrics = store.aggregate(
        "test_run",
        "dummy",
        [
            MetricDef(
                name="synthetic_action_count",
                event_filter={"event": "synthetic_action", "status": "sent"},
                aggregate="count",
            )
        ],
    )
    assert metrics["synthetic_action_count"] == 5


def test_completed_run_append_raises():
    store = EventStore(":memory:")
    store.open_run("test_run")
    store.append(_event())
    store.close_run()
    with pytest.raises(RunClosedError):
        store.append(_event())


def test_distinct_artifact_aggregate():
    store = EventStore(":memory:")
    store.open_run("test_run")
    store.append(_event(artifact="a"))
    store.append(_event(artifact="a"))
    store.append(_event(artifact="b"))
    from dsp.event_store import MetricDef

    metrics = store.aggregate(
        "test_run",
        "dummy",
        [
            MetricDef(
                name="unique_artifacts",
                event_filter={"event": "synthetic_action"},
                aggregate="distinct_artifact",
            )
        ],
    )
    assert metrics["unique_artifacts"] == 2


def test_sample_returns_events():
    store = EventStore(":memory:")
    store.open_run("test_run")
    store.append(_event())
    samples = store.sample("test_run", "dummy", limit=1)
    assert len(samples) == 1
    assert samples[0].event == "synthetic_action"


def test_export_jsonl(tmp_path):
    store = EventStore(":memory:")
    store.open_run("test_run")
    store.append(_event())
    out = tmp_path / "events.jsonl"
    store.export_jsonl(out)
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 1
