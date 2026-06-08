"""StellarClient interface contract tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dsp.detection.models import CorrelationContext
from dsp.detection.providers.stellar.client_base import (
    StellarClient,
    StellarSearchParams,
    StellarSearchResult,
)
from dsp.detection.providers.stellar.mock_client import MockStellarClient


def _params() -> StellarSearchParams:
    now = datetime.now(timezone.utc)
    context = CorrelationContext(
        run_id="20260605_iface",
        scenario_id="dns_tunnel",
        time_window_start=now,
        time_window_end=now,
        source_ip="10.10.10.5",
        destination_ip="10.10.10.53",
    )
    return StellarSearchParams(
        context=context,
        detection_model_id="stellar.dns_tunnel",
        alert_families=["DNS Tunnel"],
        analytics_types=["dns_query_volume_anomaly"],
        correlation={"protocol": "dns"},
    )


def test_stellar_client_is_abstract():
    with pytest.raises(TypeError):
        StellarClient()  # type: ignore[abstract]


def test_mock_stellar_client_implements_interface():
    client = MockStellarClient()
    assert isinstance(client, StellarClient)
    for method_name in (
        "search_alerts",
        "search_analytics",
        "search_entities",
        "search_timeline",
    ):
        assert hasattr(client, method_name)


def test_mock_search_methods_return_stellar_search_result():
    client = MockStellarClient()
    params = _params()

    for method_name in (
        "search_alerts",
        "search_analytics",
        "search_entities",
        "search_timeline",
    ):
        result = getattr(client, method_name)(params)
        assert isinstance(result, StellarSearchResult)
        assert result.ok
        assert isinstance(result.items, list)
