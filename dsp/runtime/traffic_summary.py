"""Traffic summary — planned vs actual counters from Event Store."""

from __future__ import annotations

from typing import Any

from dsp.engine.scenario_engine import TargetSet
from dsp.event_store import Event, EventStore


def _normalize_event(event: Event | dict[str, Any]) -> dict[str, Any]:
    """Normalize Event objects, dicts, or to_dict()-capable records for summary."""
    if isinstance(event, dict):
        return {
            "scenario_id": event.get("scenario_id", ""),
            "event": event.get("event", ""),
            "evidence": event.get("evidence") or {},
            "target": event.get("target", ""),
        }
    to_dict = getattr(event, "to_dict", None)
    if callable(to_dict):
        data = to_dict()
        return {
            "scenario_id": data.get("scenario_id", ""),
            "event": data.get("event", ""),
            "evidence": data.get("evidence") or {},
            "target": data.get("target", ""),
        }
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
    events = [_normalize_event(e) for e in store.list_events(run_id)]

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

        completed = _last_evidence(events, sid, f"{sid}_completed")
        if not completed:
            completed = _last_evidence(events, sid, "port_sweep_completed")
        if not completed:
            completed = _last_evidence(events, sid, "http_followup_completed")
        if not completed:
            completed = _last_evidence(events, sid, "ssh_failure_completed")
        if not completed:
            completed = _last_evidence(events, sid, "smb_scenario_completed")

        skipped = _last_evidence(events, sid, f"{sid}_skipped")
        if not skipped:
            skipped = _last_evidence(events, sid, "smb_scenario_skipped")
        if not skipped:
            skipped = _last_evidence(events, sid, "http_followup_skipped")
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
            dump_summary = completed.get("request_dump_summary") or {}
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
                "https_fallback": completed.get("https_fallback", started.get("https_fallback", False)),
                "http_targets": completed.get("http_targets") or started.get("http_targets", []),
                "https_targets": completed.get("https_targets") or started.get("https_targets", []),
                "skipped_no_http_service": skipped.get("skipped_no_http_service", False),
                "duration_sec": completed.get("duration_sec"),
                "concurrency": started.get("concurrency") or completed.get("concurrency"),
                "requests_per_second": completed.get("requests_per_second"),
                "transport": completed.get("transport") or started.get("transport"),
                "concentrated_target": completed.get("concentrated_target") or started.get("concentrated_target"),
                "host_distribution": completed.get("host_distribution", {}),
                "path_distribution": completed.get("path_distribution", {}),
                "method_distribution": completed.get("method_distribution", {}),
                "request_dump_sample_count": dump_summary.get("sample_count", 0),
                "request_dump_summary": dump_summary,
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

        summary["scenarios"][sid] = scenario_summary

    return summary
