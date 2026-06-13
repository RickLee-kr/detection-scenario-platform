"""HTTP follow-up detection parity helpers."""

from __future__ import annotations

from dsp.protocols.http.urls import (
    build_attack_path,
    compute_requests_per_target,
    plan_followup_requests,
)
from dsp.protocols.http.user_agents import (
    attach_followup_user_agents,
    is_payload_only_user_agent,
    is_scanner_user_agent,
    pick_url_scan_user_agent,
)
from dsp.protocols.http.target_probe import HttpEndpointProbeStats, is_eligible_url_scan_target


def test_pick_url_scan_user_agent_never_payload_only():
    for _ in range(100):
        ua = pick_url_scan_user_agent()
        assert is_scanner_user_agent(ua)
        assert not is_payload_only_user_agent(ua)


def test_plan_followup_requests_include_query_payload():
    plans = plan_followup_requests(
        endpoints=[("10.0.0.1", 8080)],
        max_hosts=1,
        max_per_host=5,
        max_total=5,
        include_attack_paths=True,
    )
    assert len(plans) == 5
    assert all(plan.query.startswith("?") for plan in plans)
    assert any("WEB-INF" in plan.path or "passwd" in plan.path for plan in plans)


def test_redirect_only_probe_stats():
    stats = HttpEndpointProbeStats(host="1.2.3.4", port=80, scheme="http", status_counts={301: 7})
    assert stats.is_redirect_only
    assert stats.detection_score() < 0
    assert not is_eligible_url_scan_target(stats)

    mixed = HttpEndpointProbeStats(
        host="1.2.3.4", port=80, scheme="http", status_counts={301: 2, 404: 3}
    )
    assert not mixed.is_redirect_only
    assert is_eligible_url_scan_target(mixed)

    timeout_only = HttpEndpointProbeStats(host="1.2.3.4", port=80, scheme="http", timeouts=7)
    assert not is_eligible_url_scan_target(timeout_only)


def test_build_attack_path_keeps_path_and_query_separate():
    path, query = build_attack_path("/admin")
    assert path == "/admin"
    assert query.startswith("?")


def test_compute_requests_per_target_even_split():
    assert compute_requests_per_target(3, 300, min_per_target=100) == 100
    assert compute_requests_per_target(2, 300, min_per_target=100) == 150


def test_attach_followup_user_agents_ratio():
    plans = plan_followup_requests(
        endpoints=[("10.0.0.1", 80)],
        max_hosts=1,
        max_per_host=100,
        max_total=100,
        include_attack_paths=True,
    )
    enriched, stats = attach_followup_user_agents(plans, abnormal_ratio=0.10)
    assert len(enriched) == 100
    assert stats["abnormal_user_agents_planned"] == 10
    assert stats["normal_user_agents_planned"] == 90
    assert all(plan.query.startswith("?") for plan in enriched)
    assert all(not is_payload_only_user_agent((plan.headers or {}).get("User-Agent", "")) for plan in enriched)
