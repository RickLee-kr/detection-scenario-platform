"""HTTP follow-up URL scan scaling — v1.3.9 dual-target profile."""

from __future__ import annotations

from dsp.protocols.http.urls import PAYLOAD_RECON_PATHS, compute_requests_per_target, plan_followup_requests
from dsp.protocols.http.user_agents import attach_followup_user_agents, is_payload_only_user_agent
from dsp.runtime.traffic_profiles import scenario_params_for_profile
from dsp.runner import RunManager


REQUIRED_SCAN_PATHS = (
    "/.env",
    "/WEB-INF/web.xml",
    "/WEB-INF/classes/",
    "/../../etc/passwd",
    "/admin/login",
    "/actuator/env",
    "/graphql",
    "/swagger",
    "/swagger-ui.html",
    "/backup.zip",
    "/shell.jsp",
    "/cmd.jsp",
    "/backdoor.jsp",
    "/conf/server.xml",
)


def test_normal_profile_http_followup_dual_target_scaling():
    params = scenario_params_for_profile("http_followup", "normal")
    assert params["max_hosts"] == 2
    assert params["max_total"] == 300
    assert params["max_per_host"] == 150
    assert params["abnormal_ua_ratio"] == 0.10


def test_compute_requests_per_target_two_hosts_150_each():
    assert compute_requests_per_target(2, 300) == 150


def test_plan_followup_dual_target_150_requests_each():
    plans = plan_followup_requests(
        endpoints=[("10.0.0.1", 8080), ("10.0.0.2", 8080)],
        max_hosts=2,
        max_per_host=150,
        max_total=300,
        include_attack_paths=True,
    )
    assert len(plans) == 300
    counts: dict[str, int] = {}
    for plan in plans:
        key = f"{plan.host}:{plan.port}"
        counts[key] = counts.get(key, 0) + 1
    assert counts["10.0.0.1:8080"] == 150
    assert counts["10.0.0.2:8080"] == 150


def test_attach_followup_user_agents_ratio_10_percent():
    plans = plan_followup_requests(
        endpoints=[("10.0.0.1", 80), ("10.0.0.2", 80)],
        max_hosts=2,
        max_per_host=150,
        max_total=300,
        include_attack_paths=True,
    )
    enriched, stats = attach_followup_user_agents(plans, abnormal_ratio=0.10)
    assert len(enriched) == 300
    assert stats["abnormal_user_agents_planned"] == 30
    assert stats["normal_user_agents_planned"] == 270
    assert stats["abnormal_ua_ratio"] == 0.10
    payload_only = sum(
        1
        for plan in enriched
        if is_payload_only_user_agent((plan.headers or {}).get("User-Agent", ""))
    )
    assert payload_only == 0


def test_payload_recon_paths_include_required_scan_paths():
    for path in REQUIRED_SCAN_PATHS:
        assert path in PAYLOAD_RECON_PATHS


def test_http_followup_writes_per_target_summary_fields(tmp_runs_dir):
    from dsp.event_store import EventStore

    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["http_followup"],
        target_net="10.10.10.0/24",
        dry_run=True,
        scenario_params={
            "http_followup": {
                "hosts": ["10.10.10.20", "10.10.10.21"],
                "max_hosts": 2,
                "max_per_host": 150,
                "max_total": 300,
                "abnormal_ua_ratio": 0.10,
            }
        },
    )
    assert exit_code == 0
    jsonl_path = run_dir / "http_followup_requests.jsonl"
    assert jsonl_path.exists()

    store = EventStore.open_existing(run_dir / "events.db")
    completed = None
    for event in reversed(store.list_events(run.run_id)):
        if event.event == "http_followup_completed":
            completed = event.evidence or {}
            break

    assert completed is not None
    assert completed["target_count"] == 2
    assert completed["abnormal_user_agent_ratio"] == 0.10
    assert completed["abnormal_user_agents"] == 30
    assert completed["normal_user_agents"] == 270
    assert completed["payload_only_ua"] == 0
    assert "per_target_request_count" in completed
    assert "per_target_error_count" in completed
    assert sum(completed["per_target_request_count"].values()) == 300
