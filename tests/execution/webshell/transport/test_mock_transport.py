"""MockHttpTransport tests — no live HTTP."""

from __future__ import annotations

from pathlib import Path

import pytest

from dsp.execution.webshell.transport import (
    MockHttpTransport,
    MockTransportMode,
    TransportRequest,
    WebshellTransportTimeoutError,
)


def _request() -> TransportRequest:
    return TransportRequest(url="https://lab.example/shell.jsp", timeout_seconds=10.0)


def test_mock_transport_success():
    transport = MockHttpTransport(mode=MockTransportMode.SUCCESS, body=b"healthy")
    response = transport.healthcheck(_request())
    assert response.success is True
    assert response.status_code == 200
    assert response.body == b"healthy"
    assert len(transport.calls) == 1
    assert transport.calls[0]["operation"] == "healthcheck"


def test_mock_transport_timeout():
    transport = MockHttpTransport(mode=MockTransportMode.TIMEOUT)
    with pytest.raises(WebshellTransportTimeoutError, match="mock timeout"):
        transport.send_get(_request())


def test_mock_transport_5xx():
    transport = MockHttpTransport(mode=MockTransportMode.HTTP_5XX)
    response = transport.send_post(_request())
    assert response.status_code == 503
    assert response.success is False


def test_mock_transport_429():
    transport = MockHttpTransport(mode=MockTransportMode.HTTP_429)
    response = transport.send_get(_request())
    assert response.status_code == 429
    assert response.success is False


def test_mock_transport_auth_failure():
    transport = MockHttpTransport(mode=MockTransportMode.AUTH_FAILURE)
    response = transport.send_post(_request())
    assert response.status_code == 401
    assert response.success is False


def test_mock_transport_upload_and_download_record_paths(tmp_path: Path):
    local = tmp_path / "payload.txt"
    local.write_text("data")
    transport = MockHttpTransport()
    upload_response = transport.send_upload(
        _request(),
        local_path=local,
        remote_path="/tmp/dsp_stub/run01/payload.txt",
    )
    download_response = transport.download(
        _request(),
        remote_path="/tmp/dsp_stub/run01/payload.txt",
    )
    assert upload_response.success is True
    assert download_response.success is True
    assert transport.calls[0]["local_path"] == str(local)
    assert transport.calls[1]["remote_path"] == "/tmp/dsp_stub/run01/payload.txt"
