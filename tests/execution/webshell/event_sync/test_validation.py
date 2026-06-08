"""Structural bundle validation tests."""

from __future__ import annotations

import pytest

from dsp import EVENT_SCHEMA_VERSION
from dsp.execution.webshell.event_sync import (
    BundleSchemaError,
    BundleValidationError,
    EventBundle,
    EventBundleMetadata,
    validate_bundle,
)
from tests.execution.webshell.event_sync.conftest import (
    GENERATED_AT,
    RUN_ID,
    SCENARIO_ID,
    SCENARIO_VERSION,
    event_record,
)


def _metadata(*, event_count: int, schema_version: str = EVENT_SCHEMA_VERSION) -> EventBundleMetadata:
    from datetime import datetime

    return EventBundleMetadata(
        run_id=RUN_ID,
        scenario_id=SCENARIO_ID,
        scenario_version=SCENARIO_VERSION,
        generated_at=datetime.fromisoformat(GENERATED_AT.replace("Z", "+00:00")),
        event_count=event_count,
        schema_version=schema_version,
    )


def test_validate_bundle_accepts_valid_bundle():
    events = [event_record(), event_record(event="dns_tunnel_completed", status="info")]
    bundle = EventBundle(metadata=_metadata(event_count=2), events=events)
    validate_bundle(bundle)


def test_validate_bundle_event_count_mismatch():
    bundle = EventBundle(metadata=_metadata(event_count=2), events=[event_record()])
    with pytest.raises(BundleValidationError, match="event_count mismatch"):
        validate_bundle(bundle)


def test_validate_bundle_schema_mismatch():
    bundle = EventBundle(
        metadata=_metadata(event_count=1, schema_version="9.9.9"),
        events=[event_record()],
    )
    with pytest.raises(BundleSchemaError, match="unsupported bundle schema_version"):
        validate_bundle(bundle)


def test_validate_bundle_missing_event_fields():
    bad_event = event_record()
    del bad_event["status"]
    bundle = EventBundle(metadata=_metadata(event_count=1), events=[bad_event])
    with pytest.raises(BundleValidationError, match="missing required fields"):
        validate_bundle(bundle)


def test_validate_bundle_run_id_mismatch():
    bad_event = event_record(run_id="other_run")
    bundle = EventBundle(metadata=_metadata(event_count=1), events=[bad_event])
    with pytest.raises(BundleValidationError, match="run_id does not match"):
        validate_bundle(bundle)
