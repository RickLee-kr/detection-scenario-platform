"""Host selection tests — HTTP endpoint priority."""

from __future__ import annotations

from dsp.engine.host_selection import select_http_followup_endpoints
from dsp.engine.scenario_engine import TargetSet


def test_http_followup_prefers_plain_http_endpoints():
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
    endpoints, skip = select_http_followup_endpoints(targets, {}, max_hosts=2)
    assert skip is None
    assert len(endpoints) == 1
    assert endpoints[0].scheme == "http"
    assert endpoints[0].port == 8080


def test_http_followup_https_fallback_when_no_http():
    targets = TargetSet(
        target_net="10.10.10.0/24",
        service_hosts={"https_targets": ["10.10.10.21"]},
        service_endpoints={"https_targets": [("10.10.10.21", 443)]},
        discovery_enabled=True,
    )
    endpoints, skip = select_http_followup_endpoints(targets, {}, max_hosts=2)
    assert skip is None
    assert endpoints[0].scheme == "https"
    assert endpoints[0].port == 443


def test_http_followup_skipped_no_service():
    targets = TargetSet(
        target_net="10.10.10.0/24",
        service_hosts={},
        service_endpoints={},
        discovery_enabled=True,
    )
    endpoints, skip = select_http_followup_endpoints(targets, {}, max_hosts=2)
    assert endpoints == []
    assert skip == "skipped_no_http_service"
