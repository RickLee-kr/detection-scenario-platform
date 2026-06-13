"""HTTP-only detection mode — no HTTPS targets or requests for URL scan / SQLi."""

from __future__ import annotations

from dsp.engine import RunConfig
from dsp.engine.host_selection import (
    SKIP_REASON_HTTP_TARGETS_NOT_FOUND,
    format_selected_target_labels,
    probe_and_select_http_followup_endpoints,
)
from dsp.engine.scenario_engine import RunContext, TargetSet
from dsp.event_store import EventStore
from dsp.protocols.http.client import HttpClient
from dsp.protocols.http.sqli_payloads import plan_sqli_requests
from dsp.protocols.http.target_probe import HttpEndpointProbeStats
from dsp.protocols.http.urls import HTTP_DETECTION_PORTS, HTTP_PORT_PRIORITY, HTTPS_PORT_PRIORITY, PORT_PRIORITY, plan_followup_requests
from dsp.runtime.traffic_summary import build_traffic_summary
from scenarios.http_followup import executor as http_followup_executor
from scenarios.sql_injection import executor as sql_injection_executor


def _probe_stats_for(host: str, port: int) -> HttpEndpointProbeStats:
    stats = HttpEndpointProbeStats(host=host, port=port, scheme="http")
    if (host, port) == ("221.139.249.110", 80):
        stats.status_counts = {301: 7}
    elif (host, port) == ("221.139.249.110", 8080):
        stats.status_counts = {400: 2}
    elif (host, port) == ("221.139.249.113", 80):
        stats.timeouts = 7
    elif (host, port) == ("221.139.249.118", 9000):
        stats.status_counts = {400: 3}
    else:
        stats.timeouts = 3
    return stats


def _run_probe_selection(monkeypatch, *, max_hosts: int = 2):
    def fake_probe(host, port, scheme, *, client, index=0):
        return _probe_stats_for(host, port)

    monkeypatch.setattr(
        "dsp.protocols.http.target_probe.probe_http_endpoint",
        fake_probe,
    )

    targets = TargetSet(
        target_net="221.139.249.0/24",
        service_hosts={
            "http_targets": [
                "221.139.249.110",
                "221.139.249.113",
                "221.139.249.118",
            ],
        },
        service_endpoints={
            "http_targets": [
                ("221.139.249.110", 80),
                ("221.139.249.113", 80),
                ("221.139.249.118", 9000),
            ],
        },
        discovery_enabled=True,
    )
    return probe_and_select_http_followup_endpoints(
        targets,
        {},
        max_hosts=max_hosts,
        client=HttpClient(mode="live"),
    )


def test_probe_quality_selects_8080_and_9000_over_port_80(monkeypatch):
    """Regression: live probe must expand ports and reject useless :80 endpoints."""
    selection = _run_probe_selection(monkeypatch)

    selected = {(ep.host, ep.port) for ep in selection.endpoints}
    assert selected == {("221.139.249.110", 8080), ("221.139.249.118", 9000)}
    assert all(ep.selection_reason == "error_responses_available" for ep in selection.endpoints)

    labels = set(format_selected_target_labels(selection.endpoints))
    assert labels == {
        "221.139.249.110:8080 (error_responses_available)",
        "221.139.249.118:9000 (error_responses_available)",
    }

    by_key = {(row["host"], row["port"]): row for row in selection.probe_summaries}
    assert by_key[("221.139.249.110", 8080)]["selected"] is True
    assert by_key[("221.139.249.118", 9000)]["selected"] is True
    assert by_key[("221.139.249.110", 80)]["selected"] is False
    assert by_key[("221.139.249.110", 80)]["rejection_reason"] == "redirect_only"
    assert by_key[("221.139.249.113", 80)]["selected"] is False
    assert by_key[("221.139.249.113", 80)]["rejection_reason"] == "timeout_only"


def test_probe_quality_prefers_response_endpoint_over_same_host_no_response(monkeypatch):
    """Regression: 118:9000 must win over 118:8080 when only 9000 returns 400."""

    def fake_probe(host, port, scheme, *, client, index=0):
        stats = HttpEndpointProbeStats(host=host, port=port, scheme="http")
        if (host, port) == ("221.139.249.110", 8080):
            stats.status_counts = {400: 2}
        elif (host, port) == ("221.139.249.118", 8080):
            stats.timeouts = 7
        elif (host, port) == ("221.139.249.118", 9000):
            stats.status_counts = {400: 3}
        else:
            stats.timeouts = 3
        return stats

    monkeypatch.setattr(
        "dsp.protocols.http.target_probe.probe_http_endpoint",
        fake_probe,
    )

    targets = TargetSet(
        target_net="221.139.249.0/24",
        service_hosts={"http_targets": ["221.139.249.110", "221.139.249.118"]},
        service_endpoints={
            "http_targets": [
                ("221.139.249.110", 8080),
                ("221.139.249.118", 8080),
                ("221.139.249.118", 9000),
            ],
        },
        discovery_enabled=True,
    )
    selection = probe_and_select_http_followup_endpoints(
        targets,
        {},
        max_hosts=2,
        client=HttpClient(mode="live"),
    )

    selected = {(ep.host, ep.port) for ep in selection.endpoints}
    assert selected == {("221.139.249.110", 8080), ("221.139.249.118", 9000)}


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
    http_targets = resolve_scenario_targets("http_followup", targets, {"max_hosts": 2})
    sqli_targets = resolve_scenario_targets("sql_injection", targets, {"max_hosts": 2})
    assert http_targets
    assert sqli_targets
    assert http_targets[0].startswith("10.10.10.20:")
    assert sqli_targets[0].startswith("10.10.10.20:")


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


def test_cached_endpoint_selection_preserves_port_into_executor(monkeypatch):
    from dsp.engine.host_selection import (
        HTTP_ENDPOINT_SELECTION_CACHE_KEY,
        cache_http_endpoint_selection,
        selection_to_cache,
    )
    from dsp.engine import RunConfig

    def fake_probe(host, port, scheme, *, client, index=0):
        return _probe_stats_for(host, port)

    monkeypatch.setattr(
        "dsp.protocols.http.target_probe.probe_http_endpoint",
        fake_probe,
    )

    targets = TargetSet(
        target_net="221.139.249.0/24",
        service_hosts={
            "http_targets": ["221.139.249.110", "221.139.249.118"],
        },
        service_endpoints={
            "http_targets": [
                ("221.139.249.110", 80),
                ("221.139.249.118", 9000),
            ],
        },
        discovery_enabled=True,
    )
    scenario_params = {
        "http_followup": {"max_hosts": 2, "max_total": 10, "max_per_host": 5},
        "sql_injection": {"max_hosts": 2, "max_total": 10, "max_per_host": 5},
    }
    cache_http_endpoint_selection(
        scenario_params,
        scenario_ids=["http_followup", "sql_injection"],
        targets=targets,
        dry_run=True,
    )
    cache = scenario_params["http_followup"][HTTP_ENDPOINT_SELECTION_CACHE_KEY]
    selected_ports = {(ep["host"], ep["port"]) for ep in cache["endpoints"]}
    assert selected_ports == {("221.139.249.110", 8080), ("221.139.249.118", 9000)}

    store = EventStore(":memory:")
    run_id = "cached_endpoints"
    store.open_run(run_id)
    ctx = RunContext(
        run_id=run_id,
        target_net="221.139.249.0/24",
        event_store=store,
        config=RunConfig(dry_run=True, scenario_params=scenario_params),
        dry_run=True,
    )
    http_followup_executor.run(ctx, targets, scenario_params["http_followup"])
    completed = [e for e in store.list_events(run_id) if e.event == "http_followup_completed"]
    assert completed
    assert completed[0].evidence["requests_sent"] > 0
    assert 9000 in completed[0].evidence["ports_used"]


def test_empty_endpoint_selection_emits_skip_not_zero_send_completed(monkeypatch):
    def fake_probe(host, port, scheme, *, client, index=0):
        stats = HttpEndpointProbeStats(host=host, port=port, scheme="http")
        stats.timeouts = 5
        return stats

    monkeypatch.setattr(
        "dsp.protocols.http.target_probe.probe_http_endpoint",
        fake_probe,
    )

    targets = TargetSet(
        target_net="221.139.249.0/24",
        service_hosts={"http_targets": ["221.139.249.110"]},
        service_endpoints={"http_targets": [("221.139.249.110", 80)]},
        discovery_enabled=True,
    )
    store = EventStore(":memory:")
    run_id = "empty_selection_skip"
    store.open_run(run_id)
    ctx = RunContext(
        run_id=run_id,
        target_net="221.139.249.0/24",
        event_store=store,
        config=RunConfig(dry_run=True),
        dry_run=True,
    )
    http_followup_executor.run(ctx, targets, {"max_hosts": 2})
    skipped = [e for e in store.list_events(run_id) if e.event == "http_followup_skipped"]
    completed = [e for e in store.list_events(run_id) if e.event == "http_followup_completed"]
    assert skipped
    assert not completed
    assert skipped[0].evidence["reason"] == SKIP_REASON_HTTP_TARGETS_NOT_FOUND
    assert skipped[0].evidence["requests_sent"] == 0
    assert skipped[0].evidence["target_probe"]
