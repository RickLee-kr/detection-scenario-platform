"""Dummy scenario — Phase 1A architecture verification (no network I/O)."""

from __future__ import annotations

from datetime import datetime, timezone

from dsp.engine.scenario_engine import RunContext, Scenario, ScenarioSummary, TargetSet
from dsp.event_store import Event


class DummyScenario(Scenario):
    @classmethod
    def scenario_id(cls) -> str:
        return "dummy"

    def prepare(self, ctx: RunContext, targets: TargetSet) -> None:
        ctx.event_store.append(
            Event(
                run_id=ctx.run_id,
                scenario_id=self.scenario_id(),
                timestamp=datetime.now(timezone.utc),
                stage="prepare",
                event="scenario_prepared",
                status="info",
                source="dry_run" if ctx.dry_run else "local",
                evidence={"target_net": ctx.target_net},
            )
        )

    def execute(self, ctx: RunContext, targets: TargetSet) -> None:
        params = ctx.config.scenario_params.get("dummy", {})
        count = int(params.get("action_count", 5))
        max_events = 100
        count = min(count, max_events)

        source = "dry_run" if ctx.dry_run else "local"
        target = targets.hosts[0] if targets.hosts else "10.10.10.20"

        for seq in range(1, count + 1):
            if ctx.cancelled:
                break
            ctx.event_store.append(
                Event(
                    run_id=ctx.run_id,
                    scenario_id=self.scenario_id(),
                    timestamp=datetime.now(timezone.utc),
                    stage="executor",
                    event="synthetic_action",
                    status="sent",
                    target=target,
                    artifact=f"dummy-artifact-{seq:04d}",
                    evidence={"seq": seq, "dry_run": ctx.dry_run},
                    source=source,
                )
            )

    def summarize(self, ctx: RunContext) -> ScenarioSummary:
        from dsp.event_store import EventQuery

        total = ctx.event_store.count(
            EventQuery(run_id=ctx.run_id, scenario_id=self.scenario_id())
        )
        sent = ctx.event_store.count(
            EventQuery(
                run_id=ctx.run_id,
                scenario_id=self.scenario_id(),
                event="synthetic_action",
                status="sent",
            )
        )
        return ScenarioSummary(
            scenario_id=self.scenario_id(),
            metrics={"synthetic_action_count": sent, "total_events": total},
            event_count=total,
            notes=["Dry-run synthetic events only — no network I/O"],
        )
