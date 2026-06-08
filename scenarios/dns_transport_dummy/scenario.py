"""DNS transport dummy scenario — live UDP/53 transport verification."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from dsp.engine.scenario_engine import RunContext, Scenario, ScenarioSummary, TargetSet
from dsp.event_store import Event, EventQuery
from dsp.protocols.dns import DNS_TRAFFIC_EVENTS


def _load_executor():
    path = Path(__file__).with_name("executor.py")
    spec = importlib.util.spec_from_file_location("dns_transport_dummy_executor", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DnsTransportDummyScenario(Scenario):
    @classmethod
    def scenario_id(cls) -> str:
        return "dns_transport_dummy"

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
                    "protocol": "dns",
                    "mode": mode,
                    "transport": "udp/53",
                },
            )
        )

    def execute(self, ctx: RunContext, targets: TargetSet) -> None:
        executor = _load_executor()
        params = dict(ctx.config.scenario_params.get("dns_transport_dummy", {}))
        executor.run(ctx, targets, params, scenario_id=self.scenario_id())

    def summarize(self, ctx: RunContext) -> ScenarioSummary:
        total = ctx.event_store.count(
            EventQuery(run_id=ctx.run_id, scenario_id=self.scenario_id())
        )
        sent = ctx.event_store.count(
            EventQuery(
                run_id=ctx.run_id,
                scenario_id=self.scenario_id(),
                event="dns_query_sent",
                status="sent",
            )
        )
        responses = ctx.event_store.count(
            EventQuery(
                run_id=ctx.run_id,
                scenario_id=self.scenario_id(),
                event="dns_response_received",
                status="response",
            )
        )
        mode = "mock" if ctx.dry_run else "live"
        return ScenarioSummary(
            scenario_id=self.scenario_id(),
            metrics={
                "dns_query_sent_count": sent,
                "dns_response_count": responses,
                "total_events": total,
            },
            event_count=total,
            notes=[
                f"DNS transport verification — mode={mode}, UDP/53",
                f"Traffic events: {', '.join(sorted(DNS_TRAFFIC_EVENTS))}",
            ],
        )
