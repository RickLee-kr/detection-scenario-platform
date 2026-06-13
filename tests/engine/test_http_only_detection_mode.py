"""HTTP-only detection mode — no HTTPS targets or requests for URL scan / SQLi."""

from __future__ import annotations

from dsp.engine import RunConfig
from dsp.engine.host_selection import (
    SKIP_REASON_HTTP_TARGETS_NOT_FOUND,
    probe_and_select_http_followup_endpoints,
)
from dsp.engine.scenario_engine import RunContext, TargetSet
from dsp.event_store import EventStore
from dsp.protocols.http.sqli_payloads import plan_sqli_requests
from dsp.protocols.http.urls import HTTP_DETECTION_PORTS, HTTP_PORT_PRIORITY, HTTPS_PORT_PRIORITY, PORT_PRIORITY, plan_followup_requests
from dsp.runtime.traffic_summary import build_traffic_summary
from scenarios.http_followup import executor as http_followup_executor
from scenarios.sql_injection import executor as sql_injection_executor


def test_port_priority_is_http_only():
    assert PORT_PRIORITY == HTTP_PORT_PRIORITY
    assert not set(PORT_PRIORITY).intersection({443, 8443})
    assert HTTP_DETECTION_PORTS == frozenset((80, 8080, 8000, 8008, 8888, 9000))


def test_no_https_target_selected_when_http_available():
    targets = TargetSet(
        target_net="10.10.10.0/24",
        service_hosts={
            "http_targets": ["10.10.10.20"],
            "https_targets": ["10.10.10.20", "10.10.10.21"],
        },
        service_endpoints={
            "http_targets": [("10.10.10.20", 8080)],
            "https_targets": [("10.10.10.20", 443), ("10.10.10.21", 8443)],
        },
        discovery_enabled=True,
    )
    selection = probe_and_select_http_followup_endpoints(targets, {}, max_hosts=2, client=None)
    assert selection.skip_reason is None
    assert selection.endpoints
    assert all(ep.scheme == "http" for ep in selection.endpoints)
    assert all(ep.port in HTTP_DETECTION_PORTS for ep in selection.endpoints)
    assert all(ep.port not in (443, 8443) for ep in selection.endpoints)


def test_scenario_skipped_when_only_https_exists():
    targets = TargetSet(
        target_net="10.10.10.0/24",
        service_hosts={"https_targets": ["10.10.10.21"]},
        service_endpoints={"https_targets": [("10.10.10.21", 443)]},
        discovery_enabled=True,
    )
    selection = probe_and_select_http_followup_endpoints(targets, {}, max_hosts=2, client=None)
    assert selection.endpoints == []
    assert selection.skip_reason == SKIP_REASON_HTTP_TARGETS_NOT_FOUND
    assert selection.https_targets_skipped == ["10.10.10.21:443"]


def test_no_https_request_generated_in_planned_followup():
    plans = plan_followup_requests(
        endpoints=[("10.0.0.1", 8080), ("10.0.0.2", 8000)],
        max_hosts=2,
        max_per_host=5,
        max_total=10,
    )
    assert plans
    assert all(p.url.startswith("http://") for p in plans)
    assert all(p.scheme == "http" for p in plans)
    assert all(p.port in HTTP_DETECTION_PORTS for p in plans)


def test_no_https_request_generated_in_planned_sqli():
    plans = plan_sqli_requests(
        ["10.10.10.20", "10.10.10.21"],
        endpoints=[("10.10.10.20", 80), ("10.10.10.21", 8080)],
        max_hosts=2,
        max_per_host=5,
        max_total=10,
    )
    assert plans
    assert all(p.url.startswith("http://") for p in plans)
    assert all(p.port in HTTP_DETECTION_PORTS for p in plans)


def test_https_ports_not_in_detection_priority():
    assert 443 not in PORT_PRIORITY
    assert 8443 not in PORT_PRIORITY
    assert HTTPS_PORT_PRIORITY == (443, 8443)


def test_target_selection_host_selectors_exist():
    from dsp.runner.target_selection import resolve_scenario_targets

    targets = TargetSet(
        target_net="10.10.10.0/24",
        service_hosts={"http_targets": ["10.10.10.20"]},
        service_endpoints={"http_targets": [("10.10.10.20", 8080)]},
        discovery_enabled=True,
    )
    http_hosts = resolve_scenario_targets("http_followup", targets, {"max_hosts": 2})
    sqli_hosts = resolve_scenario_targets("sql_injection", targets, {"max_hosts": 2})
    assert http_hosts == ["10.10.10.20"]
    assert sqli_hosts == ["10.10.10.20"]


def _only_https_targets() -> TargetSet:
    return TargetSet(
        target_net="10.10.10.0/24",
        service_hosts={"https_targets": ["10.10.10.21"]},
        service_endpoints={"https_targets": [("10.10.10.21", 443)]},
        discovery_enabled=True,
    )


def test_http_followup_executor_skips_when_only_https():
    store = EventStore(":memory:")
    run_id = "http_only_skip"
    store.open_run(run_id)
    ctx = RunContext(
        run_id=run_id,
        target_net="10.10.10.0/24",
        event_store=store,
        config=RunConfig(dry_run=True),
        dry_run=True,
    )
    http_followup_executor.run(ctx, _only_https_targets(), {})
    summary = build_traffic_summary(
        store,
        run_id=run_id,
        scenario_ids=["http_followup"],
        targets=_only_https_targets(),
        traffic_profile="balanced",
    )
    http_summary = summary["scenarios"]["http_followup"]
    assert http_summary["skipped"] is True
    assert http_summary["skip_reason"] == SKIP_REASON_HTTP_TARGETS_NOT_FOUND
    assert http_summary["https_targets_skipped"] == ["10.10.10.21:443"]


def test_sql_injection_executor_skips_when_only_https():
    store = EventStore(":memory:")
    run_id = "sqli_only_skip"
    store.open_run(run_id)
    ctx = RunContext(
        run_id=run_id,
        target_net="10.10.10.0/24",
        event_store=store,
        config=RunConfig(dry_run=True),
        dry_run=True,
    )
    targets = TargetSet(
        target_net="10.10.10.0/24",
        service_hosts={"https_targets": ["10.10.10.21"]},
        service_endpoints={"https_targets": [("10.10.10.21", 8443)]},
        discovery_enabled=True,
    )
    sql_injection_executor.run(ctx, targets, {})
    summary = build_traffic_summary(
        store,
        run_id=run_id,
        scenario_ids=["sql_injection"],
        targets=targets,
        traffic_profile="balanced",
    )
    sq_summary = summary["scenarios"]["sql_injection"]
    assert sq_summary["skipped"] is True
    assert sq_summary["skip_reason"] == SKIP_REASON_HTTP_TARGETS_NOT_FOUND
    assert sq_summary["https_targets_skipped"] == ["10.10.10.21:8443"]
