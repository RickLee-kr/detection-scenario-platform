"""JSONL bundle export — EventSyncBridge-compatible write path."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from dsp import EVENT_SCHEMA_VERSION
from dsp.event_store import EventStore
from dsp.execution.webshell.event_sync.bundle import BUNDLE_METADATA_MARKER


def write_jsonl_bundle(
    store: EventStore,
    bundle_path: str | Path,
    *,
    run_id: str,
    scenario_id: str,
    scenario_version: str,
    source_override: str = "remote",
) -> Path:
    """Write Event Store events to an EventSyncBridge-compatible JSONL bundle."""
    path = Path(bundle_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    events = store.list_events(run_id, scenario_id)
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    metadata = {
        BUNDLE_METADATA_MARKER: True,
        "run_id": run_id,
        "scenario_id": scenario_id,
        "scenario_version": scenario_version,
        "generated_at": generated_at,
        "event_count": len(events),
        "schema_version": EVENT_SCHEMA_VERSION,
    }

    lines = [json.dumps(metadata)]
    for event in events:
        record = {
            "run_id": event.run_id,
            "scenario_id": event.scenario_id,
            "timestamp": event.timestamp.isoformat().replace("+00:00", "Z"),
            "stage": event.stage,
            "event": event.event,
            "status": event.status,
            "target": event.target,
            "artifact": event.artifact,
            "evidence": dict(event.evidence),
            "source": source_override,
            "tags": list(event.tags),
        }
        if event.exit_code is not None:
            record["exit_code"] = event.exit_code
        if event.event_schema_version != EVENT_SCHEMA_VERSION:
            record["event_schema_version"] = event.event_schema_version
        lines.append(json.dumps(record))

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
