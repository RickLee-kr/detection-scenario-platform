"""Stellar HTTP client scaffold tests — mocked transport only."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from dsp.detection.models import CorrelationContext
from dsp.detection.providers.stellar.client_base import (
    StellarAuthError,
    StellarConfigError,
    StellarHttpError,
    StellarParseError,
    StellarSearchParams,
    StellarTimeoutError,
)
from dsp.detection.providers.stellar.http_client import HttpResponse, StellarHttpClient
from dsp.detection.providers.stellar.stellar_config import (
    ENV_API_TOKEN,
    ENV_BASE_URL,
    load_stellar_config_from_env,
)


class MockTransport:
    def __init__(self, responses: list[HttpResponse | Exception]) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.last_headers: dict[str, str] | None = None

    def request(self, **kwargs) -> HttpResponse:
        self.calls += 1
        self.last_headers = kwargs["headers"]
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _params() -> StellarSearchParams:
    now = datetime.now(timezone.utc)
    context = CorrelationContext(
        run_id="20260605_http",
        scenario_id="dns_tunnel",
        time_window_start=now,
        time_window_end=now,
        source_ip="10.10.10.5",
        destination_ip="10.10.10.53",
        s2_decision="success",
    )
    return StellarSearchParams(
        context=context,
        detection_model_id="stellar.dns_tunnel",
        alert_families=["DNS Tunnel"],
    )


def test_config_loading_success():
    config = load_stellar_config_from_env(
        {
            ENV_BASE_URL: "https://stellar.example",
            ENV_API_TOKEN: "secret-token",
            "DSP_STELLAR_VERIFY_TLS": "false",
            "DSP_STELLAR_TIMEOUT_SECONDS": "12",
        }
    )
    assert config.base_url == "https://stellar.example"
    assert config.api_token == "secret-token"
    assert config.verify_tls is False
    assert config.timeout_seconds == 12.0
    assert config.redacted_dict()["api_token"] == "***REDACTED***"


def test_missing_config_raises():
    with pytest.raises(StellarConfigError):
        load_stellar_config_from_env({ENV_BASE_URL: "https://stellar.example"})


def test_http_client_missing_config_returns_error_result():
    client = StellarHttpClient(environ={})
    result = client.search_alerts(_params())
    assert result.error is not None
    assert isinstance(result.error, StellarConfigError)


def test_http_200_response_parsed():
    body = json.dumps(
        {
            "items": [
                {
                    "id": "alert-1",
                    "name": "DNS Tunnel",
                    "severity": "high",
                    "observed_at": "2026-06-05T12:00:00Z",
                    "entity_refs": ["10.10.10.5"],
                    "detection_model_id": "stellar.dns_tunnel",
                }
            ]
        }
    ).encode()
    transport = MockTransport([HttpResponse(status_code=200, body=body, headers={})])
    client = StellarHttpClient(
        transport=transport,
        environ={
            ENV_BASE_URL: "https://stellar.example",
            ENV_API_TOKEN: "secret-token",
        },
    )

    result = client.search_alerts(_params())
    assert result.ok
    assert len(result.items) == 1
    assert result.items[0]["name"] == "DNS Tunnel"


def test_http_401_handling():
    transport = MockTransport(
        [HttpResponse(status_code=401, body=b'{"error":"unauthorized"}', headers={})]
    )
    client = StellarHttpClient(
        transport=transport,
        environ={
            ENV_BASE_URL: "https://stellar.example",
            ENV_API_TOKEN: "secret-token",
        },
    )
    result = client.search_alerts(_params())
    assert isinstance(result.error, StellarAuthError)


def test_http_500_handling():
    transport = MockTransport(
        [
            HttpResponse(status_code=500, body=b"server error", headers={}),
            HttpResponse(status_code=500, body=b"server error", headers={}),
            HttpResponse(status_code=500, body=b"server error", headers={}),
        ]
    )
    client = StellarHttpClient(
        transport=transport,
        environ={
            ENV_BASE_URL: "https://stellar.example",
            ENV_API_TOKEN: "secret-token",
        },
    )
    result = client.search_analytics(_params())
    assert isinstance(result.error, StellarHttpError)
    assert result.http_status == 500
    assert transport.calls == 3


def test_timeout_handling():
    transport = MockTransport(
        [
            StellarTimeoutError("request timeout after 1s"),
            StellarTimeoutError("request timeout after 1s"),
            StellarTimeoutError("request timeout after 1s"),
        ]
    )
    client = StellarHttpClient(
        transport=transport,
        environ={
            ENV_BASE_URL: "https://stellar.example",
            ENV_API_TOKEN: "secret-token",
            "DSP_STELLAR_TIMEOUT_SECONDS": "1",
        },
    )
    result = client.search_entities(_params())
    assert isinstance(result.error, StellarTimeoutError)


def test_invalid_json_handling():
    transport = MockTransport([HttpResponse(status_code=200, body=b"not-json", headers={})])
    client = StellarHttpClient(
        transport=transport,
        environ={
            ENV_BASE_URL: "https://stellar.example",
            ENV_API_TOKEN: "secret-token",
        },
    )
    result = client.search_timeline(_params())
    assert isinstance(result.error, StellarParseError)


def test_token_not_in_transport_headers_in_saved_output(tmp_path):
    body = json.dumps(
        {
            "items": [
                {
                    "id": "alert-1",
                    "name": "DNS Tunnel",
                    "api_token": "leaked",
                    "observed_at": "2026-06-05T12:00:00Z",
                }
            ]
        }
    ).encode()
    transport = MockTransport([HttpResponse(status_code=200, body=body, headers={})] * 4)
    client = StellarHttpClient(
        transport=transport,
        environ={
            ENV_BASE_URL: "https://stellar.example",
            ENV_API_TOKEN: "secret-token",
        },
    )
    from dsp.detection.providers.stellar.stellar_adapter import StellarAdapter

    adapter = StellarAdapter(client=client, client_mode="http")
    context = _params().context
    evidence = adapter.collect_evidence(context)
    result = adapter.validate_detection(context, evidence)
    vendor_dir = adapter.build_evidence_pack(context, evidence, result, tmp_path)

    raw_alerts = json.loads((vendor_dir / "raw" / "alert.json").read_text())
    assert raw_alerts[0]["api_token"] == "***REDACTED***"

    evidence_md = (vendor_dir / "evidence.md").read_text()
    assert "secret-token" not in evidence_md

    s3_json = (vendor_dir / "s3_result.json").read_text()
    assert "secret-token" not in s3_json
