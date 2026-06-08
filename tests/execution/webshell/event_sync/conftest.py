"""Shared fixtures for event sync tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dsp import EVENT_SCHEMA_VERSION

RUN_ID = "sync_run_01"
SCENARIO_ID = "dns_tunnel"
SCENARIO_VERSION = "1.0.0"
GENERATED_AT = "2026-06-06T12:00:00Z"


def event_record(
    *,
    event: str = "dns_tunnel_started",
    status: str = "info",
    stage: str = "executor",
    timestamp: str = "2026-06-06T12:00:01Z",
    **extra: Any,
) -> dict[str, Any]:
    record = {
        "run_id": RUN_ID,
        "scenario_id": SCENARIO_ID,
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


def metadata_record(*, event_count: int) -> dict[str, Any]:
    return {
        "_bundle_metadata": True,
        "run_id": RUN_ID,
        "scenario_id": SCENARIO_ID,
        "scenario_version": SCENARIO_VERSION,
        "generated_at": GENERATED_AT,
        "event_count": event_count,
        "schema_version": EVENT_SCHEMA_VERSION,
    }


def write_bundle(path: Path, events: list[dict[str, Any]]) -> None:
    lines = [json.dumps(metadata_record(event_count=len(events)))]
    lines.extend(json.dumps(event) for event in events)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
