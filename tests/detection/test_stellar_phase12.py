"""Phase 12 production hardening tests — pagination, throttle, cache, limits."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from dsp.detection.models import CorrelationContext, S3Status
from dsp.detection.providers.stellar.client_base import (
    StellarRateLimitError,
    StellarSearchParams,
    StellarTimeoutError,
)
from dsp.detection.providers.stellar.detection_cache import DetectionQueryCache, build_cache_key
from dsp.detection.providers.stellar.evidence_limits import EvidenceLimitConfig, apply_evidence_limits
from dsp.detection.providers.stellar.http_client import HttpResponse, StellarHttpClient
from dsp.detection.providers.stellar.query_throttle import QueryThrottle, QueryThrottleConfig
from dsp.detection.providers.stellar.stellar_adapter import StellarAdapter
from dsp.detection.providers.stellar.stellar_config import ENV_API_TOKEN, ENV_BASE_URL


class MockTransport:
    def __init__(self, responses: list[HttpResponse | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def request(self, **kwargs) -> HttpResponse:
        self.calls.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _context(**overrides) -> CorrelationContext:
    now = datetime.now(timezone.utc)
    defaults = dict(
        run_id="20260606_p12",
        scenario_id="dns_tunnel",
        time_window_start=now - timedelta(minutes=2),
        time_window_end=now + timedelta(minutes=30),
        source_ip="10.10.10.5",
        destination_ip="10.10.10.53",
        s2_decision="success",
    )
    defaults.update(overrides)
    return CorrelationContext(**defaults)


def _env(**overrides) -> dict[str, str]:
    base = {
        ENV_BASE_URL: "https://stellar.example",
        ENV_API_TOKEN: "secret-token",
    }
    base.update(overrides)
    return base


def _ok(body: dict) -> HttpResponse:
    return HttpResponse(status_code=200, body=json.dumps(body).encode(), headers={})


def _alert_item(item_id: str) -> dict:
    return {
        "id": item_id,
        "name": "DNS Tunnel",
        "severity": "high",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "entity_refs": ["10.10.10.5"],
        "detection_model_id": "stellar.dns_tunnel",
    }


def test_single_page_results():
    transport = MockTransport([_ok({"items": [_alert_item("a1")]})])
    client = StellarHttpClient(transport=transport, environ=_env())
    result = client.search_alerts(StellarSearchParams(context=_context()))
    assert result.ok
    assert len(result.items) == 1
    assert result.page_count == 1
    assert transport.calls[0]["url"].endswith("page_size=100")


def test_multi_page_results():
    transport = MockTransport(
        [
            _ok({"items": [_alert_item("a1")], "next_page_token": "page-2"}),
            _ok({"items": [_alert_item("a2")], "next_page_token": "page-3"}),
            _ok({"items": [_alert_item("a3")]}),
        ]
    )
    client = StellarHttpClient(
        transport=transport,
        environ=_env(DSP_STELLAR_PAGE_SIZE="1"),
    )
    result = client.search_alerts(StellarSearchParams(context=_context()))
    assert result.ok
    assert len(result.items) == 3
    assert result.page_count == 3
    assert result.total_fetched == 3
    assert "page_token=page-2" in transport.calls[1]["url"]
    assert "page_token=page-3" in transport.calls[2]["url"]


def test_pagination_empty_final_page():
    transport = MockTransport(
        [
            _ok({"items": [_alert_item("a1")], "next_page_token": "page-2"}),
            _ok({"items": []}),
        ]
    )
    client = StellarHttpClient(transport=transport, environ=_env())
    result = client.search_alerts(StellarSearchParams(context=_context()))
    assert result.ok
    assert len(result.items) == 1
    assert result.page_count == 2


def test_pagination_nested_token_field():
    transport = MockTransport(
        [
            _ok({"items": [_alert_item("a1")], "pagination": {"next_page_token": "tok-2"}}),
            _ok({"items": [_alert_item("a2")]}),
        ]
    )
    client = StellarHttpClient(transport=transport, environ=_env())
    result = client.search_entities(StellarSearchParams(context=_context()))
    assert len(result.items) == 2
    assert result.page_count == 2


def test_truncation_records_metadata():
    alerts = [{"id": f"a{i}"} for i in range(5)]
    limited_alerts, analytics, entities, timeline, summary = apply_evidence_limits(
        alerts=alerts,
        analytics=[],
        entities=[],
        timeline=[],
        config=EvidenceLimitConfig(max_alerts=3),
    )
    assert len(limited_alerts) == 3
    assert summary.any_truncated
    assert summary.records[0].original_count == 5
    assert summary.records[0].retained_count == 3


def test_truncation_written_to_evidence_md(tmp_path):
    transport = MockTransport(
        [
            _ok({"items": [_alert_item(f"a{i}") for i in range(4)]}),
            _ok({"items": []}),
            _ok({"items": []}),
        ]
    )
    client = StellarHttpClient(transport=transport, environ=_env())
    adapter = StellarAdapter(
        client=client,
        client_mode="http",
        evidence_limits=EvidenceLimitConfig(max_alerts=2, max_analytics=10, max_entities=10, max_timeline=10),
    )
    context = _context()
    evidence = adapter.collect_evidence(context)
    assert len(evidence.alerts) == 2
    result = adapter.validate_detection(context, evidence)
    vendor_dir = adapter.build_evidence_pack(context, evidence, result, tmp_path)
    evidence_md = (vendor_dir / "evidence.md").read_text()
    assert "Evidence Truncation" in evidence_md
    assert "retained 2 of 4" in evidence_md


def test_retry_behavior_on_timeout():
    transport = MockTransport(
        [
            StellarTimeoutError("timeout"),
            _ok({"items": [_alert_item("a1")]}),
        ]
    )
    throttle = QueryThrottle(QueryThrottleConfig(max_retries=2, retry_backoff_seconds=0.0))
    client = StellarHttpClient(transport=transport, environ=_env(), throttle=throttle)
    result = client.search_timeline(StellarSearchParams(context=_context()))
    assert result.ok
    assert len(result.items) == 1
    assert len(transport.calls) == 2


def test_throttling_enforces_request_delay():
    transport = MockTransport(
        [
            _ok({"items": [_alert_item("a1")], "next_page_token": "p2"}),
            _ok({"items": [_alert_item("a2")]}),
        ]
    )
    throttle = QueryThrottle(QueryThrottleConfig(request_delay_seconds=0.05, max_retries=0))
    client = StellarHttpClient(transport=transport, environ=_env(), throttle=throttle)
    started = time.monotonic()
    result = client.search_alerts(StellarSearchParams(context=_context()))
    elapsed = time.monotonic() - started
    assert result.ok
    assert len(result.items) == 2
    assert elapsed >= 0.04


def test_throttling_max_request_limit():
    transport = MockTransport(
        [
            _ok({"items": [_alert_item("a1")], "next_page_token": "p2"}),
            _ok({"items": [_alert_item("a2")], "next_page_token": "p3"}),
        ]
    )
    throttle = QueryThrottle(QueryThrottleConfig(max_requests_per_run=1, max_retries=0))
    client = StellarHttpClient(transport=transport, environ=_env(), throttle=throttle)
    result = client.search_alerts(StellarSearchParams(context=_context()))
    assert isinstance(result.error, StellarRateLimitError)
    assert len(result.items) == 1


def test_cache_hit_avoids_duplicate_request():
    from dsp.detection.providers.stellar.contracts.contract_loader import load_scenario_contracts
    from dsp.detection.providers.stellar.query_builder import build_search_params, EvidenceSource

    cache = DetectionQueryCache()
    transport = MockTransport([_ok({"items": [_alert_item("a1")]})])
    client = StellarHttpClient(transport=transport, environ=_env())
    adapter = StellarAdapter(client=client, client_mode="http", query_cache=cache)

    contract = load_scenario_contracts().get("dns_tunnel")
    assert contract is not None
    alert_params = build_search_params(
        context=_context(),
        contract=contract,
        evidence_type=EvidenceSource.ALERT,
        mapping=None,
    )

    first = adapter._search("alert", client.search_alerts, alert_params)
    second = adapter._search("alert", client.search_alerts, alert_params)
    assert first == second
    assert len(transport.calls) == 1


def test_cache_miss_on_different_window():
    cache = DetectionQueryCache()
    params_a = StellarSearchParams(context=_context(run_id="run-a"))
    params_b = StellarSearchParams(context=_context(run_id="run-b"))
    key_a = build_cache_key(provider="stellar", evidence_type="alerts", params=params_a)
    key_b = build_cache_key(provider="stellar", evidence_type="alerts", params=params_b)
    assert key_a.as_string() != key_b.as_string()


def test_timeout_recovery_returns_partial_on_failure():
    transport = MockTransport(
        [
            _ok({"items": [_alert_item("a1")], "next_page_token": "p2"}),
            StellarTimeoutError("timeout"),
            StellarTimeoutError("timeout"),
            StellarTimeoutError("timeout"),
        ]
    )
    client = StellarHttpClient(
        transport=transport,
        environ=_env(),
        throttle=QueryThrottle(QueryThrottleConfig(max_retries=1, retry_backoff_seconds=0.0)),
    )
    result = client.search_alerts(StellarSearchParams(context=_context()))
    assert isinstance(result.error, StellarTimeoutError)
    assert len(result.items) == 1
    assert result.page_count == 2


def test_partial_evidence_collection_adapter(tmp_path):
    transport = MockTransport(
        [
            HttpResponse(status_code=401, body=b'{"error":"auth"}', headers={}),
            _ok({"items": [_alert_item("a1")]}),
            _ok({"items": []}),
        ]
    )
    client = StellarHttpClient(transport=transport, environ=_env())
    adapter = StellarAdapter(client=client, client_mode="http")
    context = _context()
    evidence = adapter.collect_evidence(context)
    result = adapter.validate_detection(context, evidence)
    assert result.status == S3Status.S3_INCONCLUSIVE
    vendor_dir = adapter.build_evidence_pack(context, evidence, result, tmp_path)
    log_text = (vendor_dir / "detection.log").read_text()
    assert "execution_time_ms" in log_text
    assert "page_count" in log_text
    assert "pagination_counts" in log_text
    assert "evidence_counts" in log_text
    assert "s3_decision" in log_text
    assert "secret-token" not in log_text


def test_observability_logs_cache_hit():
    from dsp.detection.providers.stellar.client_base import StellarSearchResult
    from dsp.detection.providers.stellar.contracts.contract_loader import load_scenario_contracts
    from dsp.detection.providers.stellar.query_builder import build_search_params, EvidenceSource

    cache = DetectionQueryCache()
    contract = load_scenario_contracts().get("dns_tunnel")
    assert contract is not None
    alert_params = build_search_params(
        context=_context(),
        contract=contract,
        evidence_type=EvidenceSource.ALERT,
        mapping=None,
    )
    cache_key = build_cache_key(provider="stellar", evidence_type="alert", params=alert_params)
    cache.put(
        cache_key,
        StellarSearchResult(items=[_alert_item("cached")], page_count=1, total_fetched=1),
    )

    transport = MockTransport([])
    client = StellarHttpClient(transport=transport, environ=_env())
    adapter = StellarAdapter(client=client, client_mode="http", query_cache=cache)
    adapter._search("alert", client.search_alerts, alert_params)

    assert adapter.detection_logger.entries[-1]["cache_hit"] is True
    assert len(transport.calls) == 0
