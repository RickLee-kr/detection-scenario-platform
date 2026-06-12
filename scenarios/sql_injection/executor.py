"""SQL injection executor — planned payload URLs and HTTP requests."""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from dsp.engine.host_selection import probe_and_select_http_followup_endpoints
from dsp.engine.scenario_engine import RunContext, TargetSet
from dsp.runner.activity_reporter import ActivityReporter
from dsp.protocols.http import HttpClient
from dsp.protocols.http.sqli_events import (
    append_sqli_outcome_event,
    build_sql_injection_completed_event,
    build_sql_injection_started_event,
    build_sql_payload_generated_event,
    build_sql_request_sent_event,
)
from dsp.protocols.http.sqli_payloads import SQLI_PAYLOAD_CATEGORIES, plan_sqli_requests
from dsp.protocols.http.urls import (
    MAX_HOSTS_DEFAULT,
    MAX_REQUESTS_PER_HOST_DEFAULT,
    MAX_REQUESTS_TOTAL_DEFAULT,
)
from dsp.protocols.types import HttpRequest


def select_sqli_hosts(targets: TargetSet, config: dict, *, max_hosts: int = MAX_HOSTS_DEFAULT) -> list[str]:
    """Select up to max_hosts targets without discovery."""
    if config.get("hosts"):
        return [str(h) for h in config["hosts"]][:max_hosts]
    if targets.hosts:
        return list(targets.hosts)[:max_hosts]
    return ["10.10.10.20"]


def select_sqli_endpoints(
    targets: TargetSet,
    config: dict,
    *,
    max_hosts: int,
    client: HttpClient,
) -> tuple[list[tuple[str, int]], list[str]]:
    """Select 1–2 HTTP endpoints that respond, using probe scoring when available."""
    if config.get("hosts"):
        from dsp.protocols.http.urls import select_port_for_host

        hosts = [str(h) for h in config["hosts"]][:max_hosts]
        return [(h, select_port_for_host(i)) for i, h in enumerate(hosts)], hosts

    selection = probe_and_select_http_followup_endpoints(
        targets, config, max_hosts=max_hosts, client=client
    )
    if selection.endpoints:
        endpoints = [(ep.host, ep.port) for ep in selection.endpoints]
        hosts = [ep.host for ep in selection.endpoints]
        return endpoints, hosts

    hosts = select_sqli_hosts(targets, config, max_hosts=max_hosts)
    from dsp.protocols.http.urls import select_port_for_host

    return [(h, select_port_for_host(i)) for i, h in enumerate(hosts)], hosts


def _run_dir_from_store(ctx: RunContext) -> Path | None:
    db_path = getattr(ctx.event_store, "_db_path", ":memory:")
    if db_path == ":memory:":
        return None
    return Path(db_path).parent


def _write_sqli_request_log(ctx: RunContext, records: list[dict[str, Any]]) -> Path | None:
    run_dir = _run_dir_from_store(ctx)
    if run_dir is None:
        return None
    out_path = run_dir / "sql_injection_requests.jsonl"
    with out_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return out_path


def _make_http_request(plan) -> HttpRequest:
    path = plan.path
    if plan.query:
        path = f"{plan.path}?{plan.query}"
    headers: dict[str, str] = {}
    if plan.content_type:
        headers["Content-Type"] = plan.content_type
    return HttpRequest(
        url=plan.url,
        method=plan.method,
        host=plan.host,
        port=plan.port,
        path=path,
        headers=headers or None,
        body=plan.body,
    )


def run(
    ctx: RunContext,
    targets: TargetSet,
    config: dict | None = None,
    scenario_id: str = "sql_injection",
) -> None:
    """Plan and execute SQL injection HTTP requests; append events to Event Store."""
    params = config or {}
    max_hosts = int(params.get("max_hosts", MAX_HOSTS_DEFAULT))
    max_per_host = int(params.get("max_per_host", MAX_REQUESTS_PER_HOST_DEFAULT))
    max_total = int(params.get("max_total", MAX_REQUESTS_TOTAL_DEFAULT))
    source = "dry_run" if ctx.dry_run else "local"
    mode = "mock" if ctx.dry_run else "live"
    client = HttpClient(mode=mode, timeout=float(params.get("timeout", 10.0)))

    endpoints, hosts = select_sqli_endpoints(
        targets, params, max_hosts=max_hosts, client=client
    )
    plans = plan_sqli_requests(
        hosts,
        endpoints=endpoints,
        max_hosts=max_hosts,
        max_per_host=max_per_host,
        max_total=max_total,
    )

    ports_used = sorted({plan.port for plan in plans})
    sample_urls: list[str] = []
    sample_payloads: list[str] = []
    payload_count = 0
    sent_count = 0
    response_count = 0
    request_log: list[dict[str, Any]] = []
    category_counter: Counter[str] = Counter()
    transport_counter: Counter[str] = Counter()
    t0 = time.monotonic()
    activity = ActivityReporter(ctx, scenario_id, total=len(plans))

    ctx.event_store.append(
        build_sql_injection_started_event(
            run_id=ctx.run_id,
            scenario_id=scenario_id,
            target=hosts[0],
            source=source,
            evidence={
                "hosts": hosts,
                "endpoints": [{"host": h, "port": p} for h, p in endpoints],
                "planned_requests": len(plans),
                "max_total": max_total,
                "mode": mode,
                "payload_categories": sorted(SQLI_PAYLOAD_CATEGORIES),
            },
        )
    )

    for seq, plan in enumerate(plans, start=1):
        if ctx.cancelled:
            break

        request = _make_http_request(plan)
        if len(sample_urls) < 5:
            sample_urls.append(request.url)
        if plan.payload not in sample_payloads and len(sample_payloads) < 5:
            sample_payloads.append(plan.payload)

        payload_evidence = {
            "seq": seq,
            "host": plan.host,
            "port": plan.port,
            "path": plan.path,
            "parameter": plan.parameter,
            "payload": plan.payload,
            "payload_category": plan.payload_category,
            "method": plan.method,
            "transport": plan.transport,
        }
        ctx.event_store.append(
            build_sql_payload_generated_event(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                target=plan.host,
                url=request.url,
                source=source,
                evidence=payload_evidence,
            )
        )
        payload_count += 1

        ctx.event_store.append(
            build_sql_request_sent_event(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                target=plan.host,
                url=request.url,
                source=source,
                evidence={
                    **payload_evidence,
                    "url": request.url,
                },
            )
        )
        sent_count += 1

        if mode == "mock":
            result = client.request(request, mock_outcome="response", mock_status_code=200)
        else:
            result = client.request(request)

        request_log.append(
            {
                "seq": seq,
                "target": f"{plan.host}:{plan.port}",
                "method": plan.method,
                "url": request.url,
                "path": plan.path,
                "parameter": plan.parameter,
                "payload_category": plan.payload_category,
                "payload": plan.payload,
                "response_code": result.status_code,
                "transport": plan.transport,
            }
        )
        category_counter[plan.payload_category] += 1
        transport_counter[plan.transport] += 1

        ctx.event_store.append(
            append_sqli_outcome_event(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                request=request,
                result=result,
                source=source,
                payload=plan.payload,
            )
        )
        if result.outcome == "response":
            response_count += 1

        activity.record(
            action="request",
            method=plan.method,
            target=plan.host,
            url=request.url,
            payload_type=plan.payload_category,
            response_code=result.status_code,
        )

    activity.emit_final_progress()
    request_log_path = _write_sqli_request_log(ctx, request_log)
    elapsed = round(time.monotonic() - t0, 3)
    ctx.event_store.append(
        build_sql_injection_completed_event(
            run_id=ctx.run_id,
            scenario_id=scenario_id,
            target=hosts[0],
            source=source,
            evidence={
                "targets": hosts,
                "ports_used": ports_used,
                "request_count": sent_count,
                "requests_sent": sent_count,
                "payload_count": payload_count,
                "response_count": response_count,
                "duration_sec": elapsed,
                "sample_urls": sample_urls,
                "sample_payloads": sample_payloads,
                "payload_category_distribution": dict(category_counter),
                "transport_distribution": dict(transport_counter),
                "sql_injection_request_evidence": request_log,
                "sql_injection_requests_jsonl": str(request_log_path) if request_log_path else "",
            },
        )
    )
