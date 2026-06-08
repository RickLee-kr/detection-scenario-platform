"""Real HTTP transport for webshell providers — stdlib network I/O only."""

from __future__ import annotations

import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from dsp.execution.webshell.transport.base import WebshellTransport
from dsp.execution.webshell.transport.errors import (
    WebshellTransportError,
    WebshellTransportRetryExhaustedError,
    WebshellTransportTimeoutError,
)
from dsp.execution.webshell.transport.models import TransportRequest, TransportResponse
from dsp.execution.webshell.transport.retry import RetryPolicy


@dataclass
class HttpBackendResponse:
    """Normalized HTTP response from an injectable backend."""

    status_code: int
    headers: dict[str, str]
    body: bytes


class HttpBackend(Protocol):
    """Injectable HTTP backend for RealHttpTransport tests and production."""

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> HttpBackendResponse: ...


@dataclass
class UrllibHttpBackend:
    """Default stdlib HTTP backend — no third-party dependencies."""

    verify_tls: bool = True

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> HttpBackendResponse:
        req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
        context = None if self.verify_tls else ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(
                req,
                timeout=timeout_seconds,
                context=context,
            ) as resp:
                return HttpBackendResponse(
                    status_code=resp.status,
                    headers=_normalize_headers(resp.headers.items()),
                    body=resp.read(),
                )
        except urllib.error.HTTPError as exc:
            return HttpBackendResponse(
                status_code=exc.code,
                headers=_normalize_headers(exc.headers.items()) if exc.headers else {},
                body=exc.read(),
            )
        except TimeoutError as exc:
            raise WebshellTransportTimeoutError(
                f"request timeout after {timeout_seconds}s",
                url=url,
                timeout_seconds=timeout_seconds,
            ) from exc
        except urllib.error.URLError as exc:
            reason = str(exc.reason)
            if "timed out" in reason.lower():
                raise WebshellTransportTimeoutError(
                    f"request timeout: {reason}",
                    url=url,
                    timeout_seconds=timeout_seconds,
                ) from exc
            raise WebshellTransportError(f"transport error: {reason}") from exc


@dataclass
class RealHttpTransport(WebshellTransport):
    """Production HTTP transport — GET/POST/upload/download with retry and timeout."""

    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    verify_tls: bool = True
    backend: HttpBackend | None = None

    def __post_init__(self) -> None:
        if self.backend is None:
            self.backend = UrllibHttpBackend(verify_tls=self.verify_tls)

    def send_get(self, request: TransportRequest) -> TransportResponse:
        url = _build_url(request.url, request.params)
        headers = _merge_headers(request.headers, request.cookies)
        return self._dispatch(
            request,
            operation="send_get",
            method="GET",
            url=url,
            headers=headers,
            body=_encode_body(request.body),
        )

    def send_post(self, request: TransportRequest) -> TransportResponse:
        headers = _merge_headers(request.headers, request.cookies)
        return self._dispatch(
            request,
            operation="send_post",
            method="POST",
            url=request.url,
            headers=headers,
            body=_encode_body(request.body),
        )

    def send_upload(
        self,
        request: TransportRequest,
        *,
        local_path: Path,
        remote_path: str,
    ) -> TransportResponse:
        body, content_type = _build_multipart_body(local_path, remote_path)
        headers = _merge_headers(request.headers, request.cookies)
        headers["Content-Type"] = content_type
        return self._dispatch(
            request,
            operation="send_upload",
            method="POST",
            url=request.url,
            headers=headers,
            body=body,
            extra_metadata={"remote_path": remote_path, "local_path": str(local_path)},
        )

    def download(
        self,
        request: TransportRequest,
        *,
        remote_path: str,
    ) -> TransportResponse:
        params = dict(request.params)
        params["remote_path"] = remote_path
        url = _build_url(request.url, params)
        headers = _merge_headers(request.headers, request.cookies)
        return self._dispatch(
            request,
            operation="download",
            method="GET",
            url=url,
            headers=headers,
            body=None,
            extra_metadata={"remote_path": remote_path},
        )

    def healthcheck(self, request: TransportRequest) -> TransportResponse:
        return self.send_get(request)

    def _dispatch(
        self,
        request: TransportRequest,
        *,
        operation: str,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        extra_metadata: dict[str, object] | None = None,
    ) -> TransportResponse:
        backend = self.backend
        if backend is None:
            raise WebshellTransportError("HTTP backend is not configured")

        policy = self.retry_policy
        attempt = 0

        while True:
            started = time.perf_counter()
            try:
                raw = backend.request(
                    method=method,
                    url=url,
                    headers=headers,
                    body=body,
                    timeout_seconds=request.timeout_seconds,
                )
            except WebshellTransportTimeoutError as exc:
                if policy.should_retry(attempt=attempt, timed_out=True):
                    attempt += 1
                    _backoff(policy.backoff_seconds)
                    continue
                raise exc
            except WebshellTransportError:
                raise

            duration_ms = (time.perf_counter() - started) * 1000.0
            success = 200 <= raw.status_code < 300
            metadata: dict[str, object] = {
                "operation": operation,
                "attempt": attempt,
            }
            if extra_metadata:
                metadata.update(extra_metadata)

            if policy.should_retry(attempt=attempt, status_code=raw.status_code):
                attempt += 1
                _backoff(policy.backoff_seconds)
                continue

            if (
                not success
                and attempt >= policy.max_retries
                and _is_retryable_status(raw.status_code, policy)
            ):
                raise WebshellTransportRetryExhaustedError(
                    f"{operation} failed after {attempt + 1} attempts",
                    url=url,
                    attempts=attempt + 1,
                    last_status_code=raw.status_code,
                )

            return TransportResponse(
                status_code=raw.status_code,
                headers=dict(raw.headers),
                body=raw.body,
                duration_ms=duration_ms,
                success=success,
                metadata=metadata,
            )


def _is_retryable_status(status_code: int, policy: RetryPolicy) -> bool:
    if status_code == 429:
        return policy.retry_on_http_429
    if 500 <= status_code <= 599:
        return policy.retry_on_http_5xx
    return False


def _backoff(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _build_url(base_url: str, params: dict[str, str]) -> str:
    if not params:
        return base_url
    query = urllib.parse.urlencode(params)
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{query}"


def _merge_headers(
    headers: dict[str, str],
    cookies: dict[str, str],
) -> dict[str, str]:
    merged = {key: value for key, value in headers.items()}
    if cookies:
        merged["Cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())
    return merged


def _encode_body(body: bytes | str | None) -> bytes | None:
    if body is None:
        return None
    if isinstance(body, bytes):
        return body
    return body.encode("utf-8")


def _normalize_headers(items: object) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in items}


def _build_multipart_body(local_path: Path, remote_path: str) -> tuple[bytes, str]:
    boundary = f"dsp-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        chunks.append(value.encode())
        chunks.append(b"\r\n")

    add_field("remote_path", remote_path)
    file_bytes = local_path.read_bytes()
    chunks.append(f"--{boundary}\r\n".encode())
    chunks.append(
        (
            f'Content-Disposition: form-data; name="file"; filename="{local_path.name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
    )
    chunks.append(file_bytes)
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    content_type = f"multipart/form-data; boundary={boundary}"
    return b"".join(chunks), content_type
