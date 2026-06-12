"""HTTP follow-up URL scan concentration — v1.3.8 single-target profile."""

from __future__ import annotations

from dsp.protocols.http.urls import PAYLOAD_RECON_PATHS, compute_requests_per_target, plan_followup_requests
from dsp.protocols.http.user_agents import attach_followup_user_agents, is_payload_only_user_agent
from dsp.runtime.traffic_profiles import scenario_params_for_profile
from scenarios.http_followup.executor import _bash_parity_headers


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


def test_normal_profile_http_followup_single_concentrated_target():
    params = scenario_params_for_profile("http_followup", "normal")
    assert params["max_hosts"] == 1
    assert params["max_total"] == 300
    assert params["abnormal_ua_ratio"] == 0.10
    assert "min_requests_per_target" not in params


def test_compute_requests_per_target_single_host_300():
    assert compute_requests_per_target(1, 300) == 300


def test_plan_followup_single_target_300_requests():
    plans = plan_followup_requests(
        endpoints=[("10.0.0.1", 8080)],
        max_hosts=1,
        max_per_host=300,
        max_total=300,
        include_attack_paths=True,
    )
    assert len(plans) == 300
    assert all(p.host == "10.0.0.1" and p.port == 8080 for p in plans)


def test_attach_followup_user_agents_ratio_10_percent():
    plans = plan_followup_requests(
        endpoints=[("10.0.0.1", 80)],
        max_hosts=1,
        max_per_host=300,
        max_total=300,
        include_attack_paths=True,
    )
    enriched, stats = attach_followup_user_agents(
        plans,
        campaign="test-campaign",
        abnormal_ratio=0.10,
        header_builder=_bash_parity_headers,
    )
    assert len(enriched) == 300
    assert stats["abnormal_user_agents_planned"] == 30
    assert stats["normal_user_agents_planned"] == 270
    payload_only = sum(
        1
        for plan in enriched
        if is_payload_only_user_agent((plan.headers or {}).get("User-Agent", ""))
    )
    assert payload_only == 0


def test_payload_recon_paths_include_required_scan_paths():
    for path in REQUIRED_SCAN_PATHS:
        assert path in PAYLOAD_RECON_PATHS
