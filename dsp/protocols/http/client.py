"""HTTP protocol client — mock and live request transport."""

from __future__ import annotations

import socket
import ssl
import uuid
import urllib.error
import urllib.request
from typing import Any

from dsp.protocols.base import HttpProtocolError
from dsp.protocols.http.urls import PlannedHttpRequest
from dsp.protocols.types import HttpRequest, HttpResponseResult

DEFAULT_TIMEOUT_SEC = 10.0


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send_request(
    url: str,
    *,
    method: str = "GET",
    timeout: float = DEFAULT_TIMEOUT_SEC,
    verify_tls: bool = False,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    content_type: str | None = None,
) -> HttpResponseResult:
    """Send a single HTTP/HTTPS request. Redirects are not followed."""
    request_id = uuid.uuid4().hex[:8]
    evidence: dict[str, Any] = {"url": url, "method": method.upper()}

    request_headers = dict(headers) if headers else {}
    request_headers.setdefault("User-Agent", "dsp-http-followup/1.0")
    if content_type:
        request_headers.setdefault("Content-Type", content_type)
    req = urllib.request.Request(
        url,
        data=body,
        method=method.upper(),
        headers=request_headers,
    )
    context = None
    if url.lower().startswith("https://"):
        context = ssl.create_default_context()
        if not verify_tls:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

    try:
        opener = urllib.request.build_opener(_NoRedirectHandler)
        with opener.open(req, timeout=timeout, context=context) as resp:
            status_code = getattr(resp, "status", resp.getcode())
            summary = {
                "status_code": status_code,
                "reason": getattr(resp, "reason", ""),
            }
            return HttpResponseResult(
                url=url,
                method=method.upper(),
                outcome="response",
                status_code=status_code,
                response_summary=summary,
                request_id=request_id,
                dry_run=False,
                evidence={**evidence, "bytes_read": len(resp.read(1024))},
            )
    except urllib.error.HTTPError as exc:
        return HttpResponseResult(
            url=url,
            method=method.upper(),
            outcome="response",
            status_code=exc.code,
            response_summary={"status_code": exc.code, "reason": str(exc.reason)},
            request_id=request_id,
            dry_run=False,
            evidence=evidence,
        )
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, socket.timeout):
            outcome = "timeout"
        elif isinstance(reason, ConnectionRefusedError):
            outcome = "connection_refused"
        elif isinstance(reason, socket.gaierror):
            outcome = "dns_failure"
        else:
            outcome = "error"
        return HttpResponseResult(
            url=url,
            method=method.upper(),
            outcome=outcome,
            response_summary={"message": str(reason)},
            request_id=request_id,
            dry_run=False,
            evidence=evidence,
        )
    except Exception as exc:
        return HttpResponseResult(
            url=url,
            method=method.upper(),
            outcome="error",
            response_summary={"message": str(exc)},
            request_id=request_id,
            dry_run=False,
            evidence=evidence,
        )


class HttpClient:
    """HTTP protocol client with mock and live modes."""

    def __init__(
        self,
        *,
        mode: str | None = None,
        dry_run: bool = True,
        mock: bool = True,
        timeout: float = DEFAULT_TIMEOUT_SEC,
        verify_tls: bool = False,
    ) -> None:
        resolved = self._resolve_mode(mode=mode, dry_run=dry_run, mock=mock)
        if resolved not in ("mock", "live"):
            raise HttpProtocolError(f"Invalid HTTP client mode: {resolved!r}")
        self.mode = resolved
        self.dry_run = resolved == "mock"
        self.mock = resolved == "mock"
        self.timeout = timeout
        self.verify_tls = verify_tls

    @staticmethod
    def _resolve_mode(*, mode: str | None, dry_run: bool, mock: bool) -> str:
        if mode is not None:
            return mode
        return "mock" if (dry_run or mock) else "live"

    def request(
        self,
        planned: HttpRequest,
        *,
        mock_status_code: int = 200,
        mock_outcome: str | None = None,
    ) -> HttpResponseResult:
        """Execute an HTTP request in mock or live mode."""
        if self.mode == "live":
            if mock_outcome is not None:
                raise HttpProtocolError("mock_outcome is not supported in live mode")
            return send_request(
                planned.url,
                method=planned.method,
                timeout=self.timeout,
                verify_tls=self.verify_tls,
                headers=planned.headers,
                body=planned.body,
                content_type=planned.content_type,
            )
        return self._mock_request(planned, mock_status_code=mock_status_code, mock_outcome=mock_outcome)

    def _mock_request(
        self,
        planned: HttpRequest,
        *,
        mock_status_code: int = 200,
        mock_outcome: str | None = None,
    ) -> HttpResponseResult:
        request_id = uuid.uuid4().hex[:8]
        outcome = mock_outcome or "response"
        status_code = mock_status_code if outcome == "response" else None
        response_summary: dict[str, Any] | None = None

        if outcome == "response":
            response_summary = {"status_code": status_code, "mock": True}
        else:
            response_summary = {"message": f"mock {outcome}"}

        return HttpResponseResult(
            url=planned.url,
            method=planned.method,
            outcome=outcome,
            status_code=status_code,
            response_summary=response_summary,
            request_id=request_id,
            dry_run=True,
            evidence={
                "host": planned.host,
                "port": planned.port,
                "path": planned.path,
            },
        )

    def make_request(self, planned: PlannedHttpRequest) -> HttpRequest:
        if not isinstance(planned, PlannedHttpRequest):
            raise HttpProtocolError("planned request must be PlannedHttpRequest")
        return HttpRequest(
            url=planned.url,
            method=planned.method,
            host=planned.host,
            port=planned.port,
            path=planned.full_path,
            headers=planned.headers,
        )
