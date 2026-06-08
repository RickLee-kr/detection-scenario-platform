"""LDAP enumeration scenario — safe directory discovery simulation."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from dsp.engine.scenario_engine import RunContext, Scenario, ScenarioSummary, TargetSet
from dsp.event_store import Event, EventQuery
from dsp.protocols.ldap.ldap_events import LDAP_ENUM_TRAFFIC_EVENTS


def _load_executor():
    path = Path(__file__).with_name("executor.py")
    spec = importlib.util.spec_from_file_location("ldap_enumeration_executor", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LdapEnumerationScenario(Scenario):
    @classmethod
    def scenario_id(cls) -> str:
        return "ldap_enumeration"

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
                    "protocol": "ldap",
                    "mode": mode,
                    "safe_mode": True,
                },
            )
        )

    def execute(self, ctx: RunContext, targets: TargetSet) -> None:
        executor = _load_executor()
        params = dict(ctx.config.scenario_params.get("ldap_enumeration", {}))
        executor.run(ctx, targets, params, scenario_id=self.scenario_id())

    def summarize(self, ctx: RunContext) -> ScenarioSummary:
        scenario_id = self.scenario_id()
        total = ctx.event_store.count(EventQuery(run_id=ctx.run_id, scenario_id=scenario_id))
        connections = ctx.event_store.count(
            EventQuery(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                event="ldap_connection_attempt",
                status="sent",
            )
        )
        binds = ctx.event_store.count(
            EventQuery(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                event="ldap_bind_attempt",
                status="sent",
            )
        )
        searches = ctx.event_store.count(
            EventQuery(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                event="ldap_search_attempt",
                status="sent",
            )
        )

        sample_filters: list[str] = []
        for ev in ctx.event_store.list_events(ctx.run_id, scenario_id):
            if ev.event == "ldap_enum_completed":
                sample_filters = list(ev.evidence.get("sample_filters", []))

        mode = "mock" if ctx.dry_run else "live"
        return ScenarioSummary(
            scenario_id=scenario_id,
            metrics={
                "ldap_connection_attempt_count": connections,
                "ldap_bind_attempt_count": binds,
                "ldap_search_attempt_count": searches,
                "ldap_bind_or_search_attempt_count": binds + searches,
                "total_events": total,
            },
            event_count=total,
            notes=[
                f"LDAP Enumeration — mode={mode}, ports 389/636, safe_mode=true",
                f"Traffic events: {', '.join(sorted(LDAP_ENUM_TRAFFIC_EVENTS))}",
                f"sample_filters={','.join(sample_filters[:3])}",
            ],
        )
