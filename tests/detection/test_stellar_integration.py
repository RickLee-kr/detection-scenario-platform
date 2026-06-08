"""Phase 11 Stellar API integration tests — mock HTTP server only."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from dsp.detection.models import CorrelationContext, S3Status
from dsp.detection.providers.stellar.client_base import (
    StellarAuthError,
    StellarHttpError,
    StellarParseError,
    StellarSearchParams,
    StellarTimeoutError,
)
from dsp.detection.providers.stellar.http_client import HttpResponse, StellarHttpClient
from dsp.detection.providers.stellar.normalization import normalize_alerts, resolve_field
from dsp.detection.providers.stellar.query_builder import (
    EvidenceSource,
    build_search_params,
    evidence_types_to_query,
)
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
        run_id="20260605_int01",
        scenario_id="dns_tunnel",
        time_window_start=now - timedelta(minutes=2),
        time_window_end=now + timedelta(minutes=30),
        source_ip="10.10.10.5",
        destination_ip="10.10.10.53",
        s2_decision="success",
    )
    defaults.update(overrides)
    return CorrelationContext(**defaults)


def _env() -> dict[str, str]:
    return {
        ENV_BASE_URL: "https://stellar.example",
        ENV_API_TOKEN: "secret-token",
    }


def _alert_item(**extra) -> dict:
    base = {
        "id": "alert-int-1",
        "name": "DNS Tunnel",
        "severity": "high",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "entity_refs": ["10.10.10.5", "10.10.10.53"],
        "detection_model_id": "stellar.dns_tunnel",
    }
    base.update(extra)
    return base


def _analytics_item(**extra) -> dict:
    base = {
        "id": "incident-int-1",
        "analytic_type": "dns_query_volume_anomaly",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": "DNS volume spike",
        "detection_model_id": "stellar.dns_tunnel",
    }
    base.update(extra)
    return base


def _entity_item(**extra) -> dict:
    base = {
        "id": "entity-int-1",
        "entity_type": "ip",
        "entity_value": "10.10.10.5",
        "role": "source_ip",
    }
    base.update(extra)
    return base


def _timeline_item(**extra) -> dict:
    base = {
        "id": "timeline-int-1",
        "event_type": "dns_detection",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "description": "DNS tunnel observed",
    }
    base.update(extra)
    return base


def _ok(body: dict) -> HttpResponse:
    return HttpResponse(status_code=200, body=json.dumps(body).encode(), headers={})


def test_successful_alert_retrieval():
    transport = MockTransport([_ok({"items": [_alert_item()]})])
    client = StellarHttpClient(transport=transport, environ=_env())
    params = StellarSearchParams(context=_context(), detection_model_id="stellar.dns_tunnel")
    result = client.search_alerts(params)
    assert result.ok
    assert len(result.items) == 1


def test_successful_analytics_retrieval_post():
    transport = MockTransport([_ok({"items": [_analytics_item()]})])
    client = StellarHttpClient(transport=transport, environ=_env())
    params = StellarSearchParams(
        context=_context(),
        detection_model_id="stellar.dns_tunnel",
        http_method="POST",
        query={"run_id": "20260605_int01", "analytics_types": ["dns_query_volume_anomaly"]},
    )
    result = client.search_analytics(params)
    assert result.ok
    assert transport.calls[0]["method"] == "POST"
    assert transport.calls[0]["body"] is not None


def test_successful_entity_retrieval():
    transport = MockTransport([_ok({"items": [_entity_item()]})])
    client = StellarHttpClient(transport=transport, environ=_env())
    result = client.search_entities(StellarSearchParams(context=_context()))
    assert result.ok
    assert result.items[0]["entity_value"] == "10.10.10.5"


def test_successful_timeline_retrieval():
    transport = MockTransport([_ok({"items": [_timeline_item()]})])
    client = StellarHttpClient(transport=transport, environ=_env())
    result = client.search_timeline(StellarSearchParams(context=_context()))
    assert result.ok


def test_http_403_handling():
    transport = MockTransport([HttpResponse(status_code=403, body=b'{"error":"forbidden"}', headers={})])
    client = StellarHttpClient(transport=transport, environ=_env())
    result = client.search_alerts(StellarSearchParams(context=_context()))
    assert isinstance(result.error, StellarAuthError)


def test_http_404_handling():
    transport = MockTransport([HttpResponse(status_code=404, body=b'{"error":"not found"}', headers={})])
    client = StellarHttpClient(transport=transport, environ=_env())
    result = client.search_entities(StellarSearchParams(context=_context()))
    assert isinstance(result.error, StellarHttpError)
    assert result.http_status == 404


def test_empty_result():
    transport = MockTransport([_ok({"items": []})])
    client = StellarHttpClient(transport=transport, environ=_env())
    result = client.search_alerts(StellarSearchParams(context=_context()))
    assert result.ok
    assert result.items == []


def test_invalid_json():
    transport = MockTransport([HttpResponse(status_code=200, body=b"not-json", headers={})])
    client = StellarHttpClient(transport=transport, environ=_env())
    result = client.search_timeline(StellarSearchParams(context=_context()))
    assert isinstance(result.error, StellarParseError)


def test_timeout():
    transport = MockTransport(
        [
            StellarTimeoutError("timeout"),
            StellarTimeoutError("timeout"),
            StellarTimeoutError("timeout"),
        ]
    )
    client = StellarHttpClient(transport=transport, environ=_env())
    result = client.search_analytics(StellarSearchParams(context=_context()))
    assert isinstance(result.error, StellarTimeoutError)


def test_alias_normalization_srcip():
    raw = {"alert_id": "a1", "title": "DNS Tunnel", "srcip": "10.10.10.5"}
    alerts = normalize_alerts([raw], context=_context())
    assert len(alerts) == 1
    assert alerts[0].evidence_id == "a1"
    assert alerts[0].alert_name == "DNS Tunnel"


def test_contract_driven_queries_only_required_evidence():
    from dsp.detection.providers.stellar.contracts.contract_loader import load_scenario_contracts

    contract = load_scenario_contracts().get("dns_tunnel")
    assert contract is not None
    types = evidence_types_to_query(contract)
    assert EvidenceSource.ALERT in types
    assert EvidenceSource.ANALYTICS in types
    assert EvidenceSource.ENTITY in types
    assert EvidenceSource.TIMELINE not in types


def test_s3_confirmed_full_http_integration(tmp_path):
    transport = MockTransport(
        [
            _ok({"items": [_alert_item()]}),
            _ok({"items": [_analytics_item()]}),
            _ok({"items": [_entity_item()]}),
        ]
    )
    client = StellarHttpClient(transport=transport, environ=_env())
    adapter = StellarAdapter(client=client, client_mode="http")
    context = _context()
    evidence = adapter.collect_evidence(context)
    assert evidence.evidence_count >= 3
    assert len(transport.calls) == 3

    result = adapter.validate_detection(context, evidence)
    assert result.status == S3Status.S3_CONFIRMED

    vendor_dir = adapter.build_evidence_pack(context, evidence, result, tmp_path)
    assert (vendor_dir / "alerts.json").exists()
    assert (vendor_dir / "raw" / "alert.json").exists()
    log_text = (vendor_dir / "detection.log").read_text()
    assert "secret-token" not in log_text
    assert "s3_decision" in log_text


def test_s3_not_observed_empty_http(tmp_path):
    transport = MockTransport(
        [
            _ok({"items": []}),
            _ok({"items": []}),
            _ok({"items": []}),
        ]
    )
    client = StellarHttpClient(transport=transport, environ=_env())
    adapter = StellarAdapter(client=client, client_mode="http")
    context = _context()
    evidence = adapter.collect_evidence(context)
    result = adapter.validate_detection(context, evidence)
    assert result.status == S3Status.S3_NOT_OBSERVED


def test_s3_inconclusive_on_client_error(tmp_path):
    transport = MockTransport(
        [
            HttpResponse(status_code=401, body=b'{"error":"auth"}', headers={}),
            _ok({"items": []}),
            _ok({"items": []}),
        ]
    )
    client = StellarHttpClient(transport=transport, environ=_env())
    adapter = StellarAdapter(client=client, client_mode="http")
    context = _context()
    evidence = adapter.collect_evidence(context)
    result = adapter.validate_detection(context, evidence)
    assert result.status == S3Status.S3_INCONCLUSIVE
    assert "stellar_client_errors" in result.reason


def test_s3_inconclusive_partial_evidence_low_score(tmp_path):
    """Partial evidence without run_id match yields inconclusive or not_observed."""
    transport = MockTransport(
        [
            _ok(
                {
                    "items": [
                        _alert_item(
                            id="alert-partial",
                            entity_refs=[],
                            observed_at="2020-01-01T00:00:00Z",
                        )
                    ]
                }
            ),
            _ok({"items": []}),
            _ok({"items": []}),
        ]
    )
    client = StellarHttpClient(transport=transport, environ=_env())
    adapter = StellarAdapter(client=client, client_mode="http")
    context = _context()
    evidence = adapter.collect_evidence(context)
    result = adapter.validate_detection(context, evidence)
    assert result.status in {S3Status.S3_INCONCLUSIVE, S3Status.S3_NOT_OBSERVED}


def test_query_builder_includes_category():
    from dsp.detection.providers.stellar.contracts.contract_loader import load_scenario_contracts
    from dsp.detection.providers.stellar.stellar_mapping import load_stellar_mapping

    contract = load_scenario_contracts().get("dns_tunnel")
    mapping = load_stellar_mapping().get("dns_tunnel")
    assert contract is not None
    params = build_search_params(
        context=_context(),
        contract=contract,
        evidence_type=EvidenceSource.ALERT,
        mapping=mapping,
    )
    assert params.query.get("category") == "DNS Tunnel"
    assert params.query.get("source_ip") == "10.10.10.5"


def test_resolve_field_missing_alias_does_not_crash():
    assert resolve_field({"unknown": "x"}, "nonexistent_field") is None
