"""SSH login failure scenario — safe authentication failure simulation."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from dsp.engine.scenario_engine import RunContext, Scenario, ScenarioSummary, TargetSet
from dsp.event_store import Event, EventQuery
from dsp.protocols.ssh.events import SSH_FAILURE_TRAFFIC_EVENTS


def _load_executor():
    path = Path(__file__).with_name("executor.py")
    spec = importlib.util.spec_from_file_location("ssh_failure_executor", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SshFailureScenario(Scenario):
    @classmethod
    def scenario_id(cls) -> str:
        return "ssh_failure"

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
                    "protocol": "ssh_failure",
                    "mode": mode,
                },
            )
        )

    def execute(self, ctx: RunContext, targets: TargetSet) -> None:
        executor = _load_executor()
        params = dict(ctx.config.scenario_params.get("ssh_failure", {}))
        executor.run(ctx, targets, params, scenario_id=self.scenario_id())

    def summarize(self, ctx: RunContext) -> ScenarioSummary:
        scenario_id = self.scenario_id()
        total = ctx.event_store.count(EventQuery(run_id=ctx.run_id, scenario_id=scenario_id))
        attempts = ctx.event_store.count(
            EventQuery(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                event="ssh_auth_attempt",
                status="sent",
            )
        )
        failures = ctx.event_store.count(
            EventQuery(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                event="ssh_auth_failed",
                status="auth_failed",
            )
        )

        sample_usernames: list[str] = []
        for ev in ctx.event_store.list_events(ctx.run_id, scenario_id):
            if ev.event == "ssh_failure_completed":
                sample_usernames = list(ev.evidence.get("sample_usernames", []))

        mode = "mock" if ctx.dry_run else "live"
        return ScenarioSummary(
            scenario_id=scenario_id,
            metrics={
                "ssh_auth_attempt_count": attempts,
                "ssh_auth_failed_count": failures,
                "total_events": total,
            },
            event_count=total,
            notes=[
                f"SSH Login Failure — mode={mode}, port 22",
                f"Traffic events: {', '.join(sorted(SSH_FAILURE_TRAFFIC_EVENTS))}",
                f"sample_usernames={','.join(sample_usernames[:3])}",
            ],
        )
