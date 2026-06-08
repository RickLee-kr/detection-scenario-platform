"""HTTP Follow-up URL planning unit tests."""

from __future__ import annotations

import pytest

from dsp.protocols.base import HttpProtocolError
from dsp.protocols.http.urls import (
    FIXED_PATHS,
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
    assert select_port_for_host(0) == PORT_PRIORITY[0]
    assert select_port_for_host(1) == PORT_PRIORITY[1]


def test_plan_followup_requires_host():
    with pytest.raises(HttpProtocolError, match="at least one host"):
        plan_followup_requests([])


def test_planned_request_url_property():
    plans = plan_followup_requests(["lab.local"], max_total=1)
    assert plans[0].path in FIXED_PATHS
    assert plans[0].url.startswith("https://")
