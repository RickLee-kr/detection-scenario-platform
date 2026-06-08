"""SQL injection scenario — safe HTTP SQLi request pattern simulation."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from dsp.engine.scenario_engine import RunContext, Scenario, ScenarioSummary, TargetSet
from dsp.event_store import Event, EventQuery
from dsp.protocols.http.sqli_events import SQL_INJECTION_TRAFFIC_EVENTS


def _load_executor():
    path = Path(__file__).with_name("executor.py")
    spec = importlib.util.spec_from_file_location("sql_injection_executor", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SqlInjectionScenario(Scenario):
    @classmethod
    def scenario_id(cls) -> str:
        return "sql_injection"

    def prepare(self, ctx: RunContext, targets: TargetSet) -> None:
        mode = "mock" if ctx.dry_run else "live"
        ctx.event_store.append(
            Event(
                run_id=ctx.run_id,
                scenario_id=self.scenario_id(),
                timestamp=datetime.now(timezone.utc),
                stage="prepare",
                event="scenario_prepared",
                status="info",
                source="dry_run" if ctx.dry_run else "local",
                evidence={
                    "target_net": ctx.target_net,
                    "protocol": "sql_injection",
                    "mode": mode,
                },
            )
        )

    def execute(self, ctx: RunContext, targets: TargetSet) -> None:
        executor = _load_executor()
        params = dict(ctx.config.scenario_params.get("sql_injection", {}))
        executor.run(ctx, targets, params, scenario_id=self.scenario_id())

    def summarize(self, ctx: RunContext) -> ScenarioSummary:
        scenario_id = self.scenario_id()
        total = ctx.event_store.count(EventQuery(run_id=ctx.run_id, scenario_id=scenario_id))
        payloads = ctx.event_store.count(
            EventQuery(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                event="sql_payload_generated",
                status="info",
            )
        )
        sent = ctx.event_store.count(
            EventQuery(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                event="sql_request_sent",
                status="sent",
            )
        )

        sample_payloads: list[str] = []
        for ev in ctx.event_store.list_events(ctx.run_id, scenario_id):
            if ev.event == "sql_injection_completed":
                sample_payloads = list(ev.evidence.get("sample_payloads", []))

        mode = "mock" if ctx.dry_run else "live"
        return ScenarioSummary(
            scenario_id=scenario_id,
            metrics={
                "sql_payload_generated_count": payloads,
                "sql_request_sent_count": sent,
                "total_events": total,
            },
            event_count=total,
            notes=[
                f"SQL Injection — mode={mode}, GET query payloads",
                f"Traffic events: {', '.join(sorted(SQL_INJECTION_TRAFFIC_EVENTS))}",
                f"sample_payloads={','.join(sample_payloads[:3])}",
            ],
        )
