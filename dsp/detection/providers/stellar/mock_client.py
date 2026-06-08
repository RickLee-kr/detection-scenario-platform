"""Mock Stellar client — deterministic local responses, no HTTP."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from dsp.detection.providers.stellar.client_base import (
    StellarClient,
    StellarSearchParams,
    StellarSearchResult,
)


class MockStellarClient(StellarClient):
    """Stub client returning deterministic evidence keyed by scenario mapping."""

    def __init__(
        self,
        *,
        simulate_detection: bool = True,
        simulate_empty: bool = False,
    ) -> None:
        self.simulate_detection = simulate_detection
        self.simulate_empty = simulate_empty

    def search_alerts(self, params: StellarSearchParams) -> StellarSearchResult:
        if self._should_return_empty(params):
            return StellarSearchResult(items=[])

        alert_name = (
            params.alert_families[0] if params.alert_families else "Generic Alert"
        )
        observed = self._midpoint(params)
        entity_refs = [
            ip
            for ip in (params.context.source_ip, params.context.destination_ip)
            if ip
        ]
        return StellarSearchResult(
            items=[
                {
                    "id": f"stellar-alert-{uuid4().hex[:8]}",
                    "name": alert_name,
                    "severity": "high",
                    "observed_at": observed.isoformat().replace("+00:00", "Z"),
                    "entity_refs": entity_refs,
                    "detection_model_id": params.detection_model_id,
                    "run_id": params.context.run_id,
                    "scenario_id": params.context.scenario_id,
                }
            ]
        )

    def search_analytics(self, params: StellarSearchParams) -> StellarSearchResult:
        if self._should_return_empty(params):
            return StellarSearchResult(items=[])

        analytic_type = (
            params.analytics_types[0] if params.analytics_types else "generic_analytic"
        )
        observed = self._midpoint(params)
        return StellarSearchResult(
            items=[
                {
                    "id": f"stellar-incident-{uuid4().hex[:8]}",
                    "analytic_type": analytic_type,
                    "observed_at": observed.isoformat().replace("+00:00", "Z"),
                    "summary": f"Mock analytics for {params.context.scenario_id}",
                    "detection_model_id": params.detection_model_id,
                    "run_id": params.context.run_id,
                    "scenario_id": params.context.scenario_id,
                }
            ]
        )

    def search_entities(self, params: StellarSearchParams) -> StellarSearchResult:
        if self.simulate_empty or not self.simulate_detection:
            return StellarSearchResult(items=[])

        items: list[dict[str, Any]] = []
        if params.context.source_ip:
            items.append(
                {
                    "id": f"entity-src-{uuid4().hex[:6]}",
                    "entity_type": "ip",
                    "entity_value": params.context.source_ip,
                    "role": "source_ip",
                    "run_id": params.context.run_id,
                    "scenario_id": params.context.scenario_id,
                }
            )
        if params.context.destination_ip:
            items.append(
                {
                    "id": f"entity-dst-{uuid4().hex[:6]}",
                    "entity_type": "ip",
                    "entity_value": params.context.destination_ip,
                    "role": "destination_ip",
                    "run_id": params.context.run_id,
                    "scenario_id": params.context.scenario_id,
                }
            )
        return StellarSearchResult(items=items)

    def search_timeline(self, params: StellarSearchParams) -> StellarSearchResult:
        if self._should_return_empty(params):
            return StellarSearchResult(items=[])

        protocol = params.correlation.get("protocol", "unknown")
        observed = self._midpoint(params)
        return StellarSearchResult(
            items=[
                {
                    "id": f"timeline-{uuid4().hex[:8]}",
                    "event_type": f"{protocol}_detection",
                    "observed_at": observed.isoformat().replace("+00:00", "Z"),
                    "description": f"Mock timeline event for {params.context.scenario_id}",
                    "run_id": params.context.run_id,
                    "scenario_id": params.context.scenario_id,
                }
            ]
        )

    def _should_return_empty(self, params: StellarSearchParams) -> bool:
        return (
            self.simulate_empty
            or not self.simulate_detection
            or params.detection_model_id is None
        )

    @staticmethod
    def _midpoint(params: StellarSearchParams) -> datetime:
        start = params.context.time_window_start
        end = params.context.time_window_end
        return start + (end - start) / 2
