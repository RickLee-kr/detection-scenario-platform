"""HTTP Follow-up executor — URL scan with bash attack paths and UA diversity."""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from dsp.engine.host_selection import (
    HttpFollowupEndpoint,
    probe_and_select_http_followup_endpoints,
)
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
    compute_requests_per_target,
)
from dsp.protocols.http.user_agents import (
    attach_followup_user_agents,
    classify_user_agent,
    is_abnormal_user_agent,
    is_payload_only_user_agent,
)


def select_followup_endpoints(
    targets: TargetSet,
    config: dict,
    *,
    max_hosts: int = MAX_HOSTS_DEFAULT,
    client: HttpClient | None = None,
):
    return probe_and_select_http_followup_endpoints(
        targets, config, max_hosts=max_hosts, client=client
    )


def _target_key(host: str, port: int) -> str:
    return f"{host}:{port}"


def _requests_per_target(plans: list[PlannedHttpRequest]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for plan in plans:
        key = _target_key(plan.host, plan.port)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _print_http_followup_started(
    *,
    requests_per_target: dict[str, int],
    abnormal_ua_ratio: float,
) -> None:
    print("HTTP follow-up STARTED:")
    print("HTTP:")
    for target, count in sorted(requests_per_target.items()):
        print(f"  {target} requests={count}")
    print(f"selected_targets: {sorted(requests_per_target)}")
    print(f"requests_per_target: {requests_per_target}")
    print(f"abnormal_ua_ratio: {abnormal_ua_ratio:.0%}")
    print(f"expected_url_scan_distribution: {requests_per_target}")


def _run_dir_from_store(ctx: RunContext) -> Path | None:
    db_path = getattr(ctx.event_store, "_db_path", ":memory:")
    if db_path == ":memory:":
        return None
    return Path(db_path).parent


def _write_request_log(ctx: RunContext, records: list[dict[str, Any]]) -> Path | None:
    run_dir = _run_dir_from_store(ctx)
    if run_dir is None:
        return None
    out_path = run_dir / "http_followup_requests.jsonl"
    with out_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return out_path


def _errors_per_target(request_log: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in request_log:
        key = _target_key(record["host"], record["port"])
        code = record.get("response_code")
        if code is not None and 400 <= int(code) < 600:
            counts[key] = counts.get(key, 0) + 1
    return counts


def _response_code_distribution(counter: Counter[int]) -> dict[str, int]:
    return {str(code): count for code, count in sorted(counter.items())}


def _redirect_only_warning(dist: dict[str, int], total: int) -> bool:
    if total <= 0:
        return False
    redirect = sum(int(dist.get(str(code), 0)) for code in (301, 302, 303, 307, 308))
    errors = sum(int(dist.get(str(code), 0)) for code in range(400, 600))
    success = sum(int(dist.get(str(code), 0)) for code in range(200, 300))
    return redirect == total or (redirect > 0 and errors == 0 and success == 0 and redirect >= total * 0.9)


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
    min_requests_per_target = int(params.get("min_requests_per_target", 100))
    abnormal_ua_ratio = float(params.get("abnormal_ua_ratio", 0.10))
    include_attack_paths = bool(params.get("include_attack_paths", True))
    source = "dry_run" if ctx.dry_run else "local"
    mode = "mock" if ctx.dry_run else "live"
    client = HttpClient(mode=mode, timeout=float(params.get("timeout", 10.0)))

    selection = select_followup_endpoints(
        targets, params, max_hosts=max_hosts, client=client
    )
    if selection.skip_reason:
        _emit_skipped(
            ctx,
            hosts=[],
            reason=selection.skip_reason,
            scenario_id=scenario_id,
            source=source,
        )
        return

    endpoints = selection.endpoints
    endpoint_tuples = [(ep.host, ep.port) for ep in endpoints]
    hosts = [ep.host for ep in endpoints]
    https_fallback = all(ep.scheme == "https" for ep in endpoints) and bool(endpoints)

    per_target_budget = compute_requests_per_target(
        len(endpoint_tuples),
        max_total,
        min_per_target=min_requests_per_target,
    )
    max_per_host = min(max_per_host, per_target_budget)

    raw_plans = plan_followup_requests(
        endpoints=endpoint_tuples,
        max_hosts=max_hosts,
        max_per_host=max_per_host,
        max_total=max_total,
        include_attack_paths=include_attack_paths,
    )
    plans, ua_plan_stats = attach_followup_user_agents(
        raw_plans,
        abnormal_ratio=abnormal_ua_ratio,
    )
    requests_per_target = _requests_per_target(plans)
    selected_targets = sorted(requests_per_target)
    concentrated_target = selected_targets[0] if len(selected_targets) == 1 else ""
    _print_http_followup_started(
        requests_per_target=requests_per_target,
        abnormal_ua_ratio=abnormal_ua_ratio,
    )

    paths_planned = sorted({p.full_path for p in plans})
    ports_used = sorted({plan.port for plan in plans})
    schemes_used = sorted({plan.scheme for plan in plans})
    scheme_by_port = {plan.port: plan.scheme for plan in plans}
    sample_urls: list[str] = []
    ua_classes: dict[str, int] = {}
    ua_samples: list[str] = []
    sent_count = 0
    response_count = 0
    timeout_count = 0
    status_counter: Counter[int] = Counter()
    request_log: list[dict[str, Any]] = []
    t0 = time.monotonic()

    ctx.event_store.append(
        build_http_followup_started_event(
            run_id=ctx.run_id,
            scenario_id=scenario_id,
            target=hosts[0],
            source=source,
            evidence={
                "hosts": hosts,
                "endpoints": [
                    {
                        "host": ep.host,
                        "port": ep.port,
                        "scheme": ep.scheme,
                        "selection_reason": ep.selection_reason,
                    }
                    for ep in endpoints
                ],
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
                "selected_http_target_reason": selection.selected_http_target_reason,
                "probe_summaries": selection.probe_summaries,
                "redirect_only_candidates": selection.redirect_only_candidates,
                "selected_targets": selected_targets,
                "concentrated_target": concentrated_target,
                "requests_per_target": requests_per_target,
                "abnormal_ua_ratio": abnormal_ua_ratio,
                "expected_url_scan_distribution": dict(requests_per_target),
                "abnormal_user_agents_planned": ua_plan_stats["abnormal_user_agents_planned"],
                "normal_user_agents_planned": ua_plan_stats["normal_user_agents_planned"],
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
            "query": plan.query,
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
            mock_code = 404 if seq % 3 else 403
            result = client.request(request, mock_outcome="response", mock_status_code=mock_code)
        else:
            result = client.request(request)

        response_code: int | None = result.status_code
        if result.outcome == "response" and response_code is not None:
            status_counter[int(response_code)] += 1
            response_count += 1
        elif result.outcome == "timeout":
            timeout_count += 1

        request_log.append(
            {
                "seq": seq,
                "method": plan.method,
                "path": plan.path,
                "query": plan.query,
                "user_agent": ua,
                "response_code": response_code,
                "host": plan.host,
                "port": plan.port,
                "scheme": plan.scheme,
                "url": request.url,
                "outcome": result.outcome,
            }
        )

        ctx.event_store.append(
            append_outcome_event(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                request=request,
                result=result,
                source=source,
            )
        )

    abnormal_user_agents = sum(1 for record in request_log if is_abnormal_user_agent(record["user_agent"]))
    normal_user_agents = sent_count - abnormal_user_agents
    payload_only_ua = sum(
        1 for record in request_log if is_payload_only_user_agent(record["user_agent"])
    )
    target_distribution = _requests_per_target(
        [
            PlannedHttpRequest(
                host=record["host"],
                port=record["port"],
                path=record["path"],
                query=record["query"],
            )
            for record in request_log
        ]
    )
    per_target_error_count = _errors_per_target(request_log)
    per_target_request_count = dict(target_distribution)
    abnormal_user_agent_ratio = round(abnormal_user_agents / sent_count, 4) if sent_count else 0.0
    malicious_rare_count = abnormal_user_agents
    response_code_distribution = _response_code_distribution(status_counter)
    redirect_only_warning = _redirect_only_warning(response_code_distribution, response_count)
    request_log_path = _write_request_log(ctx, request_log)
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
                "abnormal_user_agents": abnormal_user_agents,
                "normal_user_agents": normal_user_agents,
                "abnormal_user_agent_ratio": abnormal_user_agent_ratio,
                "payload_only_ua": payload_only_ua,
                "target_count": len(target_distribution),
                "concentrated_target": concentrated_target,
                "target_distribution": target_distribution,
                "selected_targets": selected_targets,
                "per_target_request_count": per_target_request_count,
                "per_target_error_count": per_target_error_count,
                "requests_per_target": requests_per_target,
                "abnormal_ua_ratio": abnormal_ua_ratio,
                "expected_url_scan_distribution": dict(requests_per_target),
                "https_fallback": https_fallback,
                "http_targets": targets.hosts_for_capability("http_targets"),
                "https_targets": targets.hosts_for_capability("https_targets"),
                "selected_http_target_reason": selection.selected_http_target_reason,
                "response_code_distribution": response_code_distribution,
                "redirect_only_warning": redirect_only_warning,
                "probe_summaries": selection.probe_summaries,
                "redirect_only_candidates": selection.redirect_only_candidates,
                "http_followup_requests_jsonl": str(request_log_path) if request_log_path else "",
            },
        )
    )
