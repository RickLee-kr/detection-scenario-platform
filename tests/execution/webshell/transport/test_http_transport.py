"""RealHttpTransport tests — mocked HTTP backend, no live network."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from dsp.execution.webshell.transport import (
    RealHttpTransport,
    RetryPolicy,
    TransportRequest,
    WebshellTransportRetryExhaustedError,
    WebshellTransportTimeoutError,
)
from dsp.execution.webshell.transport.real_http_transport import HttpBackendResponse


@dataclass
class RecordingHttpBackend:
    """Test double that records requests and returns scripted responses."""

    responses: list[HttpBackendResponse | Exception] = field(default_factory=list)
    calls: list[dict[str, object]] = field(default_factory=list)
    _index: int = 0

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> HttpBackendResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": body,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self._index >= len(self.responses):
            raise AssertionError(f"no scripted response for call {self._index + 1}")
        scripted = self.responses[self._index]
        self._index += 1
        if isinstance(scripted, Exception):
            raise scripted
        return scripted


def _request(**overrides: object) -> TransportRequest:
    payload = {
        "url": "https://lab.example/shell.jsp",
        "timeout_seconds": 10.0,
    }
    payload.update(overrides)
    return TransportRequest(**payload)  # type: ignore[arg-type]


def _ok(body: bytes = b"ok", **headers: str) -> HttpBackendResponse:
    merged = {"content-type": "text/plain", **headers}
    return HttpBackendResponse(status_code=200, headers=merged, body=body)


def test_get_success():
    backend = RecordingHttpBackend(
        responses=[_ok(b"get-body", **{"x-dsp": "1"})]
    )
    transport = RealHttpTransport(backend=backend, retry_policy=RetryPolicy(max_retries=0))
    response = transport.send_get(_request(params={"token": "abc"}))
    assert response.success is True
    assert response.body == b"get-body"
    assert response.headers["x-dsp"] == "1"
    assert backend.calls[0]["method"] == "GET"
    assert "token=abc" in str(backend.calls[0]["url"])


def test_post_success():
    backend = RecordingHttpBackend(responses=[_ok(b"post-body")])
    transport = RealHttpTransport(backend=backend, retry_policy=RetryPolicy(max_retries=0))
    response = transport.send_post(_request(body=b"payload"))
    assert response.success is True
    assert response.body == b"post-body"
    assert backend.calls[0]["method"] == "POST"
    assert backend.calls[0]["body"] == b"payload"


def test_upload_success(tmp_path: Path):
    local = tmp_path / "payload.txt"
    local.write_bytes(b"upload-data")
    backend = RecordingHttpBackend(responses=[_ok(b"uploaded")])
    transport = RealHttpTransport(backend=backend, retry_policy=RetryPolicy(max_retries=0))
    response = transport.send_upload(
        _request(),
        local_path=local,
        remote_path="/tmp/dsp_stub/run01/payload.txt",
    )
    assert response.success is True
    assert backend.calls[0]["method"] == "POST"
    body = backend.calls[0]["body"]
    assert isinstance(body, bytes)
    assert b"upload-data" in body
    assert b"/tmp/dsp_stub/run01/payload.txt" in body
    assert "multipart/form-data" in str(backend.calls[0]["headers"]["Content-Type"])


def test_download_success():
    backend = RecordingHttpBackend(responses=[_ok(b"bundle-bytes")])
    transport = RealHttpTransport(backend=backend, retry_policy=RetryPolicy(max_retries=0))
    response = transport.download(
        _request(),
        remote_path="/tmp/dsp_stub/run01/events.jsonl",
    )
    assert response.success is True
    assert response.body == b"bundle-bytes"
    assert "remote_path=%2Ftmp%2Fdsp_stub%2Frun01%2Fevents.jsonl" in str(backend.calls[0]["url"])


def test_timeout_mapping():
    backend = RecordingHttpBackend(
        responses=[
            WebshellTransportTimeoutError(
                "request timeout after 10.0s",
                url="https://lab.example/shell.jsp",
                timeout_seconds=10.0,
            )
        ]
    )
    transport = RealHttpTransport(
        backend=backend,
        retry_policy=RetryPolicy(max_retries=0, retry_on_timeout=False),
    )
    with pytest.raises(WebshellTransportTimeoutError, match="timeout"):
        transport.send_get(_request())


def test_http_4xx_mapping():
    backend = RecordingHttpBackend(
        responses=[HttpBackendResponse(status_code=404, headers={}, body=b"not found")]
    )
    transport = RealHttpTransport(backend=backend, retry_policy=RetryPolicy(max_retries=0))
    response = transport.send_post(_request())
    assert response.status_code == 404
    assert response.success is False
    assert response.body == b"not found"


def test_http_5xx_mapping_without_retry():
    backend = RecordingHttpBackend(
        responses=[HttpBackendResponse(status_code=503, headers={}, body=b"down")]
    )
    transport = RealHttpTransport(
        backend=backend,
        retry_policy=RetryPolicy(max_retries=0, retry_on_http_5xx=False),
    )
    response = transport.send_get(_request())
    assert response.status_code == 503
    assert response.success is False
    assert len(backend.calls) == 1


def test_retry_on_retryable_5xx_when_policy_allows():
    backend = RecordingHttpBackend(
        responses=[
            HttpBackendResponse(status_code=503, headers={}, body=b"down"),
            _ok(b"recovered"),
        ]
    )
    transport = RealHttpTransport(
        backend=backend,
        retry_policy=RetryPolicy(max_retries=2, backoff_seconds=0, retry_on_http_5xx=True),
    )
    response = transport.send_get(_request())
    assert response.success is True
    assert response.body == b"recovered"
    assert len(backend.calls) == 2


def test_no_retry_when_policy_disallows_5xx():
    backend = RecordingHttpBackend(
        responses=[HttpBackendResponse(status_code=503, headers={}, body=b"down")]
    )
    transport = RealHttpTransport(
        backend=backend,
        retry_policy=RetryPolicy(max_retries=3, retry_on_http_5xx=False),
    )
    response = transport.send_get(_request())
    assert response.status_code == 503
    assert len(backend.calls) == 1


def test_retry_exhausted_raises():
    backend = RecordingHttpBackend(
        responses=[
            HttpBackendResponse(status_code=503, headers={}, body=b"down"),
            HttpBackendResponse(status_code=503, headers={}, body=b"down"),
            HttpBackendResponse(status_code=503, headers={}, body=b"down"),
        ]
    )
    transport = RealHttpTransport(
        backend=backend,
        retry_policy=RetryPolicy(max_retries=2, backoff_seconds=0, retry_on_http_5xx=True),
    )
    with pytest.raises(WebshellTransportRetryExhaustedError) as exc_info:
        transport.send_get(_request())
    assert exc_info.value.last_status_code == 503
    assert exc_info.value.attempts == 3


def test_response_headers_and_body_preserved():
    backend = RecordingHttpBackend(
        responses=[
            HttpBackendResponse(
                status_code=201,
                headers={"x-custom": "alpha", "content-type": "application/json"},
                body=b'{"raw":"payload"}',
            )
        ]
    )
    transport = RealHttpTransport(backend=backend, retry_policy=RetryPolicy(max_retries=0))
    response = transport.send_post(_request(body=b"{}"))
    assert response.status_code == 201
    assert response.headers["x-custom"] == "alpha"
    assert response.body == b'{"raw":"payload"}'


def test_retry_on_429_when_policy_allows():
    backend = RecordingHttpBackend(
        responses=[
            HttpBackendResponse(status_code=429, headers={}, body=b"rate limited"),
            _ok(b"ok"),
        ]
    )
    transport = RealHttpTransport(
        backend=backend,
        retry_policy=RetryPolicy(max_retries=1, backoff_seconds=0, retry_on_http_429=True),
    )
    response = transport.send_get(_request())
    assert response.success is True
    assert len(backend.calls) == 2


def test_no_stdout_stderr_parsing():
    source = inspect.getsource(__import__(
        "dsp.execution.webshell.transport.real_http_transport",
        fromlist=["RealHttpTransport"],
    ))
    lowered = source.lower()
    assert "stdout" not in lowered
    assert "stderr" not in lowered
    assert "grep" not in lowered


def test_no_detection_inference():
    source = inspect.getsource(__import__(
        "dsp.execution.webshell.transport.real_http_transport",
        fromlist=["RealHttpTransport"],
    ))
    lowered = source.lower()
    for token in ("detection", "alert", "correlation", "validation_result"):
        assert token not in lowered
