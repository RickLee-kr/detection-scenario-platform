"""TransportRequest and TransportResponse model tests."""

from __future__ import annotations

from dsp.execution.webshell.transport import TransportRequest, TransportResponse


def test_transport_request_roundtrip():
    request = TransportRequest(
        url="https://lab.example/shell.jsp",
        method="POST",
        headers={"X-Test": "1"},
        cookies={"session": "abc"},
        params={"cmd": "id"},
        body=b"payload",
        timeout_seconds=30.0,
        metadata={"family": "jsp"},
    )
    restored = TransportRequest.from_dict(request.to_dict())
    assert restored.url == request.url
    assert restored.method == request.method
    assert restored.headers == request.headers
    assert restored.cookies == request.cookies
    assert restored.params == request.params
    assert restored.body == "payload"
    assert restored.timeout_seconds == request.timeout_seconds
    assert restored.metadata == request.metadata


def test_transport_response_roundtrip():
    response = TransportResponse(
        status_code=200,
        headers={"content-type": "text/html"},
        body=b"<html>ok</html>",
        duration_ms=12.5,
        success=True,
        metadata={"transport": "mock"},
    )
    restored = TransportResponse.from_dict(response.to_dict())
    assert restored.status_code == response.status_code
    assert restored.headers == response.headers
    assert restored.body == response.body
    assert restored.duration_ms == response.duration_ms
    assert restored.success == response.success
    assert restored.metadata == response.metadata
