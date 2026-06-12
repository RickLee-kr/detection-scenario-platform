"""SQL injection strengthening — v1.3.8 payload categories and volume."""

from __future__ import annotations

import json

from dsp.protocols.http.sqli_payloads import SQLI_PAYLOAD_CATEGORIES, SQLI_TRANSPORTS, plan_sqli_requests
from dsp.runtime.traffic_profiles import scenario_params_for_profile
from dsp.runner import RunManager


def test_normal_profile_sql_injection_at_least_200_requests():
    params = scenario_params_for_profile("sql_injection", "normal")
    assert params["max_total"] >= 200
    assert params["max_hosts"] in (1, 2)


def test_plan_sqli_requests_normal_profile_volume():
    params = scenario_params_for_profile("sql_injection", "normal")
    plans = plan_sqli_requests(
        ["10.10.10.20", "10.10.10.21"],
        max_hosts=params["max_hosts"],
        max_per_host=params["max_per_host"],
        max_total=params["max_total"],
    )
    assert len(plans) >= 200


def test_plan_sqli_includes_all_payload_categories():
    plans = plan_sqli_requests(
        ["10.10.10.20"],
        max_total=200,
        max_per_host=200,
    )
    categories = {p.payload_category for p in plans}
    assert categories == set(SQLI_PAYLOAD_CATEGORIES)


def test_plan_sqli_uses_all_transports():
    plans = plan_sqli_requests(
        ["10.10.10.20"],
        max_total=30,
        max_per_host=30,
    )
    transports = {p.transport for p in plans}
    assert transports == set(SQLI_TRANSPORTS)


def test_sql_injection_writes_jsonl_evidence(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    _, run_dir, exit_code = manager.run(
        scenario_ids=["sql_injection"],
        target_net="10.10.10.0/24",
        dry_run=True,
        scenario_params={
            "sql_injection": {
                "hosts": ["10.10.10.20"],
                "max_total": 20,
                "max_per_host": 20,
            }
        },
    )
    assert exit_code == 0
    jsonl_path = run_dir / "sql_injection_requests.jsonl"
    assert jsonl_path.exists()
    records = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]
    assert len(records) == 20
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
