"""EventSyncBridge integration tests — no network."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from dsp.event_store import Event, EventQuery, EventStore
from dsp.execution.webshell.event_sync import (
    BundleSchemaError,
    BundleValidationError,
    EventSyncBridge,
    load_jsonl_bundle,
    validate_bundle,
)
from tests.execution.webshell.event_sync.conftest import (
    RUN_ID,
    SCENARIO_ID,
    event_record,
    metadata_record,
    write_bundle,
)


def _open_store() -> EventStore:
    store = EventStore(":memory:")
    store.open_run(RUN_ID)
    return store


def test_valid_bundle_import(tmp_path):
    bundle_path = tmp_path / "events.jsonl"
    events = [
        event_record(),
        event_record(event="dns_tunnel_query_sent", status="sent"),
    ]
    write_bundle(bundle_path, events)

    store = _open_store()
    result = EventSyncBridge().sync_bundle(bundle_path, store)

    assert result.imported_count == 2
    assert result.skipped_count == 0
    assert result.bundle_metadata.run_id == RUN_ID
    assert store.count(EventQuery(run_id=RUN_ID, scenario_id=SCENARIO_ID)) == 2


def test_empty_bundle_import(tmp_path):
    bundle_path = tmp_path / "empty.jsonl"
    write_bundle(bundle_path, [])

    store = _open_store()
    result = EventSyncBridge().sync_bundle(bundle_path, store)

    assert result.imported_count == 0
    assert result.skipped_count == 0
    assert store.count(EventQuery(run_id=RUN_ID, scenario_id=SCENARIO_ID)) == 0


def test_malformed_json_rejected(tmp_path):
    bundle_path = tmp_path / "bad.jsonl"
    bundle_path.write_text("{not-json}\n", encoding="utf-8")

    store = _open_store()
    with pytest.raises(BundleValidationError, match="malformed JSON"):
        EventSyncBridge().sync_bundle(bundle_path, store)


def test_missing_metadata_rejected(tmp_path):
    bundle_path = tmp_path / "no_meta.jsonl"
    bundle_path.write_text(json.dumps(event_record()) + "\n", encoding="utf-8")

    store = _open_store()
    with pytest.raises(BundleValidationError, match="metadata missing"):
        EventSyncBridge().sync_bundle(bundle_path, store)


def test_event_count_mismatch_rejected(tmp_path):
    bundle_path = tmp_path / "mismatch.jsonl"
    lines = [
        json.dumps(metadata_record(event_count=2)),
        json.dumps(event_record()),
    ]
    bundle_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    store = _open_store()
    with pytest.raises(BundleValidationError, match="event_count mismatch"):
        EventSyncBridge().sync_bundle(bundle_path, store)


def test_schema_mismatch_rejected(tmp_path):
    bundle_path = tmp_path / "schema.jsonl"
    meta = metadata_record(event_count=1)
    meta["schema_version"] = "0.0.1"
    lines = [json.dumps(meta), json.dumps(event_record())]
    bundle_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    store = _open_store()
    with pytest.raises(BundleSchemaError):
        EventSyncBridge().sync_bundle(bundle_path, store)


def test_duplicate_events_skipped(tmp_path):
    duplicate = event_record()
    bundle_path = tmp_path / "dup.jsonl"
    write_bundle(bundle_path, [duplicate, duplicate.copy()])

    store = _open_store()
    result = EventSyncBridge().sync_bundle(bundle_path, store)

    assert result.imported_count == 1
    assert result.skipped_count == 1


def test_large_bundle_import(tmp_path):
    events = [
        event_record(
            event=f"dns_tunnel_query_sent_{index}",
            status="sent",
            timestamp=f"2026-06-06T12:00:{index % 60:02d}Z",
        )
        for index in range(250)
    ]
    bundle_path = tmp_path / "large.jsonl"
    write_bundle(bundle_path, events)

    store = _open_store()
    result = EventSyncBridge().sync_bundle(bundle_path, store)

    assert result.imported_count == 250
    assert result.skipped_count == 0
    assert store.count(EventQuery(run_id=RUN_ID, scenario_id=SCENARIO_ID)) == 250


def test_partial_corruption_skips_invalid_events(tmp_path):
    valid = event_record()
    invalid = event_record(status="success")
    bundle_path = tmp_path / "partial.jsonl"
    write_bundle(bundle_path, [valid, invalid])

    store = _open_store()
    result = EventSyncBridge().sync_bundle(bundle_path, store)

    assert result.imported_count == 1
    assert result.skipped_count == 1


def test_invalid_event_schema_skipped(tmp_path):
    bad = event_record()
    del bad["stage"]
    bundle_path = tmp_path / "invalid.jsonl"
    meta = metadata_record(event_count=1)
    bundle_path.write_text(
        json.dumps(meta) + "\n" + json.dumps(bad) + "\n",
        encoding="utf-8",
    )

    store = _open_store()
    with pytest.raises(BundleValidationError, match="missing required fields"):
        EventSyncBridge().sync_bundle(bundle_path, store)


def test_store_duplicate_skipped_on_resync(tmp_path):
    bundle_path = tmp_path / "events.jsonl"
    events = [event_record()]
    write_bundle(bundle_path, events)

    store = _open_store()
    bridge = EventSyncBridge()
    first = bridge.sync_bundle(bundle_path, store)
    second = bridge.sync_bundle(bundle_path, store)

    assert first.imported_count == 1
    assert second.imported_count == 0
    assert second.skipped_count == 1
    assert store.count(EventQuery(run_id=RUN_ID, scenario_id=SCENARIO_ID)) == 1


def test_bridge_only_appends_does_not_modify_existing(tmp_path):
    bundle_path = tmp_path / "events.jsonl"
    write_bundle(bundle_path, [event_record()])

    store = _open_store()
    store.append(
        Event(
            run_id=RUN_ID,
            scenario_id=SCENARIO_ID,
            timestamp=datetime(2026, 6, 6, 11, 59, 0, tzinfo=timezone.utc),
            stage="runner",
            event="scenario_started",
            status="info",
            source="runner",
        )
    )
    before = store.list_events(RUN_ID)

    EventSyncBridge().sync_bundle(bundle_path, store)

    after = store.list_events(RUN_ID)
    assert after[0].event == before[0].event
    assert after[0].stage == before[0].stage
    assert len(after) == 2
