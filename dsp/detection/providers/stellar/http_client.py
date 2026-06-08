"""Stellar HTTP client — real API integration with retry and safe error handling."""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from dsp.detection.providers.stellar.client_base import (
    StellarAuthError,
    StellarClient,
    StellarClientError,
    StellarConfigError,
    StellarHttpError,
    StellarParseError,
    StellarRateLimitError,
    StellarSearchParams,
    StellarSearchResult,
    StellarTimeoutError,
)
from dsp.detection.providers.stellar.query_throttle import QueryThrottle, QueryThrottleConfig
from dsp.detection.providers.stellar.stellar_config import StellarConfig, load_stellar_config_from_env

RETRYABLE_STATUS_CODES = frozenset({500, 502, 503, 504})

DEFAULT_ENDPOINTS = {
    "alert": "/api/v1/detection/alerts",
    "alerts": "/api/v1/detection/alerts",
    "analytics": "/api/v1/detection/analytics",
    "entity": "/api/v1/detection/entities",
    "entities": "/api/v1/detection/entities",
    "timeline": "/api/v1/detection/timeline",
}


@dataclass
class HttpResponse:
    status_code: int
    body: bytes
    headers: dict[str, str]


class HttpTransport(Protocol):
    """Injectable HTTP transport for tests."""

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: float,
        verify_tls: bool,
    ) -> HttpResponse: ...


class UrllibHttpTransport:
    """Default stdlib HTTP transport."""

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: float,
        verify_tls: bool,
    ) -> HttpResponse:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        context = None if verify_tls else ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds, context=context) as resp:
                raw_headers = {k.lower(): v for k, v in resp.headers.items()}
                return HttpResponse(
                    status_code=resp.status,
                    body=resp.read(),
                    headers=raw_headers,
                )
        except urllib.error.HTTPError as exc:
            return HttpResponse(
                status_code=exc.code,
                body=exc.read(),
                headers={k.lower(): v for k, v in exc.headers.items()},
            )
        except TimeoutError as exc:
            raise StellarTimeoutError(f"request timeout after {timeout_seconds}s") from exc
        except urllib.error.URLError as exc:
            if "timed out" in str(exc.reason).lower():
                raise StellarTimeoutError(f"request timeout: {exc.reason}") from exc
            raise StellarHttpError(f"transport error: {exc.reason}") from exc


class StellarHttpClient(StellarClient):
    """Real Stellar HTTP client — requires DSP_STELLAR_* environment variables."""

    def __init__(
        self,
        config: StellarConfig | None = None,
        *,
        transport: HttpTransport | None = None,
        environ: dict[str, str] | None = None,
        throttle: QueryThrottle | None = None,
    ) -> None:
        self._config = config
        self._environ = environ
        self._transport = transport or UrllibHttpTransport()
        self._config_error: StellarConfigError | None = None
        if self._config is None:
            try:
                self._config = load_stellar_config_from_env(environ)
            except StellarConfigError as exc:
                self._config_error = exc
        self._throttle = throttle or QueryThrottle(
            self._config.throttle if self._config is not None else QueryThrottleConfig()
        )

    @property
    def config(self) -> StellarConfig | None:
        return self._config

    @property
    def throttle(self) -> QueryThrottle:
        return self._throttle

    def reset_run_state(self) -> None:
        """Reset per-run throttle budget before a new evidence collection."""
        self._throttle.reset()

    def search_alerts(self, params: StellarSearchParams) -> StellarSearchResult:
        return self._search(params, default_path=DEFAULT_ENDPOINTS["alerts"])

    def search_analytics(self, params: StellarSearchParams) -> StellarSearchResult:
        return self._search(params, default_path=DEFAULT_ENDPOINTS["analytics"])

    def search_entities(self, params: StellarSearchParams) -> StellarSearchResult:
        return self._search(params, default_path=DEFAULT_ENDPOINTS["entities"])

    def search_timeline(self, params: StellarSearchParams) -> StellarSearchResult:
        return self._search(params, default_path=DEFAULT_ENDPOINTS["timeline"])

    def _search(self, params: StellarSearchParams, *, default_path: str) -> StellarSearchResult:
        if self._config_error is not None:
            return StellarSearchResult(error=self._config_error)
        assert self._config is not None

        started = time.perf_counter()
        path = params.api_path or default_path
        method = (params.http_method or "GET").upper()
        base_payload = self._build_query_payload(params)
        throttle_config = self._config.throttle or QueryThrottleConfig()
        max_retries = throttle_config.max_retries

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._config.api_token}",
        }
        if method == "POST":
            headers["Content-Type"] = "application/json"

        aggregated_items: list[dict[str, Any]] = []
        page_count = 0
        last_status: int | None = None
        page_token: str | None = None

        while True:
            page_count += 1
            page_payload = dict(base_payload)
            page_payload["page_size"] = self._config.page_size
            if page_token:
                page_payload["page_token"] = page_token

            url, body = self._prepare_request(path, method, page_payload)
            last_error: StellarClientError | None = None
            page_result: StellarSearchResult | None = None

            for attempt in range(max_retries + 1):
                try:
                    self._throttle.before_request()
                    response = self._transport.request(
                        method=method,
                        url=url,
                        headers=headers,
                        body=body,
                        timeout_seconds=self._config.timeout_seconds,
                        verify_tls=self._config.verify_tls,
                    )
                    page_result = self._parse_response(response)
                    last_status = page_result.http_status
                    if (
                        page_result.error
                        and isinstance(page_result.error, StellarHttpError)
                        and page_result.http_status in RETRYABLE_STATUS_CODES
                        and attempt < max_retries
                    ):
                        last_error = page_result.error
                        self._throttle.retry_sleep(attempt)
                        continue
                    break
                except StellarRateLimitError as exc:
                    return self._partial_result(
                        aggregated_items,
                        error=exc,
                        http_status=last_status,
                        page_count=page_count,
                        started=started,
                    )
                except StellarTimeoutError as exc:
                    last_error = exc
                    if attempt < max_retries:
                        self._throttle.retry_sleep(attempt)
                        continue
                    return self._partial_result(
                        aggregated_items,
                        error=exc,
                        http_status=last_status,
                        page_count=page_count,
                        started=started,
                    )
                except StellarClientError as exc:
                    return self._partial_result(
                        aggregated_items,
                        error=exc,
                        http_status=last_status,
                        page_count=page_count,
                        started=started,
                    )

            if page_result is None:
                return self._partial_result(
                    aggregated_items,
                    error=last_error or StellarHttpError("unknown request failure"),
                    http_status=last_status,
                    page_count=page_count,
                    started=started,
                )

            if page_result.error is not None:
                return self._partial_result(
                    aggregated_items,
                    error=page_result.error,
                    http_status=page_result.http_status,
                    page_count=page_count,
                    started=started,
                )

            aggregated_items.extend(page_result.items)
            next_token = page_result.next_page_token
            if not next_token:
                break
            page_token = next_token

        elapsed_ms = (time.perf_counter() - started) * 1000
        return StellarSearchResult(
            items=aggregated_items,
            http_status=last_status,
            page_count=page_count,
            total_fetched=len(aggregated_items),
            execution_time_ms=elapsed_ms,
        )

    @staticmethod
    def _partial_result(
        aggregated_items: list[dict[str, Any]],
        *,
        error: StellarClientError,
        http_status: int | None,
        page_count: int,
        started: float,
    ) -> StellarSearchResult:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return StellarSearchResult(
            items=list(aggregated_items),
            error=error,
            http_status=http_status,
            page_count=page_count,
            total_fetched=len(aggregated_items),
            execution_time_ms=elapsed_ms,
        )

    def _build_query_payload(self, params: StellarSearchParams) -> dict[str, Any]:
        if params.query:
            return dict(params.query)

        return {
            "run_id": params.context.run_id,
            "scenario_id": params.context.scenario_id,
            "start": params.context.time_window_start.isoformat().replace("+00:00", "Z"),
            "end": params.context.time_window_end.isoformat().replace("+00:00", "Z"),
            "detection_model_id": params.detection_model_id or "",
            "category": params.category or "",
            "source_ip": params.context.source_ip or "",
            "destination_ip": params.context.destination_ip or "",
        }

    def _prepare_request(
        self,
        path: str,
        method: str,
        payload: dict[str, Any],
    ) -> tuple[str, bytes | None]:
        base = f"{self._config.base_url.rstrip('/')}{path}"  # type: ignore[union-attr]

        if method == "POST":
            return base, json.dumps(payload).encode("utf-8")

        flat_params = self._flatten_params(payload)
        query = urllib.parse.urlencode(flat_params, doseq=True)
        return f"{base}?{query}", None

    @staticmethod
    def _flatten_params(payload: dict[str, Any]) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for key, value in payload.items():
            if value in (None, ""):
                continue
            if isinstance(value, list):
                for item in value:
                    if item not in (None, ""):
                        pairs.append((key, str(item)))
            else:
                pairs.append((key, str(value)))
        return pairs

    def _parse_response(self, response: HttpResponse) -> StellarSearchResult:
        status = response.status_code

        if status in {401, 403}:
            return StellarSearchResult(
                error=StellarAuthError(f"authentication failed: HTTP {status}"),
                http_status=status,
            )
        if status >= 500 or status in RETRYABLE_STATUS_CODES:
            return StellarSearchResult(
                error=StellarHttpError(f"server error: HTTP {status}", status_code=status),
                http_status=status,
            )
        if status >= 400:
            return StellarSearchResult(
                error=StellarHttpError(f"client error: HTTP {status}", status_code=status),
                http_status=status,
            )

        if not response.body:
            return StellarSearchResult(items=[], http_status=status)

        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return StellarSearchResult(
                error=StellarParseError(f"invalid JSON response: {exc}"),
                http_status=status,
            )

        items = payload.get("items", [])
        if not isinstance(items, list):
            return StellarSearchResult(
                error=StellarParseError("response.items must be a list"),
                http_status=status,
            )

        normalized_items = [item for item in items if isinstance(item, dict)]
        return StellarSearchResult(
            items=normalized_items,
            http_status=status,
            next_page_token=_extract_next_page_token(payload),
        )


def _extract_next_page_token(payload: dict[str, Any]) -> str | None:
    for key in ("next_page_token", "nextPageToken", "page_token", "cursor"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    pagination = payload.get("pagination")
    if isinstance(pagination, dict):
        for key in ("next_page_token", "nextPageToken", "page_token", "cursor"):
            value = pagination.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None
