"""HTTP protocol client unit tests."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest

from dsp.protocols.base import HttpProtocolError
from dsp.protocols.http import HttpClient, send_request
from dsp.protocols.http.urls import PlannedHttpRequest


def test_mock_http_request():
    client = HttpClient(mode="mock")
    plan = PlannedHttpRequest(host="10.10.10.20", port=443, path="/login")
    request = client.make_request(plan)
    result = client.request(request)
    assert result.outcome == "response"
    assert result.status_code == 200
    assert result.dry_run is True


def test_live_mode_rejects_mock_outcome():
    client = HttpClient(mode="live")
    plan = PlannedHttpRequest(host="10.10.10.20", port=80, path="/")
    request = client.make_request(plan)
    with pytest.raises(HttpProtocolError, match="mock_outcome"):
        client.request(request, mock_outcome="response")


def test_send_request_parses_http_response():
    plan = PlannedHttpRequest(host="10.10.10.20", port=80, path="/health")
    url = plan.url

    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    mock_resp.status = 200
    mock_resp.getcode.return_value = 200
    mock_resp.reason = "OK"
    mock_resp.read.return_value = b"ok"

    with patch("urllib.request.build_opener") as build_opener:
        opener = MagicMock()
        opener.open.return_value = mock_resp
        build_opener.return_value = opener
        result = send_request(url, timeout=1.0)

    assert result.outcome == "response"
    assert result.status_code == 200
    assert result.dry_run is False


def test_send_request_http_error_is_response():
    import urllib.error

    plan = PlannedHttpRequest(host="10.10.10.20", port=80, path="/missing")
    url = plan.url
    err = urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=io.BytesIO(b""))

    with patch("urllib.request.build_opener") as build_opener:
        opener = MagicMock()
        opener.open.side_effect = err
        build_opener.return_value = opener
        result = send_request(url, timeout=1.0)

    assert result.outcome == "response"
    assert result.status_code == 404
