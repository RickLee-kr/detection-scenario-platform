"""Traffic summary — planned vs actual counters from Event Store."""

from __future__ import annotations

from typing import Any

from dsp.engine.scenario_engine import TargetSet
from dsp.event_store import Event, EventStore


def _event_dict(event: Event) -> dict[str, Any]:
    return {
        "scenario_id": event.scenario_id,
        "event": event.event,
        "evidence": event.evidence or {},
        "target": event.target,
    }


def _count_events(events: list[dict[str, Any]], scenario_id: str, event_name: str) -> int:
    return sum(1 for e in events if e.get("scenario_id") == scenario_id and e.get("event") == event_name)


def _last_evidence(events: list[dict[str, Any]], scenario_id: str, event_name: str) -> dict[str, Any]:
    for e in reversed(events):
        if e.get("scenario_id") == scenario_id and e.get("event") == event_name:
            return dict(e.get("evidence") or {})
    return {}


def build_traffic_summary(
    store: EventStore,
    *,
    run_id: str,
    scenario_ids: list[str],
    targets: TargetSet,
    traffic_profile: str,
) -> dict[str, Any]:
    """Build planned vs actual traffic summary for a run."""
    events = [_event_dict(e) for e in store.list_events(run_id)]

    summary: dict[str, Any] = {
        "traffic_profile": traffic_profile,
        "target_net": targets.target_net,
        "discovery": {
            "enabled": targets.discovery_enabled,
            **targets.discovery_meta,
        },
        "scenarios": {},
    }

    for sid in scenario_ids:
        started = _last_evidence(events, sid, f"{sid}_started")
        if not started:
            started = _last_evidence(events, sid, "port_sweep_started")
        if not started:
            started = _last_evidence(events, sid, "http_followup_started")
        if not started:
            started = _last_evidence(events, sid, "ssh_failure_started")
        if not started:
            started = _last_evidence(events, sid, "smb_scenario_started")
        if not started:
            started = _last_evidence(events, sid, "sql_injection_started")

        completed = _last_evidence(events, sid, f"{sid}_completed")
        if not completed:
            completed = _last_evidence(events, sid, "port_sweep_completed")
        if not completed:
            completed = _last_evidence(events, sid, "http_followup_completed")
        if not completed:
            completed = _last_evidence(events, sid, "ssh_failure_completed")
        if not completed:
            completed = _last_evidence(events, sid, "smb_scenario_completed")
        if not completed:
            completed = _last_evidence(events, sid, "sql_injection_completed")

        skipped = _last_evidence(events, sid, f"{sid}_skipped")
        if not skipped:
            skipped = _last_evidence(events, sid, "smb_scenario_skipped")
        if not skipped:
            skipped = _last_evidence(events, sid, "http_followup_skipped")
        if not skipped:
            skipped = _last_evidence(events, sid, "sql_injection_skipped")
        if not skipped:
            skipped = _last_evidence(events, sid, "ssh_failure_skipped")

        scenario_summary: dict[str, Any] = {
            "target_ips": completed.get("targets") or started.get("hosts") or skipped.get("hosts") or [],
            "skipped": bool(skipped),
            "skip_reason": skipped.get("reason"),
        }

        if sid == "port_sweep":
            scenario_summary.update({
                "probes_planned": started.get("planned_probes", 0),
                "probes_sent": completed.get("probe_count") or _count_events(events, sid, "port_probe_sent"),
                "connections_open": completed.get("connection_success_count", 0),
                "connection_failures": completed.get("connection_failure_count", 0),
                "ports": started.get("ports", []),
                "duration_sec": completed.get("duration_sec"),
                "probes_per_second": completed.get("probes_per_second"),
                "concurrency": started.get("concurrency") or completed.get("concurrency"),
            })
        elif sid == "http_followup":
            scenario_summary.update({
                "requests_planned": started.get("planned_requests", 0),
                "requests_sent": completed.get("request_count") or _count_events(events, sid, "http_request_sent"),
                "responses_received": completed.get("response_count", 0),
                "paths_sample": completed.get("paths_used") or started.get("paths_planned"),
                "user_agent_classes": completed.get("user_agent_classes", {}),
                "malicious_rare_ua_count": completed.get("malicious_rare_ua_count", 0),
                "ports_used": completed.get("ports_used", []),
                "schemes_used": completed.get("schemes_used", []),
                "scheme_by_port": completed.get("scheme_by_port", {}),
                "https_fallback": False,
                "https_targets_skipped": completed.get("https_targets_skipped")
                or started.get("https_targets_skipped")
                or skipped.get("https_targets_skipped", []),
                "http_targets": completed.get("http_targets") or started.get("http_targets", []),
                "https_targets": completed.get("https_targets") or started.get("https_targets", []),
                "skipped_no_http_service": skipped.get("skipped_no_http_service", False),
                "http_targets_not_found": skipped.get("http_targets_not_found", False)
                or skipped.get("reason") == "HTTP_TARGETS_NOT_FOUND",
                "duration_sec": completed.get("duration_sec"),
                "response_code_distribution": completed.get("response_code_distribution", {}),
                "selected_http_target_reason": completed.get("selected_http_target_reason")
                or started.get("selected_http_target_reason", ""),
                "redirect_only_warning": completed.get("redirect_only_warning", False),
                "probe_summaries": completed.get("probe_summaries") or started.get("probe_summaries", []),
                "target_probe": completed.get("target_probe")
                or started.get("target_probe")
                or completed.get("probe_summaries")
                or started.get("probe_summaries", []),
                "rejected_targets": completed.get("rejected_targets")
                or started.get("rejected_targets")
                or skipped.get("rejected_targets", []),
                "redirect_only_candidates": completed.get("redirect_only_candidates")
                or started.get("redirect_only_candidates", []),
                "target_count": completed.get("target_count", len(completed.get("target_distribution", {}))),
                "concentrated_target": completed.get("concentrated_target", ""),
                "target_distribution": completed.get("target_distribution", {}),
                "selected_targets": completed.get("selected_targets")
                or started.get("selected_targets", []),
                "requests_per_target": completed.get("requests_per_target")
                or started.get("requests_per_target", {}),
                "per_target_request_count": completed.get("per_target_request_count", {}),
                "per_target_error_count": completed.get("per_target_error_count", {}),
                "abnormal_user_agents": completed.get("abnormal_user_agents", 0),
                "normal_user_agents": completed.get("normal_user_agents", 0),
                "abnormal_user_agent_ratio": completed.get("abnormal_user_agent_ratio", 0.0),
                "payload_only_ua": completed.get("payload_only_ua", 0),
                "abnormal_ua_ratio": completed.get("abnormal_ua_ratio")
                or started.get("abnormal_ua_ratio", 0.0),
                "expected_url_scan_distribution": completed.get("expected_url_scan_distribution")
                or started.get("expected_url_scan_distribution", {}),
            })
        elif sid == "ssh_failure":
            scenario_summary.update({
                "auth_attempts_planned": started.get("planned_attempts", 0),
                "auth_attempts": completed.get("attempt_count") or _count_events(events, sid, "ssh_auth_attempt"),
                "auth_failed": completed.get("failure_count") or _count_events(events, sid, "ssh_auth_failed"),
                "timeouts": _count_events(events, sid, "ssh_auth_timeout"),
                "sample_usernames": completed.get("sample_usernames", []),
            })
        elif sid == "smb_login_failure":
            scenario_summary.update({
                "attempts_planned": started.get("planned_attempts", 0),
                "tcp_connect_attempts": completed.get("tcp_connect_attempts", 0),
                "tcp_connect_open": completed.get("tcp_connect_open", 0),
                "tcp_connect_failed": completed.get("tcp_connect_failed", 0),
                "skipped_no_open_service": completed.get("skipped_no_open_service", False),
                "auth_attempts": 0,
                "auth_failed": 0,
            })
        elif sid == "sql_injection":
            scenario_summary.update({
                "requests_planned": started.get("planned_requests", 0),
                "requests_sent": completed.get("requests_sent") or completed.get("request_count", 0),
                "responses_received": completed.get("response_count", 0),
                "payload_count": completed.get("payload_count", 0),
                "payload_category_distribution": completed.get("payload_category_distribution", {}),
                "transport_distribution": completed.get("transport_distribution", {}),
                "ports_used": completed.get("ports_used", started.get("ports_used", [])),
                "schemes_used": completed.get("schemes_used", started.get("schemes_used", [])),
                "https_targets_skipped": completed.get("https_targets_skipped")
                or started.get("https_targets_skipped")
                or skipped.get("https_targets_skipped", []),
                "http_targets_not_found": skipped.get("http_targets_not_found", False)
                or skipped.get("reason") == "HTTP_TARGETS_NOT_FOUND",
                "duration_sec": completed.get("duration_sec"),
                "selected_http_target_reason": completed.get("selected_http_target_reason")
                or started.get("selected_http_target_reason", ""),
                "probe_summaries": completed.get("probe_summaries") or started.get("probe_summaries", []),
                "target_probe": completed.get("target_probe")
                or started.get("target_probe")
                or completed.get("probe_summaries")
                or started.get("probe_summaries", []),
                "rejected_targets": completed.get("rejected_targets")
                or started.get("rejected_targets")
                or skipped.get("rejected_targets", []),
                "selected_targets": completed.get("selected_targets")
                or started.get("selected_targets", []),
                "sql_injection_requests_jsonl": completed.get("sql_injection_requests_jsonl", ""),
            })

        summary["scenarios"][sid] = scenario_summary

    return summary
