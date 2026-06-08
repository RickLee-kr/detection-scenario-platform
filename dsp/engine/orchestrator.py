"""Scenario orchestration helpers."""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

from dsp.engine.scenario_engine import (
    RunContext,
    Scenario,
    ScenarioSkipError,
    ScenarioSummary,
    TargetSet,
)
from dsp.event_store import Event, EventStore
from dsp.plugins.models import PluginRecord


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _append_lifecycle(
    store: EventStore,
    run_id: str,
    scenario_id: str,
    event_name: str,
    status: str,
    stage: str,
    source: str = "runner",
    evidence: dict | None = None,
) -> None:
    store.append(
        Event(
            run_id=run_id,
            scenario_id=scenario_id,
            timestamp=_utcnow(),
            stage=stage,
            event=event_name,
            status=status,
            source=source,
            evidence=evidence or {},
        )
    )


def run_scenario(
    record: PluginRecord,
    ctx: RunContext,
    targets: TargetSet,
    snapshot_dir: Path | None = None,
) -> ScenarioSummary | None:
    """Orchestrate prepare → execute → summarize for one scenario."""
    assert record.scenario_class is not None
    scenario: Scenario = record.scenario_class()
    scenario_id = record.id

    if snapshot_dir:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"manifest.snapshot.{scenario_id}.json"
        snapshot_path.write_text(
            json.dumps(record.manifest.raw, indent=2),
            encoding="utf-8",
        )

    try:
        scenario.prepare(ctx, targets)
    except ScenarioSkipError as exc:
        _append_lifecycle(
            ctx.event_store,
            ctx.run_id,
            scenario_id,
            "scenario_skipped",
            "info",
            "prepare",
            evidence={"reason": str(exc)},
        )
        return None

    try:
        _append_lifecycle(
            ctx.event_store,
            ctx.run_id,
            scenario_id,
            "scenario_started",
            "info",
            "executor",
            source="runner",
        )
        result = scenario.execute(ctx, targets)
        if result is not None:
            raise TypeError("execute() must return None")
        _append_lifecycle(
            ctx.event_store,
            ctx.run_id,
            scenario_id,
            "scenario_completed",
            "info",
            "executor",
            source="runner",
        )
    except ScenarioSkipError:
        raise
    except Exception as exc:
        _append_lifecycle(
            ctx.event_store,
            ctx.run_id,
            scenario_id,
            "scenario_aborted",
            "error",
            "executor",
            evidence={"error": str(exc), "traceback": traceback.format_exc()},
        )
        return None

    return scenario.summarize(ctx)
