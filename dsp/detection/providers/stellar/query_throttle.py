"""Query throttling — prevents accidental Stellar API flooding."""

from __future__ import annotations

import time
from dataclasses import dataclass

from dsp.detection.providers.stellar.client_base import StellarRateLimitError


@dataclass
class QueryThrottleConfig:
    """Throttling knobs for a single detection run."""

    request_delay_seconds: float = 0.0
    max_requests_per_run: int = 200
    retry_backoff_seconds: float = 0.05
    max_retries: int = 2


class QueryThrottle:
    """Per-run request budget and inter-request delay."""

    def __init__(self, config: QueryThrottleConfig | None = None) -> None:
        self._config = config or QueryThrottleConfig()
        self._request_count = 0
        self._last_request_at: float | None = None

    @property
    def request_count(self) -> int:
        return self._request_count

    @property
    def config(self) -> QueryThrottleConfig:
        return self._config

    def reset(self) -> None:
        self._request_count = 0
        self._last_request_at = None

    def before_request(self) -> None:
        """Apply delay and enforce max request budget."""
        if self._request_count >= self._config.max_requests_per_run:
            raise StellarRateLimitError(
                f"max request limit reached ({self._config.max_requests_per_run})"
            )

        delay = self._config.request_delay_seconds
        if delay > 0 and self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            remaining = delay - elapsed
            if remaining > 0:
                time.sleep(remaining)

        self._request_count += 1
        self._last_request_at = time.monotonic()

    def retry_sleep(self, attempt: int) -> None:
        """Backoff sleep between retry attempts."""
        backoff = self._config.retry_backoff_seconds * (attempt + 1)
        if backoff > 0:
            time.sleep(backoff)
