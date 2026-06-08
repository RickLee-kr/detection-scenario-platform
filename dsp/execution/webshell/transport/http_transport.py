"""Mock HTTP transport for unit tests — no network I/O."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from dsp.execution.webshell.transport.base import WebshellTransport
from dsp.execution.webshell.transport.errors import (
    WebshellTransportTimeoutError,
)
from dsp.execution.webshell.transport.models import TransportRequest, TransportResponse


class MockTransportMode(str, Enum):
    """Deterministic mock response modes for unit tests."""

    SUCCESS = "success"
    TIMEOUT = "timeout"
    HTTP_5XX = "http_5xx"
    HTTP_429 = "http_429"
    AUTH_FAILURE = "auth_failure"


@dataclass
class MockHttpTransport(WebshellTransport):
    """Deterministic HTTP transport stub — tests only, no network calls."""

    mode: MockTransportMode = MockTransportMode.SUCCESS
    status_code: int = 200
    body: bytes = b"ok"
    headers: dict[str, str] = field(default_factory=lambda: {"content-type": "text/plain"})
    duration_ms: float = 1.0
    calls: list[dict[str, object]] = field(default_factory=list)

    def send_get(self, request: TransportRequest) -> TransportResponse:
        return self._dispatch(request, operation="send_get")

    def send_post(self, request: TransportRequest) -> TransportResponse:
        return self._dispatch(request, operation="send_post")

    def send_upload(
        self,
        request: TransportRequest,
        *,
        local_path: Path,
        remote_path: str,
    ) -> TransportResponse:
        return self._dispatch(
            request,
            operation="send_upload",
            local_path=str(local_path),
            remote_path=remote_path,
        )

    def download(
        self,
        request: TransportRequest,
        *,
        remote_path: str,
    ) -> TransportResponse:
        return self._dispatch(
            request,
            operation="download",
            remote_path=remote_path,
        )

    def healthcheck(self, request: TransportRequest) -> TransportResponse:
        return self._dispatch(request, operation="healthcheck")

    def _dispatch(
        self,
        request: TransportRequest,
        *,
        operation: str,
        **extra: object,
    ) -> TransportResponse:
        self.calls.append(
            {
                "operation": operation,
                "request": request,
                **extra,
            }
        )
        if self.mode is MockTransportMode.TIMEOUT:
            raise WebshellTransportTimeoutError(
                f"mock timeout for {request.url}",
                url=request.url,
                timeout_seconds=request.timeout_seconds,
            )
        status_code, body, success = self._resolve_response()
        time.sleep(0)
        return TransportResponse(
            status_code=status_code,
            headers=dict(self.headers),
            body=body,
            duration_ms=self.duration_ms,
            success=success,
            metadata={"mode": self.mode.value, "operation": operation},
        )

    def _resolve_response(self) -> tuple[int, bytes, bool]:
        if self.mode is MockTransportMode.HTTP_5XX:
            return 503, b"service unavailable", False
        if self.mode is MockTransportMode.HTTP_429:
            return 429, b"rate limited", False
        if self.mode is MockTransportMode.AUTH_FAILURE:
            return 401, b"unauthorized", False
        return self.status_code, self.body, 200 <= self.status_code < 300
