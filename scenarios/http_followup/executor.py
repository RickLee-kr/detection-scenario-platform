"""HTTP Follow-up executor — fixed-path URL planning and HTTP requests."""

from __future__ import annotations

import time

from dsp.engine.scenario_engine import RunContext, TargetSet
from dsp.protocols.http import (
    HttpClient,
    append_outcome_event,
    build_http_followup_completed_event,
    build_http_followup_started_event,
    build_http_request_created_event,
    build_http_request_sent_event,
    plan_followup_requests,
)
from dsp.protocols.http.urls import (
    MAX_HOSTS_DEFAULT,
    MAX_REQUESTS_PER_HOST_DEFAULT,
    MAX_REQUESTS_TOTAL_DEFAULT,
)


def select_followup_hosts(targets: TargetSet, config: dict, *, max_hosts: int = MAX_HOSTS_DEFAULT) -> list[str]:
    """Select up to max_hosts targets without discovery."""
    if config.get("hosts"):
        return [str(h) for h in config["hosts"]][:max_hosts]
    if targets.hosts:
        return list(targets.hosts)[:max_hosts]
    return ["10.10.10.20"]


def run(
    ctx: RunContext,
    targets: TargetSet,
    config: dict | None = None,
    scenario_id: str = "http_followup",
) -> None:
    """Plan and execute HTTP follow-up requests; append events to Event Store."""
    params = config or {}
    max_hosts = int(params.get("max_hosts", MAX_HOSTS_DEFAULT))
    max_per_host = int(params.get("max_per_host", MAX_REQUESTS_PER_HOST_DEFAULT))
    max_total = int(params.get("max_total", MAX_REQUESTS_TOTAL_DEFAULT))
    source = "dry_run" if ctx.dry_run else "local"
    mode = "mock" if ctx.dry_run else "live"
    client = HttpClient(mode=mode, timeout=float(params.get("timeout", 10.0)))

    hosts = select_followup_hosts(targets, params, max_hosts=max_hosts)
    plans = plan_followup_requests(
        hosts,
        max_hosts=max_hosts,
        max_per_host=max_per_host,
        max_total=max_total,
    )

    ports_used = sorted({plan.port for plan in plans})
    sample_urls: list[str] = []
    sent_count = 0
    response_count = 0
    t0 = time.monotonic()

    ctx.event_store.append(
        build_http_followup_started_event(
            run_id=ctx.run_id,
            scenario_id=scenario_id,
            target=hosts[0],
            source=source,
            evidence={
                "hosts": hosts,
                "planned_requests": len(plans),
                "max_total": max_total,
                "mode": mode,
            },
        )
    )

    for seq, plan in enumerate(plans, start=1):
        if ctx.cancelled:
            break

        request = client.make_request(plan)
        if len(sample_urls) < 5:
            sample_urls.append(request.url)

        created_evidence = {
            "seq": seq,
            "host": plan.host,
            "port": plan.port,
            "path": plan.path,
            "method": plan.method,
        }
        ctx.event_store.append(
            build_http_request_created_event(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                target=plan.host,
                url=request.url,
                source=source,
                evidence=created_evidence,
            )
        )

        ctx.event_store.append(
            build_http_request_sent_event(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                target=plan.host,
                url=request.url,
                source=source,
                evidence={
                    **created_evidence,
                    "url": request.url,
                },
            )
        )
        sent_count += 1

        if mode == "mock":
            result = client.request(request, mock_outcome="response", mock_status_code=200)
        else:
            result = client.request(request)

        ctx.event_store.append(
            append_outcome_event(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                request=request,
                result=result,
                source=source,
            )
        )
        if result.outcome == "response":
            response_count += 1

    elapsed = round(time.monotonic() - t0, 3)
    ctx.event_store.append(
        build_http_followup_completed_event(
            run_id=ctx.run_id,
            scenario_id=scenario_id,
            target=hosts[0],
            source=source,
            evidence={
                "targets": hosts,
                "ports_used": ports_used,
                "request_count": sent_count,
                "response_count": response_count,
                "duration_sec": elapsed,
                "sample_urls": sample_urls,
            },
        )
    )
