"""EventSyncBridge — append-only Event Store import path."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from dsp import EVENT_SCHEMA_VERSION
from dsp.event_store import Event, EventStore
from dsp.event_store.models import RunNotOpenError
from dsp.execution.webshell.event_sync.base import EventSyncBridgeBase
from dsp.execution.webshell.event_sync.bundle import load_jsonl_bundle
from dsp.execution.webshell.event_sync.exceptions import BundleValidationError
from dsp.execution.webshell.event_sync.models import EventBundleMetadata, EventSyncResult
from dsp.execution.webshell.event_sync.validation import validate_bundle


class EventSyncBridge(EventSyncBridgeBase):
    """Import remote JSONL bundles into Event Store — append only."""

    def sync_bundle(
        self,
        bundle_path: str | Path,
        event_store: EventStore,
    ) -> EventSyncResult:
        if event_store.run_id is None:
            raise RunNotOpenError("Event Store has no open run")
        bundle = load_jsonl_bundle(bundle_path)
        validate_bundle(bundle)
        if bundle.metadata.run_id != event_store.run_id:
            raise BundleValidationError(
                f"bundle run_id {bundle.metadata.run_id!r} does not match "
                f"open run {event_store.run_id!r}",
                rule="store_run_id_mismatch",
            )

        imported_count = 0
        skipped_count = 0
        seen_fingerprints: set[tuple[Any, ...]] = set()

        for index, raw_event in enumerate(bundle.events, start=1):
            fingerprint = _event_fingerprint(raw_event)
            if fingerprint in seen_fingerprints:
                skipped_count += 1
                continue
            seen_fingerprints.add(fingerprint)

            try:
                event = _dict_to_event(raw_event)
                event.validate()
            except (KeyError, TypeError, ValueError):
                skipped_count += 1
                continue

            if _is_duplicate_in_store(event_store, event):
                skipped_count += 1
                continue

            event_store.append(event)
            imported_count += 1

        return EventSyncResult(
            imported_count=imported_count,
            skipped_count=skipped_count,
            bundle_metadata=bundle.metadata,
        )


def _event_fingerprint(raw_event: dict[str, Any]) -> tuple[Any, ...]:
    return (
        raw_event.get("run_id"),
        raw_event.get("scenario_id"),
        raw_event.get("timestamp"),
        raw_event.get("stage"),
        raw_event.get("event"),
        raw_event.get("status"),
        raw_event.get("target", ""),
        raw_event.get("artifact", ""),
    )


def _dict_to_event(data: dict[str, Any]) -> Event:
    timestamp = data["timestamp"]
    if isinstance(timestamp, str):
        ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    else:
        raise ValueError("timestamp must be an ISO-8601 string")
    return Event(
        run_id=data["run_id"],
        scenario_id=data["scenario_id"],
        timestamp=ts,
        stage=data["stage"],
        event=data["event"],
        status=data["status"],
        target=data.get("target", ""),
        artifact=data.get("artifact", ""),
        evidence=dict(data.get("evidence") or {}),
        source=data.get("source", "remote"),
        exit_code=data.get("exit_code"),
        tags=list(data.get("tags") or []),
        event_schema_version=data.get("event_schema_version", EVENT_SCHEMA_VERSION),
    )


def _is_duplicate_in_store(event_store: EventStore, event: Event) -> bool:
    assert event_store.run_id is not None
    existing = event_store.list_events(event_store.run_id, event.scenario_id)
    fingerprint = (
        event.run_id,
        event.scenario_id,
        event.timestamp.isoformat().replace("+00:00", "Z"),
        event.stage,
        event.event,
        event.status,
        event.target,
        event.artifact,
    )
    for stored in existing:
        stored_fingerprint = (
            stored.run_id,
            stored.scenario_id,
            stored.timestamp.isoformat().replace("+00:00", "Z"),
            stored.stage,
            stored.event,
            stored.status,
            stored.target,
            stored.artifact,
        )
        if stored_fingerprint == fingerprint:
            return True
    return False
