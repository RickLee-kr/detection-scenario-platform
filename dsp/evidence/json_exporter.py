"""JSON evidence export — Event Store data only, no interpretation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dsp.event_store.models import Event


def _event_to_dict(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_schema_version": event.event_schema_version,
        "run_id": event.run_id,
        "timestamp": event.timestamp.isoformat().replace("+00:00", "Z"),
        "scenario_id": event.scenario_id,
        "stage": event.stage,
        "event": event.event,
        "status": event.status,
        "target": event.target,
        "artifact": event.artifact,
        "evidence": event.evidence,
        "source": event.source,
        "exit_code": event.exit_code,
        "tags": event.tags,
    }


def export_run_json(events: list[Event], run_id: str, output_directory: Path) -> Path:
    """Write run_<run_id>.json containing run metadata and raw events."""
    output_directory.mkdir(parents=True, exist_ok=True)
    path = output_directory / f"run_{run_id}.json"
    payload = {
        "run_id": run_id,
        "event_count": len(events),
        "events": [_event_to_dict(event) for event in events],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path
