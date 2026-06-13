"""SQL injection payload generation and URL construction unit tests."""

from __future__ import annotations

import pytest

from dsp.protocols.base import HttpProtocolError
from dsp.protocols.http.sqli_payloads import (
    SQLI_PATHS,
    SQLI_PAYLOAD_CATEGORIES,
    SQLI_PAYLOADS,
    build_sqli_url,
    plan_sqli_requests,
)


def test_sqli_paths_include_realistic_web_endpoints():
    expected = {
        "/search",
        "/search.php",
        "/product",
        "/product.php",
        "/item",
        "/item.php",
        "/login",
        "/login.php",
        "/admin/login",
        "/graphql",
        "/api/search",
        "/api/product",
        "/api/user",
        "/catalog",
        "/query",
    }
    assert expected.issubset(set(SQLI_PATHS))


def test_sqli_payload_categories_defined():
    assert "boolean_based" in SQLI_PAYLOAD_CATEGORIES
    assert "boolean_extended" in SQLI_PAYLOAD_CATEGORIES
    assert "union_extended" in SQLI_PAYLOAD_CATEGORIES
    assert "order_by_enumeration" in SQLI_PAYLOAD_CATEGORIES
    assert "db_metadata" in SQLI_PAYLOAD_CATEGORIES
    assert "mysql_error" in SQLI_PAYLOAD_CATEGORIES
    assert "mysql_time" in SQLI_PAYLOAD_CATEGORIES
    assert "mssql_time" in SQLI_PAYLOAD_CATEGORIES
    assert "file_access" in SQLI_PAYLOAD_CATEGORIES
    assert len(SQLI_PAYLOADS) > 30


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
    plans = plan_sqli_requests(["10.10.10.20"], max_per_host=10, max_total=10)
    assert len(plans) == 10
    assert all(p.host == "10.10.10.20" for p in plans)


def test_plan_sqli_requests_two_hosts_max_total():
    plans = plan_sqli_requests(
        ["10.10.10.20", "10.10.10.21"],
        max_hosts=2,
        max_per_host=10,
        max_total=20,
    )
    assert len(plans) == 20


def test_plan_sqli_requests_respects_max_total():
    plans = plan_sqli_requests(["10.10.10.20"], max_total=5, max_per_host=5)
    assert len(plans) == 5


def test_plan_sqli_requests_cycles_paths_and_categories():
    plans = plan_sqli_requests(["10.10.10.20"], max_total=5, max_per_host=5)
    assert plans[0].path in SQLI_PATHS
    assert plans[0].payload_category in SQLI_PAYLOAD_CATEGORIES
    assert plans[0].parameter == "id"


def test_planned_sqli_request_url_property():
    plans = plan_sqli_requests(["lab.local"], max_total=1, max_per_host=1)
    assert plans[0].path in SQLI_PATHS
    assert plans[0].url.startswith("http://lab.local")


def test_plan_sqli_post_form_has_body():
    plans = plan_sqli_requests(["10.10.10.20"], max_total=30, max_per_host=30)
    form_plans = [p for p in plans if p.transport == "form"]
    assert form_plans
    assert form_plans[0].method == "POST"
    assert form_plans[0].body is not None
    assert form_plans[0].content_type == "application/x-www-form-urlencoded"


def test_plan_sqli_requests_requires_host():
    with pytest.raises(HttpProtocolError, match="at least one host"):
        plan_sqli_requests([])
