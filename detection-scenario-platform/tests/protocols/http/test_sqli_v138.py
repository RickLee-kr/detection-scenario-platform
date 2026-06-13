"""SQL injection strengthening — v1.3.9 payload categories, volume, and endpoint diversity."""

from __future__ import annotations

import json

from dsp.protocols.http.sqli_payloads import (
    SQLI_PATHS,
    SQLI_PAYLOAD_CATEGORIES,
    SQLI_TRANSPORTS,
    plan_sqli_requests,
)
from dsp.runtime.traffic_profiles import scenario_params_for_profile
from dsp.runner import RunManager

REALISTIC_ENDPOINTS = (
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
)


def test_normal_profile_sql_injection_at_least_800_requests():
    params = scenario_params_for_profile("sql_injection", "normal")
    assert params["max_total"] >= 800
    assert params["max_hosts"] == 2
    assert params["max_per_host"] == 400


def test_plan_sqli_requests_normal_profile_volume():
    params = scenario_params_for_profile("sql_injection", "normal")
    plans = plan_sqli_requests(
        ["10.10.10.20", "10.10.10.21"],
        max_hosts=params["max_hosts"],
        max_per_host=params["max_per_host"],
        max_total=params["max_total"],
    )
    assert len(plans) == 800
    counts: dict[str, int] = {}
    for plan in plans:
        key = f"{plan.host}:{plan.port}"
        counts[key] = counts.get(key, 0) + 1
    assert len(counts) == 2
    assert all(count == 400 for count in counts.values())


def test_plan_sqli_includes_all_payload_categories():
    plans = plan_sqli_requests(
        ["10.10.10.20"],
        max_total=800,
        max_per_host=800,
    )
    categories = {p.payload_category for p in plans}
    assert categories == set(SQLI_PAYLOAD_CATEGORIES)


def test_plan_sqli_endpoint_diversity():
    plans = plan_sqli_requests(
        ["10.10.10.20", "10.10.10.21"],
        max_hosts=2,
        max_total=800,
        max_per_host=400,
    )
    paths = {p.path for p in plans}
    assert len(paths) >= 8
    for endpoint in REALISTIC_ENDPOINTS:
        assert endpoint in SQLI_PATHS
    assert paths.intersection(set(REALISTIC_ENDPOINTS))


def test_plan_sqli_uses_all_transports():
    plans = plan_sqli_requests(
        ["10.10.10.20"],
        max_total=800,
        max_per_host=800,
    )
    transports = {p.transport for p in plans}
    assert transports == set(SQLI_TRANSPORTS)
    transport_counts = {t: sum(1 for p in plans if p.transport == t) for t in SQLI_TRANSPORTS}
    for count in transport_counts.values():
        assert 250 <= count <= 280


def test_plan_sqli_varied_parameters():
    plans = plan_sqli_requests(
        ["10.10.10.20"],
        max_total=100,
        max_per_host=100,
    )
    parameters = {p.parameter for p in plans}
    assert len(parameters) >= 5


def test_sql_injection_writes_jsonl_evidence(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    _, run_dir, exit_code = manager.run(
        scenario_ids=["sql_injection"],
        target_net="10.10.10.0/24",
        dry_run=True,
        scenario_params={
            "sql_injection": {
                "hosts": ["10.10.10.20", "10.10.10.21"],
                "max_hosts": 2,
                "max_total": 800,
                "max_per_host": 400,
            }
        },
    )
    assert exit_code == 0
    jsonl_path = run_dir / "sql_injection_requests.jsonl"
    assert jsonl_path.exists()
    records = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]
    assert len(records) == 800
    required_fields = {
        "target",
        "method",
        "url",
        "path",
        "parameter",
        "payload_category",
        "payload",
        "response_code",
        "transport",
    }
    assert required_fields.issubset(records[0])
    assert "detection_success" not in records[0]
    categories = {r["payload_category"] for r in records}
    assert categories == set(SQLI_PAYLOAD_CATEGORIES)
    transports = {r["transport"] for r in records}
    assert transports == set(SQLI_TRANSPORTS)


def test_sql_injection_no_detection_success_inference(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    _, run_dir, _ = manager.run(
        scenario_ids=["sql_injection"],
        target_net="10.10.10.0/24",
        dry_run=True,
        scenario_params={
            "sql_injection": {
                "hosts": ["10.10.10.20"],
                "max_total": 5,
                "max_per_host": 5,
            }
        },
    )
    validation = json.loads((run_dir / "validation.json").read_text())
    result = validation["results"][0]
    assert "detection_success" not in result
    assert "detection_inferred" not in result.get("metrics", {})
