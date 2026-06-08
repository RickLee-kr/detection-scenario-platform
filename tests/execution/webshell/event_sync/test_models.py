"""Event sync model serialization tests."""

from __future__ import annotations

from datetime import datetime, timezone

from dsp import EVENT_SCHEMA_VERSION
from dsp.execution.webshell.event_sync import (
    EventBundleMetadata,
    EventSyncResult,
)
from tests.execution.webshell.event_sync.conftest import (
    RUN_ID,
    SCENARIO_ID,
    SCENARIO_VERSION,
)


def test_event_bundle_metadata_roundtrip():
    metadata = EventBundleMetadata(
        run_id=RUN_ID,
        scenario_id=SCENARIO_ID,
        scenario_version=SCENARIO_VERSION,
        generated_at=datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc),
        event_count=3,
        schema_version=EVENT_SCHEMA_VERSION,
    )
    restored = EventBundleMetadata.from_dict(metadata.to_dict())
    assert restored.run_id == metadata.run_id
    assert restored.event_count == metadata.event_count
    assert restored.schema_version == metadata.schema_version


def test_event_sync_result_roundtrip():
    metadata = EventBundleMetadata(
        run_id=RUN_ID,
        scenario_id=SCENARIO_ID,
        scenario_version=SCENARIO_VERSION,
        generated_at=datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc),
        event_count=1,
        schema_version=EVENT_SCHEMA_VERSION,
    )
    result = EventSyncResult(
        imported_count=1,
        skipped_count=0,
        bundle_metadata=metadata,
    )
    payload = result.to_dict()
    assert payload["imported_count"] == 1
    assert payload["bundle_metadata"]["run_id"] == RUN_ID
