"""DNS Tunnel scenario — idx-pattern UDP/53 exfil simulation."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from dsp.engine.scenario_engine import RunContext, Scenario, ScenarioSummary, TargetSet
from dsp.event_store import Event, EventQuery
from dsp.protocols.dns.tunnel_events import DNS_TUNNEL_TRAFFIC_EVENTS


def _load_executor():
    path = Path(__file__).with_name("executor.py")
    spec = importlib.util.spec_from_file_location("dns_tunnel_executor", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DnsTunnelScenario(Scenario):
    @classmethod
    def scenario_id(cls) -> str:
        return "dns_tunnel"

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
                    "protocol": "dns_tunnel",
                    "mode": mode,
                    "transport": "udp/53",
                },
            )
        )

    def execute(self, ctx: RunContext, targets: TargetSet) -> None:
        executor = _load_executor()
        params = dict(ctx.config.scenario_params.get("dns_tunnel", {}))
        executor.run(ctx, targets, params, scenario_id=self.scenario_id())

    def summarize(self, ctx: RunContext) -> ScenarioSummary:
        scenario_id = self.scenario_id()
        total = ctx.event_store.count(EventQuery(run_id=ctx.run_id, scenario_id=scenario_id))
        chunks = ctx.event_store.count(
            EventQuery(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                event="dns_tunnel_chunk_created",
                status="info",
            )
        )
        queries = ctx.event_store.count(
            EventQuery(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                event="dns_tunnel_query_sent",
                status="sent",
            )
        )

        duration_sec = None
        targets: list[str] = []
        sample_fqdns: list[str] = []
        for ev in ctx.event_store.list_events(ctx.run_id, scenario_id):
            if ev.event == "dns_tunnel_completed":
                duration_sec = ev.evidence.get("duration_sec")
                targets = list(ev.evidence.get("targets", []))
                sample_fqdns = list(ev.evidence.get("sample_fqdns", []))

        mode = "mock" if ctx.dry_run else "live"
        return ScenarioSummary(
            scenario_id=scenario_id,
            metrics={
                "dns_tunnel_chunk_created_count": chunks,
                "dns_tunnel_query_sent_count": queries,
                "total_events": total,
            },
            event_count=total,
            notes=[
                f"DNS Tunnel — mode={mode}, idx-pattern UDP/53",
                f"Traffic events: {', '.join(sorted(DNS_TUNNEL_TRAFFIC_EVENTS))}",
                f"duration_sec={duration_sec}",
                f"targets={','.join(targets)}",
                f"sample_fqdns={','.join(sample_fqdns[:3])}",
            ],
        )
