"""Structural bundle validation — no scenario success determination."""

from __future__ import annotations

from typing import Any

from dsp import EVENT_SCHEMA_VERSION
from dsp.execution.webshell.event_sync.exceptions import (
    BundleSchemaError,
    BundleValidationError,
)
from dsp.execution.webshell.event_sync.models import EventBundle

REQUIRED_EVENT_FIELDS = frozenset(
    {
        "run_id",
        "scenario_id",
        "timestamp",
        "stage",
        "event",
        "status",
    }
)


def validate_bundle(bundle: EventBundle) -> None:
    """Validate bundle structure before Event Store import.

    Raises:
        BundleValidationError: metadata, field, or count inconsistencies
        BundleSchemaError: unsupported schema version
    """
    metadata = bundle.metadata
    if not metadata.run_id:
        raise BundleValidationError("metadata run_id is required", rule="run_id")
    if not metadata.scenario_id:
        raise BundleValidationError("metadata scenario_id is required", rule="scenario_id")
    if not metadata.schema_version:
        raise BundleValidationError(
            "metadata schema_version is required",
            rule="schema_version",
        )
    if metadata.schema_version != EVENT_SCHEMA_VERSION:
        raise BundleSchemaError(
            f"unsupported bundle schema_version: {metadata.schema_version!r}",
            schema_version=metadata.schema_version,
            expected=EVENT_SCHEMA_VERSION,
        )
    if metadata.event_count != len(bundle.events):
        raise BundleValidationError(
            f"event_count mismatch: metadata={metadata.event_count}, "
            f"actual={len(bundle.events)}",
            rule="event_count_mismatch",
        )
    for index, event in enumerate(bundle.events, start=1):
        _validate_event_record(event, index=index, metadata=metadata)


def _validate_event_record(
    event: dict[str, Any],
    *,
    index: int,
    metadata: Any,
) -> None:
    if not isinstance(event, dict):
        raise BundleValidationError(
            f"event {index} must be a JSON object",
            rule="invalid_event_type",
        )
    missing = REQUIRED_EVENT_FIELDS - set(event.keys())
    if missing:
        raise BundleValidationError(
            f"event {index} missing required fields: {sorted(missing)}",
            rule="missing_event_fields",
        )
    if event["run_id"] != metadata.run_id:
        raise BundleValidationError(
            f"event {index} run_id does not match bundle metadata",
            rule="run_id_mismatch",
        )
    if event["scenario_id"] != metadata.scenario_id:
        raise BundleValidationError(
            f"event {index} scenario_id does not match bundle metadata",
            rule="scenario_id_mismatch",
        )
    if not isinstance(event["timestamp"], str):
        raise BundleValidationError(
            f"event {index} timestamp must be an ISO-8601 string",
            rule="invalid_timestamp",
        )
