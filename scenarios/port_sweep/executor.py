"""Port sweep executor — planned TCP connection probes."""

from __future__ import annotations

import time

from dsp.engine.scenario_engine import RunContext, TargetSet
from dsp.protocols.recon import (
    DEFAULT_PORTS,
    MAX_HOSTS_DEFAULT,
    MAX_PORTS_DEFAULT,
    PortSweepClient,
    append_outcome_events,
    build_port_probe_sent_event,
    build_port_sweep_completed_event,
    build_port_sweep_started_event,
    plan_port_sweep,
)


def select_port_sweep_hosts(
    targets: TargetSet,
    config: dict,
    *,
    max_hosts: int = MAX_HOSTS_DEFAULT,
) -> list[str]:
    """Select up to max_hosts targets without discovery."""
    if config.get("hosts"):
        return [str(h) for h in config["hosts"]][:max_hosts]
    if targets.hosts:
        return list(targets.hosts)[:max_hosts]
    return ["10.10.10.30"]


def _resolve_ports(config: dict, max_ports: int) -> tuple[int, ...]:
    raw = config.get("ports")
    if raw is None:
        return DEFAULT_PORTS[:max_ports]
    return tuple(int(p) for p in raw)[:max_ports]


def run(
    ctx: RunContext,
    targets: TargetSet,
    config: dict | None = None,
    scenario_id: str = "port_sweep",
) -> None:
    """Plan and execute port sweep probes; append events to Event Store."""
    params = config or {}
    max_hosts = int(params.get("max_hosts", MAX_HOSTS_DEFAULT))
    max_ports = int(params.get("max_ports", MAX_PORTS_DEFAULT))
    safe_mode = bool(params.get("safe_mode", True))
    source = "dry_run" if ctx.dry_run else "local"
    mode = "mock" if ctx.dry_run else "live"
    client = PortSweepClient(
        mode=mode,
        timeout=float(params.get("timeout", 3.0)),
        safe_mode=safe_mode,
    )

    hosts = select_port_sweep_hosts(targets, params, max_hosts=max_hosts)
    ports = _resolve_ports(params, max_ports)
    plans = plan_port_sweep(
        hosts,
        max_hosts=max_hosts,
        ports=ports,
        max_ports=max_ports,
        safe_mode=safe_mode,
    )

    probe_count = 0
    success_count = 0
    failure_count = 0
    t0 = time.monotonic()

    ctx.event_store.append(
        build_port_sweep_started_event(
            run_id=ctx.run_id,
            scenario_id=scenario_id,
            target=hosts[0],
            source=source,
            evidence={
                "hosts": hosts,
                "ports": list(ports),
                "planned_probes": len(plans),
                "max_ports": max_ports,
                "mode": mode,
                "safe_mode": safe_mode,
            },
        )
    )

    for seq, plan in enumerate(plans, start=1):
        if ctx.cancelled:
            break

        probe = client.make_probe(plan)
        artifact = plan.artifact

        probe_evidence = {
            "seq": seq,
            "host": plan.host,
            "port": plan.port,
            "safe_mode": plan.safe_mode,
        }
        ctx.event_store.append(
            build_port_probe_sent_event(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                target=plan.host,
                artifact=artifact,
                source=source,
                evidence=probe_evidence,
            )
        )
        probe_count += 1

        if mode == "mock":
            result = client.probe(plan, mock_outcome="connection_refused")
        else:
            result = client.probe(plan)

        for outcome_event in append_outcome_events(
            run_id=ctx.run_id,
            scenario_id=scenario_id,
            probe=probe,
            result=result,
            source=source,
        ):
            ctx.event_store.append(outcome_event)

        if result.connection_opened:
            success_count += 1
        else:
            failure_count += 1

    elapsed = round(time.monotonic() - t0, 3)
    ctx.event_store.append(
        build_port_sweep_completed_event(
            run_id=ctx.run_id,
            scenario_id=scenario_id,
            target=hosts[0],
            source=source,
            evidence={
                "targets": hosts,
                "hosts": hosts,
                "ports": list(ports),
                "probe_count": probe_count,
                "connection_success_count": success_count,
                "connection_failure_count": failure_count,
                "duration_sec": elapsed,
                "safe_mode": safe_mode,
            },
        )
    )
