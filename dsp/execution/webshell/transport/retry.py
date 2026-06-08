"""Retry policy model for webshell HTTP transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RetryPolicy:
    """Declarative retry policy — no framework integration."""

    max_retries: int = 2
    backoff_seconds: float = 1.0
    retry_on_timeout: bool = True
    retry_on_http_5xx: bool = True
    retry_on_http_429: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_retries": self.max_retries,
            "backoff_seconds": self.backoff_seconds,
            "retry_on_timeout": self.retry_on_timeout,
            "retry_on_http_5xx": self.retry_on_http_5xx,
            "retry_on_http_429": self.retry_on_http_429,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetryPolicy:
        return cls(
            max_retries=int(data.get("max_retries", 2)),
            backoff_seconds=float(data.get("backoff_seconds", 1.0)),
            retry_on_timeout=bool(data.get("retry_on_timeout", True)),
            retry_on_http_5xx=bool(data.get("retry_on_http_5xx", True)),
            retry_on_http_429=bool(data.get("retry_on_http_429", True)),
        )

    def should_retry(
        self,
        *,
        attempt: int,
        status_code: int | None = None,
        timed_out: bool = False,
    ) -> bool:
        """Return True when another attempt is permitted."""
        if attempt >= self.max_retries:
            return False
        if timed_out:
            return self.retry_on_timeout
        if status_code is None:
            return False
        if status_code == 429:
            return self.retry_on_http_429
        if 500 <= status_code <= 599:
            return self.retry_on_http_5xx
        return False
