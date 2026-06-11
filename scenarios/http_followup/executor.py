"""HTTP Follow-up executor — URL scan with bash attack paths and UA diversity."""

from __future__ import annotations

import time

from dsp.engine.host_selection import HttpFollowupEndpoint, select_http_followup_endpoints
from dsp.engine.scenario_engine import RunContext, TargetSet
from dsp.event_store import Event
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
    ATTACK_SCAN_PATHS,
    MAX_HOSTS_DEFAULT,
    MAX_REQUESTS_PER_HOST_DEFAULT,
    MAX_REQUESTS_TOTAL_DEFAULT,
    PlannedHttpRequest,
)
from dsp.protocols.http.user_agents import classify_user_agent, pick_user_agent


def select_followup_endpoints(
    targets: TargetSet,
    config: dict,
    *,
    max_hosts: int = MAX_HOSTS_DEFAULT,
) -> tuple[list[HttpFollowupEndpoint], str | None]:
    return select_http_followup_endpoints(targets, config, max_hosts=max_hosts)


def select_followup_hosts(
    targets: TargetSet,
    config: dict,
    *,
    max_hosts: int = MAX_HOSTS_DEFAULT,
) -> list[str]:
    """Backward-compatible host list for console target selection."""
    endpoints, skip_reason = select_followup_endpoints(targets, config, max_hosts=max_hosts)
    if skip_reason:
        return []
    return [ep.host for ep in endpoints]


def _attach_user_agents(plans: list[PlannedHttpRequest]) -> list[PlannedHttpRequest]:
    enriched: list[PlannedHttpRequest] = []
    for plan in plans:
        ua = pick_user_agent()
        enriched.append(
            PlannedHttpRequest(
                host=plan.host,
                port=plan.port,
                path=plan.path,
                method=plan.method,
                headers={"User-Agent": ua},
            )
        )
    return enriched


def _emit_skipped(ctx: RunContext, *, hosts: list[str], reason: str, scenario_id: str, source: str) -> None:
    from datetime import datetime, timezone

    ctx.event_store.append(
        Event(
            run_id=ctx.run_id,
            scenario_id=scenario_id,
            timestamp=datetime.now(timezone.utc),
            stage="executor",
            event="http_followup_skipped",
            status="info",
            source=source,
            evidence={
                "hosts": hosts,
                "reason": reason,
                "skipped_no_http_service": reason == "skipped_no_http_service",
                "requests_planned": 0,
                "requests_sent": 0,
            },
        )
    )


def run(
    ctx: RunContext,
    targets: TargetSet,
    config: dict | None = None,
    scenario_id: str = "http_followup",
) -> None:
    """Plan and execute HTTP URL scan requests; append events to Event Store."""
    params = config or {}
    max_hosts = int(params.get("max_hosts", MAX_HOSTS_DEFAULT))
    max_per_host = int(params.get("max_per_host", MAX_REQUESTS_PER_HOST_DEFAULT))
    max_total = int(params.get("max_total", MAX_REQUESTS_TOTAL_DEFAULT))
    include_attack_paths = bool(params.get("include_attack_paths", True))
    source = "dry_run" if ctx.dry_run else "local"
    mode = "mock" if ctx.dry_run else "live"
    client = HttpClient(mode=mode, timeout=float(params.get("timeout", 10.0)))

    endpoints, skip_reason = select_followup_endpoints(targets, params, max_hosts=max_hosts)
    if skip_reason:
        _emit_skipped(
            ctx,
            hosts=[],
            reason=skip_reason,
            scenario_id=scenario_id,
            source=source,
        )
        return

    endpoint_tuples = [(ep.host, ep.port) for ep in endpoints]
    hosts = [ep.host for ep in endpoints]
    https_fallback = all(ep.scheme == "https" for ep in endpoints) and bool(endpoints)

    plans = _attach_user_agents(
        plan_followup_requests(
            endpoints=endpoint_tuples,
            max_hosts=max_hosts,
            max_per_host=max_per_host,
            max_total=max_total,
            include_attack_paths=include_attack_paths,
        )
    )

    paths_planned = sorted({p.path for p in plans})
    ports_used = sorted({plan.port for plan in plans})
    schemes_used = sorted({plan.scheme for plan in plans})
    scheme_by_port = {plan.port: plan.scheme for plan in plans}
    sample_urls: list[str] = []
    ua_classes: dict[str, int] = {}
    ua_samples: list[str] = []
    sent_count = 0
    response_count = 0
    timeout_count = 0
    t0 = time.monotonic()

    ctx.event_store.append(
        build_http_followup_started_event(
            run_id=ctx.run_id,
            scenario_id=scenario_id,
            target=hosts[0],
            source=source,
            evidence={
                "hosts": hosts,
                "endpoints": [{"host": ep.host, "port": ep.port, "scheme": ep.scheme} for ep in endpoints],
                "planned_requests": len(plans),
                "requests_planned": len(plans),
                "max_total": max_total,
                "mode": mode,
                "discovery": targets.discovery_enabled,
                "include_attack_paths": include_attack_paths,
                "paths_planned": paths_planned,
                "mandatory_attack_paths": list(ATTACK_SCAN_PATHS),
                "https_fallback": https_fallback,
                "http_targets": targets.hosts_for_capability("http_targets"),
                "https_targets": targets.hosts_for_capability("https_targets"),
            },
        )
    )

    for seq, plan in enumerate(plans, start=1):
        if ctx.cancelled:
            break

        request = client.make_request(plan)
        ua = (plan.headers or {}).get("User-Agent", "")
        ua_kind = classify_user_agent(ua) if ua else "unknown"
        ua_classes[ua_kind] = ua_classes.get(ua_kind, 0) + 1
        if len(ua_samples) < 8:
            ua_samples.append(ua[:120])

        if len(sample_urls) < 10:
            sample_urls.append(request.url)

        created_evidence = {
            "seq": seq,
            "host": plan.host,
            "port": plan.port,
            "scheme": plan.scheme,
            "path": plan.path,
            "method": plan.method,
            "user_agent_class": ua_kind,
            "user_agent": ua[:120],
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
                evidence={**created_evidence, "url": request.url},
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
        elif result.outcome == "timeout":
            timeout_count += 1

    malicious_rare_count = sum(
        count for kind, count in ua_classes.items() if kind != "normal"
    )
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
                "schemes_used": schemes_used,
                "scheme_by_port": scheme_by_port,
                "paths_used": paths_planned,
                "requests_planned": len(plans),
                "request_count": sent_count,
                "requests_sent": sent_count,
                "response_count": response_count,
                "responses_received": response_count,
                "timeouts": timeout_count,
                "duration_sec": elapsed,
                "sample_urls": sample_urls,
                "user_agent_classes": ua_classes,
                "user_agent_samples": ua_samples,
                "malicious_rare_ua_count": malicious_rare_count,
                "https_fallback": https_fallback,
                "http_targets": targets.hosts_for_capability("http_targets"),
                "https_targets": targets.hosts_for_capability("https_targets"),
            },
        )
    )
