"""Stellar client interface — mock and HTTP implementations share this contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from dsp.detection.models import CorrelationContext


class StellarClientError(Exception):
    """Base Stellar client error."""


class StellarConfigError(StellarClientError):
    """Missing or invalid Stellar HTTP configuration."""


class StellarAuthError(StellarClientError):
    """Authentication failure (HTTP 401/403)."""


class StellarHttpError(StellarClientError):
    """HTTP transport or server error."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class StellarTimeoutError(StellarClientError):
    """Request timeout."""


class StellarParseError(StellarClientError):
    """Invalid JSON or unexpected response shape."""


class StellarRateLimitError(StellarClientError):
    """Request budget exhausted for the current detection run."""


@dataclass
class StellarSearchParams:
    """Inputs shared by all Stellar search operations."""

    context: CorrelationContext
    detection_model_id: str | None = None
    alert_families: list[str] = field(default_factory=list)
    analytics_types: list[str] = field(default_factory=list)
    correlation: dict[str, Any] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)
    http_method: str = "GET"
    api_path: str | None = None
    evidence_type: str | None = None
    category: str | None = None
    entity_types: list[str] = field(default_factory=list)
    protocol: str | None = None
    port: int | None = None


@dataclass
class StellarSearchResult:
    """Vendor search outcome — raw items plus optional error."""

    items: list[dict[str, Any]] = field(default_factory=list)
    error: StellarClientError | None = None
    http_status: int | None = None
    page_count: int = 1
    total_fetched: int = 0
    execution_time_ms: float | None = None
    from_cache: bool = False
    next_page_token: str | None = None

    def __post_init__(self) -> None:
        if self.total_fetched == 0 and self.items:
            self.total_fetched = len(self.items)

    @property
    def ok(self) -> bool:
        return self.error is None


class StellarClient(ABC):
    """Stellar detection query interface."""

    @abstractmethod
    def search_alerts(self, params: StellarSearchParams) -> StellarSearchResult: ...

    @abstractmethod
    def search_analytics(self, params: StellarSearchParams) -> StellarSearchResult: ...

    @abstractmethod
    def search_entities(self, params: StellarSearchParams) -> StellarSearchResult: ...

    @abstractmethod
    def search_timeline(self, params: StellarSearchParams) -> StellarSearchResult: ...
