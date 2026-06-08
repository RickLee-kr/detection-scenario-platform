"""SQL injection payload generation and URL construction unit tests."""

from __future__ import annotations

import pytest

from dsp.protocols.base import HttpProtocolError
from dsp.protocols.http.sqli_payloads import (
    SQLI_PATHS,
    SQLI_PAYLOADS,
    build_sqli_url,
    plan_sqli_requests,
)


def test_sqli_paths_fixed_list():
    assert SQLI_PATHS == ("/login", "/admin", "/api", "/search", "/index.html")


def test_sqli_payloads_safe_patterns():
    assert len(SQLI_PAYLOADS) == 5
    assert "id=1' OR '1'='1" in SQLI_PAYLOADS
    assert "id=1 UNION SELECT 1" in SQLI_PAYLOADS
    assert "user=admin'--" in SQLI_PAYLOADS


def test_build_sqli_url_https_with_payload():
    url = build_sqli_url("10.10.10.20", 443, "/login", "id=1' OR '1'='1")
    assert url.startswith("https://10.10.10.20/login?")
    assert "OR" in url


def test_build_sqli_url_http_nonstandard_port():
    url = build_sqli_url("10.10.10.20", 8080, "/api", "id=1 AND 1=1")
    assert url.startswith("http://10.10.10.20:8080/api?")
    assert "AND" in url
    assert "1=1" in url


def test_plan_sqli_requests_single_host_default_caps():
    plans = plan_sqli_requests(["10.10.10.20"])
    assert len(plans) == 10
    assert all(p.host == "10.10.10.20" for p in plans)


def test_plan_sqli_requests_two_hosts_max_total():
    plans = plan_sqli_requests(["10.10.10.20", "10.10.10.21"])
    assert len(plans) == 20


def test_plan_sqli_requests_respects_max_total():
    plans = plan_sqli_requests(["10.10.10.20"], max_total=5)
    assert len(plans) == 5


def test_plan_sqli_requests_cycles_paths_and_payloads():
    plans = plan_sqli_requests(["10.10.10.20"], max_total=5)
    paths = [p.path for p in plans]
    queries = [p.query for p in plans]
    assert paths[0] == "/login"
    assert queries[0] == SQLI_PAYLOADS[0]
    assert queries[1] == SQLI_PAYLOADS[1]


def test_planned_sqli_request_url_property():
    plans = plan_sqli_requests(["lab.local"], max_total=1)
    assert "/login" in plans[0].url
    assert "?" in plans[0].url


def test_plan_sqli_requests_requires_host():
    with pytest.raises(HttpProtocolError, match="at least one host"):
        plan_sqli_requests([])
