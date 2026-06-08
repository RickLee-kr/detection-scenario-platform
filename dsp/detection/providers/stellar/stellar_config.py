"""Stellar HTTP client configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dsp.detection.providers.stellar.client_base import StellarConfigError
from dsp.detection.providers.stellar.evidence_limits import EvidenceLimitConfig
from dsp.detection.providers.stellar.query_throttle import QueryThrottleConfig

ENV_BASE_URL = "DSP_STELLAR_BASE_URL"
ENV_API_TOKEN = "DSP_STELLAR_API_TOKEN"
ENV_VERIFY_TLS = "DSP_STELLAR_VERIFY_TLS"
ENV_TIMEOUT_SECONDS = "DSP_STELLAR_TIMEOUT_SECONDS"
ENV_PAGE_SIZE = "DSP_STELLAR_PAGE_SIZE"
ENV_REQUEST_DELAY_SECONDS = "DSP_STELLAR_REQUEST_DELAY_SECONDS"
ENV_MAX_REQUESTS_PER_RUN = "DSP_STELLAR_MAX_REQUESTS_PER_RUN"
ENV_MAX_RETRIES = "DSP_STELLAR_MAX_RETRIES"
ENV_RETRY_BACKOFF_SECONDS = "DSP_STELLAR_RETRY_BACKOFF_SECONDS"
ENV_MAX_ALERTS = "DSP_STELLAR_MAX_ALERTS"
ENV_MAX_ANALYTICS = "DSP_STELLAR_MAX_ANALYTICS"
ENV_MAX_ENTITIES = "DSP_STELLAR_MAX_ENTITIES"
ENV_MAX_TIMELINE = "DSP_STELLAR_MAX_TIMELINE"

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_PAGE_SIZE = 100
DEFAULT_REQUEST_DELAY_SECONDS = 0.0
DEFAULT_MAX_REQUESTS_PER_RUN = 200
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 0.05
DEFAULT_MAX_ALERTS = 500
DEFAULT_MAX_ANALYTICS = 500
DEFAULT_MAX_ENTITIES = 500
DEFAULT_MAX_TIMELINE = 1000


@dataclass(frozen=True)
class StellarConfig:
    base_url: str
    api_token: str
    verify_tls: bool = True
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    page_size: int = DEFAULT_PAGE_SIZE
    throttle: QueryThrottleConfig | None = None
    evidence_limits: EvidenceLimitConfig | None = None

    def __post_init__(self) -> None:
        if self.throttle is None:
            object.__setattr__(
                self,
                "throttle",
                QueryThrottleConfig(
                    request_delay_seconds=DEFAULT_REQUEST_DELAY_SECONDS,
                    max_requests_per_run=DEFAULT_MAX_REQUESTS_PER_RUN,
                    retry_backoff_seconds=DEFAULT_RETRY_BACKOFF_SECONDS,
                    max_retries=DEFAULT_MAX_RETRIES,
                ),
            )
        if self.evidence_limits is None:
            object.__setattr__(
                self,
                "evidence_limits",
                EvidenceLimitConfig(
                    max_alerts=DEFAULT_MAX_ALERTS,
                    max_analytics=DEFAULT_MAX_ANALYTICS,
                    max_entities=DEFAULT_MAX_ENTITIES,
                    max_timeline=DEFAULT_MAX_TIMELINE,
                ),
            )

    def redacted_dict(self) -> dict[str, str | float | bool | int]:
        """Safe config snapshot — never includes the API token."""
        throttle = self.throttle or QueryThrottleConfig()
        limits = self.evidence_limits or EvidenceLimitConfig()
        return {
            "base_url": self.base_url,
            "api_token": "***REDACTED***",
            "verify_tls": self.verify_tls,
            "timeout_seconds": self.timeout_seconds,
            "page_size": self.page_size,
            "request_delay_seconds": throttle.request_delay_seconds,
            "max_requests_per_run": throttle.max_requests_per_run,
            "max_retries": throttle.max_retries,
            "retry_backoff_seconds": throttle.retry_backoff_seconds,
            "max_alerts": limits.max_alerts,
            "max_analytics": limits.max_analytics,
            "max_entities": limits.max_entities,
            "max_timeline": limits.max_timeline,
        }


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_float(value: str | None, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise StellarConfigError(f"invalid float value: {value}") from exc


def _parse_int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise StellarConfigError(f"invalid integer value: {value}") from exc
    if parsed < 0:
        raise StellarConfigError(f"integer value must be non-negative: {value}")
    return parsed


def load_stellar_config_from_env(
    environ: dict[str, str] | None = None,
) -> StellarConfig:
    """Load Stellar HTTP config from environment. Raises StellarConfigError if required vars missing."""
    env = environ if environ is not None else os.environ

    base_url = env.get(ENV_BASE_URL, "").strip()
    api_token = env.get(ENV_API_TOKEN, "").strip()

    if not base_url:
        raise StellarConfigError(f"missing required environment variable: {ENV_BASE_URL}")
    if not api_token:
        raise StellarConfigError(f"missing required environment variable: {ENV_API_TOKEN}")

    throttle = QueryThrottleConfig(
        request_delay_seconds=_parse_float(
            env.get(ENV_REQUEST_DELAY_SECONDS),
            DEFAULT_REQUEST_DELAY_SECONDS,
        ),
        max_requests_per_run=_parse_int(
            env.get(ENV_MAX_REQUESTS_PER_RUN),
            DEFAULT_MAX_REQUESTS_PER_RUN,
        ),
        retry_backoff_seconds=_parse_float(
            env.get(ENV_RETRY_BACKOFF_SECONDS),
            DEFAULT_RETRY_BACKOFF_SECONDS,
        ),
        max_retries=_parse_int(env.get(ENV_MAX_RETRIES), DEFAULT_MAX_RETRIES),
    )
    evidence_limits = EvidenceLimitConfig(
        max_alerts=_parse_int(env.get(ENV_MAX_ALERTS), DEFAULT_MAX_ALERTS),
        max_analytics=_parse_int(env.get(ENV_MAX_ANALYTICS), DEFAULT_MAX_ANALYTICS),
        max_entities=_parse_int(env.get(ENV_MAX_ENTITIES), DEFAULT_MAX_ENTITIES),
        max_timeline=_parse_int(env.get(ENV_MAX_TIMELINE), DEFAULT_MAX_TIMELINE),
    )

    return StellarConfig(
        base_url=base_url,
        api_token=api_token,
        verify_tls=_parse_bool(env.get(ENV_VERIFY_TLS), True),
        timeout_seconds=_parse_float(env.get(ENV_TIMEOUT_SECONDS), DEFAULT_TIMEOUT_SECONDS),
        page_size=_parse_int(env.get(ENV_PAGE_SIZE), DEFAULT_PAGE_SIZE),
        throttle=throttle,
        evidence_limits=evidence_limits,
    )
