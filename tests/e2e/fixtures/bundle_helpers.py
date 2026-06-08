"""EventSyncBridge-compatible JSONL bundle helpers for E2E tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dsp import EVENT_SCHEMA_VERSION


def metadata_record(
    *,
    run_id: str,
    scenario_id: str,
    event_count: int,
    scenario_version: str = "1.0.0",
    generated_at: str = "2026-06-06T12:00:00Z",
) -> dict[str, Any]:
    return {
        "_bundle_metadata": True,
        "run_id": run_id,
        "scenario_id": scenario_id,
        "scenario_version": scenario_version,
        "generated_at": generated_at,
        "event_count": event_count,
        "schema_version": EVENT_SCHEMA_VERSION,
    }


def event_record(
    *,
    run_id: str,
    scenario_id: str,
    event: str = "synthetic_action",
    status: str = "sent",
    stage: str = "executor",
    timestamp: str = "2026-06-06T12:00:01Z",
    **extra: Any,
) -> dict[str, Any]:
    record = {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "timestamp": timestamp,
        "stage": stage,
        "event": event,
        "status": status,
        "source": "remote",
        "evidence": {},
        "tags": [],
    }
    record.update(extra)
    return record


def write_bundle(
    path: Path,
    *,
    run_id: str,
    scenario_id: str,
    events: list[dict[str, Any]],
) -> None:
    lines = [
        json.dumps(
            metadata_record(
                run_id=run_id,
                scenario_id=scenario_id,
                event_count=len(events),
            )
        )
    ]
    lines.extend(json.dumps(event) for event in events)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def remote_bundle_path_for_run(run_id: str) -> str:
    return f"/tmp/dsp/{run_id}/events.jsonl"
