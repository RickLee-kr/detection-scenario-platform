"""HTTP Follow-up URL planning unit tests."""

from __future__ import annotations

import pytest

from dsp.protocols.base import HttpProtocolError
from dsp.protocols.http.urls import (
    FIXED_PATHS,
    HTTP_PORT_PRIORITY,
    PORT_PRIORITY,
    build_url,
    plan_followup_requests,
    select_port_for_host,
)


def test_build_url_https_default_port():
    assert build_url("10.10.10.20", 443, "/login") == "https://10.10.10.20/login"


def test_build_url_http_default_port():
    assert build_url("10.10.10.20", 80, "/admin") == "http://10.10.10.20/admin"


def test_build_url_nonstandard_port():
    assert build_url("10.10.10.20", 8080, "/api") == "http://10.10.10.20:8080/api"


def test_fixed_paths_count():
    assert len(FIXED_PATHS) == 10


def test_plan_followup_request_caps():
    plans = plan_followup_requests(
        ["10.10.10.20", "10.10.10.21"],
        max_hosts=2,
        max_per_host=10,
        max_total=20,
    )
    assert len(plans) == 20
    assert plans[0].host == "10.10.10.20"
    assert plans[10].host == "10.10.10.21"


def test_plan_followup_respects_max_total():
    plans = plan_followup_requests(["10.10.10.20"], max_total=5)
    assert len(plans) == 5


def test_plan_followup_uses_port_priority():
    assert select_port_for_host(0) == HTTP_PORT_PRIORITY[0]
    assert select_port_for_host(1) == HTTP_PORT_PRIORITY[1]


def test_plan_followup_prefers_http_ports():
    assert PORT_PRIORITY[0] == 80
    assert HTTP_PORT_PRIORITY[0] == 80


def test_plan_followup_requires_host():
    with pytest.raises(HttpProtocolError, match="at least one host or endpoint"):
        plan_followup_requests([])


def test_planned_request_url_property():
    from dsp.protocols.http.urls import ATTACK_SCAN_PATHS

    plans = plan_followup_requests(["lab.local"], max_total=1)
    assert plans[0].path in ATTACK_SCAN_PATHS
    assert plans[0].url.startswith("http://")
    assert plans[0].port == 80


def test_plan_followup_cycles_paths_for_volume():
    plans = plan_followup_requests(["10.10.10.20"], max_per_host=50, max_total=50)
    assert len(plans) == 50
    assert plans[0].path != plans[-1].path or len({p.path for p in plans}) > 1


def test_plan_followup_includes_attack_paths_by_default():
    from dsp.protocols.http.urls import ATTACK_SCAN_PATHS

    plans = plan_followup_requests(["10.10.10.20"], max_per_host=20, max_total=20)
    planned_paths = {p.path for p in plans}
    assert ATTACK_SCAN_PATHS[0] in planned_paths
    assert "/.env" in planned_paths or "/WEB-INF/web.xml" in planned_paths
