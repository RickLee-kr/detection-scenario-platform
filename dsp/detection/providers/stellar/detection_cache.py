"""Per-run detection query cache — avoids duplicate Stellar API calls."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from dsp.detection.providers.stellar.client_base import StellarSearchParams, StellarSearchResult


@dataclass(frozen=True)
class DetectionCacheKey:
    """Cache identity for a single evidence query within one run."""

    scenario_id: str
    run_id: str
    provider: str
    evidence_type: str
    window_start: str
    window_end: str
    query_fingerprint: str

    def as_string(self) -> str:
        return "|".join(
            [
                self.scenario_id,
                self.run_id,
                self.provider,
                self.evidence_type,
                self.window_start,
                self.window_end,
                self.query_fingerprint,
            ]
        )


def _iso_window(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _query_fingerprint(params: StellarSearchParams) -> str:
    payload: dict[str, Any] = {
        "api_path": params.api_path,
        "http_method": params.http_method,
        "query": params.query,
        "detection_model_id": params.detection_model_id,
        "category": params.category,
        "alert_families": params.alert_families,
        "analytics_types": params.analytics_types,
        "entity_types": params.entity_types,
        "protocol": params.protocol,
        "port": params.port,
    }
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def build_cache_key(
    *,
    provider: str,
    evidence_type: str,
    params: StellarSearchParams,
) -> DetectionCacheKey:
    context = params.context
    return DetectionCacheKey(
        scenario_id=context.scenario_id,
        run_id=context.run_id,
        provider=provider,
        evidence_type=evidence_type,
        window_start=_iso_window(context.time_window_start),
        window_end=_iso_window(context.time_window_end),
        query_fingerprint=_query_fingerprint(params),
    )


class DetectionQueryCache:
    """Single-run cache for identical Stellar evidence queries."""

    def __init__(self) -> None:
        self._entries: dict[str, StellarSearchResult] = {}

    def clear(self) -> None:
        self._entries.clear()

    def get(self, key: DetectionCacheKey) -> StellarSearchResult | None:
        cached = self._entries.get(key.as_string())
        if cached is None:
            return None
        return StellarSearchResult(
            items=list(cached.items),
            error=cached.error,
            http_status=cached.http_status,
            page_count=cached.page_count,
            total_fetched=cached.total_fetched,
            execution_time_ms=cached.execution_time_ms,
            from_cache=True,
        )

    def put(self, key: DetectionCacheKey, result: StellarSearchResult) -> None:
        self._entries[key.as_string()] = StellarSearchResult(
            items=list(result.items),
            error=result.error,
            http_status=result.http_status,
            page_count=result.page_count,
            total_fetched=result.total_fetched,
            execution_time_ms=result.execution_time_ms,
            from_cache=False,
        )
