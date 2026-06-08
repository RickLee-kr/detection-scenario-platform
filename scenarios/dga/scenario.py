"""DGA scenario — NXDOMAIN and resolvable domain generation."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from dsp.engine.scenario_engine import RunContext, Scenario, ScenarioSummary, TargetSet
from dsp.event_store import Event, EventQuery
from dsp.protocols.dns.dga_events import DGA_TRAFFIC_EVENTS


def _load_executor():
    path = Path(__file__).with_name("executor.py")
    spec = importlib.util.spec_from_file_location("dga_executor", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DgaScenario(Scenario):
    @classmethod
    def scenario_id(cls) -> str:
        return "dga"

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
                    "protocol": "dga",
                    "mode": mode,
                    "effective_tld": "xdr.ooo",
                },
            )
        )

    def execute(self, ctx: RunContext, targets: TargetSet) -> None:
        executor = _load_executor()
        params = dict(ctx.config.scenario_params.get("dga", {}))
        executor.run(ctx, targets, params, scenario_id=self.scenario_id())

    def summarize(self, ctx: RunContext) -> ScenarioSummary:
        scenario_id = self.scenario_id()
        total = ctx.event_store.count(EventQuery(run_id=ctx.run_id, scenario_id=scenario_id))
        generated = ctx.event_store.count(
            EventQuery(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                event="dga_domain_generated",
                status="info",
            )
        )
        nxdomain = ctx.event_store.count(
            EventQuery(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                event="dga_nxdomain_observed",
                status="nxdomain",
            )
        )
        resolved = ctx.event_store.count(
            EventQuery(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                event="dga_resolved_observed",
                status="response",
            )
        )

        effective_tld = "xdr.ooo"
        sample_domains: list[str] = []
        for ev in ctx.event_store.list_events(ctx.run_id, scenario_id):
            if ev.event == "dga_completed":
                effective_tld = ev.evidence.get("effective_tld", effective_tld)
                sample_domains = list(ev.evidence.get("sample_domains", []))

        mode = "mock" if ctx.dry_run else "live"
        return ScenarioSummary(
            scenario_id=scenario_id,
            metrics={
                "dga_domain_generated_count": generated,
                "dga_nxdomain_observed_count": nxdomain,
                "dga_resolved_observed_count": resolved,
                "total_events": total,
            },
            event_count=total,
            notes=[
                f"DGA — mode={mode}, effective_tld={effective_tld}",
                f"Traffic events: {', '.join(sorted(DGA_TRAFFIC_EVENTS))}",
                f"sample_domains={','.join(sample_domains[:3])}",
            ],
        )
