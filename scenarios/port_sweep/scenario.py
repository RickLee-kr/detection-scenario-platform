"""Port sweep scenario — safe horizontal port sweep simulation."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from dsp.engine.scenario_engine import RunContext, Scenario, ScenarioSummary, TargetSet
from dsp.event_store import Event, EventQuery
from dsp.protocols.recon.port_sweep_events import PORT_SWEEP_TRAFFIC_EVENTS


def _load_executor():
    path = Path(__file__).with_name("executor.py")
    spec = importlib.util.spec_from_file_location("port_sweep_executor", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PortSweepScenario(Scenario):
    @classmethod
    def scenario_id(cls) -> str:
        return "port_sweep"

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
                    "protocol": "tcp",
                    "mode": mode,
                    "safe_mode": True,
                },
            )
        )

    def execute(self, ctx: RunContext, targets: TargetSet) -> None:
        executor = _load_executor()
        params = dict(ctx.config.scenario_params.get("port_sweep", {}))
        executor.run(ctx, targets, params, scenario_id=self.scenario_id())

    def summarize(self, ctx: RunContext) -> ScenarioSummary:
        scenario_id = self.scenario_id()
        total = ctx.event_store.count(EventQuery(run_id=ctx.run_id, scenario_id=scenario_id))
        probes = ctx.event_store.count(
            EventQuery(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                event="port_probe_sent",
                status="sent",
            )
        )
        opened = ctx.event_store.count(
            EventQuery(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                event="port_connection_opened",
                status="sent",
            )
        )
        failed = ctx.event_store.count(
            EventQuery(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                event="port_connection_failed",
            )
        )

        sample_ports: list[int] = []
        for ev in ctx.event_store.list_events(ctx.run_id, scenario_id):
            if ev.event == "port_sweep_completed":
                sample_ports = list(ev.evidence.get("ports", []))

        mode = "mock" if ctx.dry_run else "live"
        return ScenarioSummary(
            scenario_id=scenario_id,
            metrics={
                "port_probe_count": probes,
                "port_connection_success_count": opened,
                "port_connection_failure_count": failed,
                "port_connection_attempt_count": opened + failed,
                "total_events": total,
            },
            event_count=total,
            notes=[
                f"Port Sweep — mode={mode}, safe_mode=true",
                f"Traffic events: {', '.join(sorted(PORT_SWEEP_TRAFFIC_EVENTS))}",
                f"sample_ports={','.join(str(p) for p in sample_ports[:5])}",
            ],
        )
