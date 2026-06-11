"""HTTP Follow-up executor — bash URL scan / UA anomaly parity with burst timing."""

from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, NamedTuple

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
from dsp.protocols.http.curl_transport import curl_available
from dsp.protocols.http.urls import (
    ATTACK_SCAN_PATHS,
    MAX_HOSTS_DEFAULT,
    MAX_REQUESTS_PER_HOST_DEFAULT,
    MAX_REQUESTS_TOTAL_DEFAULT,
    REQUEST_DUMP_SAMPLE_SIZE,
    PlannedHttpRequest,
)
from dsp.protocols.http.user_agents import classify_user_agent, pick_burst_user_agent
from dsp.protocols.types import HttpRequest, HttpResponseResult

# stellar_poc_followup.sh: inter_sleep=0, ~300 unique URLs in HTTP_SCAN_WINDOW_SECONDS (~40s)
DEFAULT_CONCURRENCY = 32


class _RequestOutcome(NamedTuple):
    seq: int
    plan: PlannedHttpRequest
    request: HttpRequest
    result: HttpResponseResult
    ua: str
    ua_kind: str


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


def _campaign_id(ctx: RunContext) -> str:
    return ctx.run_id[:12]


def _bash_parity_headers(
    plan: PlannedHttpRequest,
    *,
    campaign: str,
    user_agent: str,
) -> dict[str, str]:
    """Bash curl extra_hdrs + pick_host_hdr + X-PoC-Campaign."""
    headers = {
        "Host": plan.host_header,
        "User-Agent": user_agent,
        "X-External-URL-Recon": campaign,
        "X-PoC-Mode": "external_url_scan",
        "X-PoC-Campaign": campaign,
    }
    if plan.method == "POST" and plan.body:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    return headers


def _attach_burst_user_agents(
    plans: list[PlannedHttpRequest],
    *,
    campaign: str,
) -> list[PlannedHttpRequest]:
    enriched: list[PlannedHttpRequest] = []
    for plan in plans:
        ua = pick_burst_user_agent()
        body = f"probe={campaign}" if plan.method == "POST" else plan.body
        enriched.append(
            PlannedHttpRequest(
                host=plan.host,
                port=plan.port,
                path=plan.path,
                query=plan.query,
                method=plan.method,
                body=body,
                headers=_bash_parity_headers(plan, campaign=campaign, user_agent=ua),
            )
        )
    return enriched


def _request_dump_record(outcome: _RequestOutcome) -> dict[str, Any]:
    plan = outcome.plan
    result = outcome.result
    headers = dict(plan.headers or {})
    return {
        "seq": outcome.seq,
        "method": plan.method,
        "scheme": plan.scheme,
        "host": plan.host,
        "port": plan.port,
        "path": plan.path,
        "query": plan.query,
        "full_url": plan.url,
        "user_agent": outcome.ua,
        "user_agent_class": outcome.ua_kind,
        "host_header": plan.host_header,
        "headers": headers,
        "status_code": result.status_code,
        "response_received": result.outcome == "response",
        "transport": (result.evidence or {}).get("transport", "urllib"),
    }


def _build_dump_summary(
    dump: list[dict[str, Any]],
    *,
    ua_classes: dict[str, int],
    path_counts: Counter[str],
    host_counts: Counter[str],
    method_counts: Counter[str],
) -> dict[str, Any]:
    return {
        "sample_count": len(dump),
        "user_agent_classes": ua_classes,
        "path_distribution": dict(path_counts.most_common(15)),
        "host_distribution": dict(host_counts),
        "method_distribution": dict(method_counts),
        "unique_paths": len(path_counts),
        "unique_user_agents": len({d["user_agent"] for d in dump}),
        "queries_present": sum(1 for d in dump if d.get("query")),
        "responses_in_sample": sum(1 for d in dump if d.get("response_received")),
    }


def _execute_request(
    *,
    seq: int,
    plan: PlannedHttpRequest,
    client: HttpClient,
    mode: str,
) -> _RequestOutcome:
    request = client.make_request(plan)
    ua = (plan.headers or {}).get("User-Agent", "")
    ua_kind = classify_user_agent(ua) if ua else "unknown"
    if mode == "mock":
        result = client.request(request, mock_outcome="response", mock_status_code=404)
    else:
        result = client.request(request)
    return _RequestOutcome(seq=seq, plan=plan, request=request, result=result, ua=ua, ua_kind=ua_kind)


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
    """Plan and execute HTTP URL scan burst; append events to Event Store."""
    params = config or {}
    max_hosts = int(params.get("max_hosts", MAX_HOSTS_DEFAULT))
    max_per_host = int(params.get("max_per_host", MAX_REQUESTS_PER_HOST_DEFAULT))
    max_total = int(params.get("max_total", MAX_REQUESTS_TOTAL_DEFAULT))
    include_attack_paths = bool(params.get("include_attack_paths", True))
    concurrency = max(1, int(params.get("concurrency", DEFAULT_CONCURRENCY)))
    transport = str(params.get("transport", "auto"))
    source = "dry_run" if ctx.dry_run else "local"
    mode = "mock" if ctx.dry_run else "live"
    client = HttpClient(
        mode=mode,
        timeout=float(params.get("timeout", 2.0)),
        transport=transport,
    )
    campaign = _campaign_id(ctx)
    live_transport = "curl" if (mode == "live" and client._use_curl()) else "urllib"

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
    concentrated_target = f"{endpoints[0].scheme}://{endpoints[0].host}:{endpoints[0].port}" if endpoints else ""

    plans = _attach_burst_user_agents(
        plan_followup_requests(
            endpoints=endpoint_tuples,
            max_hosts=max_hosts,
            max_per_host=max_per_host,
            max_total=max_total,
            include_attack_paths=include_attack_paths,
        ),
        campaign=campaign,
    )

    paths_planned = sorted({p.full_path for p in plans})
    ports_used = sorted({plan.port for plan in plans})
    schemes_used = sorted({plan.scheme for plan in plans})
    scheme_by_port = {plan.port: plan.scheme for plan in plans}
    ua_classes: dict[str, int] = {}
    sent_count = 0
    response_count = 0
    timeout_count = 0
    outcomes: list[_RequestOutcome] = []
    path_counts: Counter[str] = Counter()
    host_counts: Counter[str] = Counter()
    method_counts: Counter[str] = Counter()
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
                "max_hosts": max_hosts,
                "concentrated_target": concentrated_target,
                "concurrency": concurrency,
                "transport": live_transport,
                "curl_available": curl_available(),
                "mode": mode,
                "discovery": targets.discovery_enabled,
                "include_attack_paths": include_attack_paths,
                "paths_planned": paths_planned[:20],
                "mandatory_attack_paths": list(ATTACK_SCAN_PATHS),
                "https_fallback": https_fallback,
                "http_targets": targets.hosts_for_capability("http_targets"),
                "https_targets": targets.hosts_for_capability("https_targets"),
                "ua_policy": "url_scan_burst_no_normal",
                "campaign_id": campaign,
            },
        )
    )

    worker_count = min(concurrency, len(plans)) if plans else 1
    pending = list(enumerate(plans, start=1))
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        future_map = {
            pool.submit(_execute_request, seq=seq, plan=plan, client=client, mode=mode): seq
            for seq, plan in pending
        }
        for future in as_completed(future_map):
            if ctx.cancelled:
                break
            try:
                outcome = future.result()
            except Exception:
                seq = future_map[future]
                plan = plans[seq - 1]
                outcome = _RequestOutcome(
                    seq=seq,
                    plan=plan,
                    request=client.make_request(plan),
                    result=HttpResponseResult(
                        url=plan.url,
                        method=plan.method,
                        outcome="error",
                        request_id="error",
                        dry_run=mode == "mock",
                        evidence={"host": plan.host, "port": plan.port},
                    ),
                    ua=(plan.headers or {}).get("User-Agent", ""),
                    ua_kind="unknown",
                )

            outcomes.append(outcome)
            plan = outcome.plan
            ua_kind = outcome.ua_kind
            ua_classes[ua_kind] = ua_classes.get(ua_kind, 0) + 1
            path_counts[plan.path] += 1
            host_counts[plan.host] += 1
            method_counts[plan.method] += 1

            created_evidence = {
                "seq": outcome.seq,
                "host": plan.host,
                "port": plan.port,
                "scheme": plan.scheme,
                "path": plan.path,
                "query": plan.query,
                "full_url": plan.url,
                "method": plan.method,
                "user_agent_class": ua_kind,
                "user_agent": outcome.ua,
                "host_header": plan.host_header,
                "headers": dict(plan.headers or {}),
                "transport": live_transport,
            }
            ctx.event_store.append(
                build_http_request_created_event(
                    run_id=ctx.run_id,
                    scenario_id=scenario_id,
                    target=plan.host,
                    url=outcome.request.url,
                    source=source,
                    evidence=created_evidence,
                )
            )
            ctx.event_store.append(
                build_http_request_sent_event(
                    run_id=ctx.run_id,
                    scenario_id=scenario_id,
                    target=plan.host,
                    url=outcome.request.url,
                    source=source,
                    evidence={**created_evidence, "url": outcome.request.url},
                )
            )
            sent_count += 1

            ctx.event_store.append(
                append_outcome_event(
                    run_id=ctx.run_id,
                    scenario_id=scenario_id,
                    request=outcome.request,
                    result=outcome.result,
                    source=source,
                )
            )
            if outcome.result.outcome == "response":
                response_count += 1
            elif outcome.result.outcome == "timeout":
                timeout_count += 1

    outcomes.sort(key=lambda o: o.seq)
    request_dump = [_request_dump_record(o) for o in outcomes[:REQUEST_DUMP_SAMPLE_SIZE]]

    malicious_rare_count = sum(
        count for kind, count in ua_classes.items() if kind != "normal"
    )
    dump_summary = _build_dump_summary(
        request_dump,
        ua_classes=ua_classes,
        path_counts=path_counts,
        host_counts=host_counts,
        method_counts=method_counts,
    )
    elapsed = round(time.monotonic() - t0, 3)
    requests_per_second = round(sent_count / elapsed, 2) if elapsed > 0 else 0.0
    ctx.event_store.append(
        build_http_followup_completed_event(
            run_id=ctx.run_id,
            scenario_id=scenario_id,
            target=hosts[0],
            source=source,
            evidence={
                "targets": hosts,
                "concentrated_target": concentrated_target,
                "ports_used": ports_used,
                "schemes_used": schemes_used,
                "scheme_by_port": scheme_by_port,
                "paths_used": paths_planned[:20],
                "requests_planned": len(plans),
                "request_count": sent_count,
                "requests_sent": sent_count,
                "response_count": response_count,
                "responses_received": response_count,
                "timeouts": timeout_count,
                "duration_sec": elapsed,
                "concurrency": concurrency,
                "requests_per_second": requests_per_second,
                "transport": live_transport,
                "user_agent_classes": ua_classes,
                "malicious_rare_ua_count": malicious_rare_count,
                "https_fallback": https_fallback,
                "http_targets": targets.hosts_for_capability("http_targets"),
                "https_targets": targets.hosts_for_capability("https_targets"),
                "request_dump": request_dump,
                "request_dump_summary": dump_summary,
                "host_distribution": dict(host_counts),
                "path_distribution": dict(path_counts.most_common(15)),
                "method_distribution": dict(method_counts),
                "ua_policy": "url_scan_burst_no_normal",
                "campaign_id": campaign,
            },
        )
    )
