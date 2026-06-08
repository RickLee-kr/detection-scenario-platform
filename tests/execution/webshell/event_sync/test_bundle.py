"""Bundle loader tests."""

from __future__ import annotations

import pytest

from dsp.execution.webshell.event_sync import (
    BundleNotFoundError,
    BundleValidationError,
    load_jsonl_bundle,
)
from tests.execution.webshell.event_sync.conftest import (
    RUN_ID,
    SCENARIO_ID,
    event_record,
    write_bundle,
)


def test_load_valid_bundle(tmp_path):
    bundle_path = tmp_path / "events.jsonl"
    events = [event_record(), event_record(event="dns_tunnel_query_sent", status="sent")]
    write_bundle(bundle_path, events)

    bundle = load_jsonl_bundle(bundle_path)
    assert bundle.metadata.run_id == RUN_ID
    assert bundle.metadata.scenario_id == SCENARIO_ID
    assert bundle.metadata.event_count == 2
    assert len(bundle.events) == 2


def test_load_empty_bundle(tmp_path):
    bundle_path = tmp_path / "empty.jsonl"
    write_bundle(bundle_path, [])

    bundle = load_jsonl_bundle(bundle_path)
    assert bundle.metadata.event_count == 0
    assert bundle.events == []


def test_load_malformed_json(tmp_path):
    bundle_path = tmp_path / "bad.jsonl"
    bundle_path.write_text('{"_bundle_metadata": true, "run_id": "x"\n', encoding="utf-8")
    with pytest.raises(BundleValidationError, match="malformed JSON"):
        load_jsonl_bundle(bundle_path)


def test_load_missing_metadata(tmp_path):
    bundle_path = tmp_path / "no_meta.jsonl"
    bundle_path.write_text(json_line(event_record()) + "\n", encoding="utf-8")
    with pytest.raises(BundleValidationError, match="metadata missing"):
        load_jsonl_bundle(bundle_path)


def test_load_bundle_not_found(tmp_path):
    with pytest.raises(BundleNotFoundError, match="bundle not found"):
        load_jsonl_bundle(tmp_path / "missing.jsonl")


def json_line(record: dict) -> str:
    import json

    return json.dumps(record)
