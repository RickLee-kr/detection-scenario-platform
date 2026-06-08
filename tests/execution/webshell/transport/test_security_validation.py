"""Transport security validation wiring tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from dsp.execution.webshell import WebshellSecurityPolicy, WebshellSecurityViolation
from dsp.execution.webshell.transport import (
    TransportRequest,
    WebshellTransportValidationError,
    validate_download_transport,
    validate_transport_request,
    validate_transport_url,
    validate_upload_transport,
)


def _request(url: str = "https://lab.example/shell.jsp") -> TransportRequest:
    return TransportRequest(url=url, timeout_seconds=25.0)


def test_validate_transport_url_blocks_file_scheme():
    policy = WebshellSecurityPolicy()
    with pytest.raises(WebshellTransportValidationError, match="blocked url scheme"):
        validate_transport_url(policy, "file:///etc/passwd")


def test_validate_transport_url_blocks_loopback_in_safe_mode():
    policy = WebshellSecurityPolicy(safe_mode=True)
    with pytest.raises(WebshellTransportValidationError, match="loopback url blocked"):
        validate_transport_url(policy, "http://127.0.0.1/shell.jsp")


def test_validate_transport_url_allows_loopback_when_safe_mode_off():
    policy = WebshellSecurityPolicy(safe_mode=False)
    validate_transport_url(policy, "http://127.0.0.1/shell.jsp")


def test_validate_transport_url_custom_blocked_pattern():
    policy = WebshellSecurityPolicy()
    patterns = frozenset({"admin"})
    with pytest.raises(WebshellTransportValidationError, match="blocked url pattern"):
        validate_transport_url(
            policy,
            "https://lab.example/admin/shell.jsp",
            blocked_url_patterns=patterns,
        )


def test_validate_upload_transport_enforces_policy(tmp_path: Path):
    local = tmp_path / "stub.py"
    local.write_text("print('ok')")
    policy = WebshellSecurityPolicy(allow_upload=True)
    request = _request()
    validate_upload_transport(
        policy,
        request,
        local_path=local,
        remote_path="/tmp/dsp_stub/run01/stub.py",
    )


def test_validate_upload_transport_denied_upload():
    policy = WebshellSecurityPolicy(allow_upload=False)
    with pytest.raises(WebshellSecurityViolation, match="upload not allowed"):
        validate_upload_transport(
            policy,
            _request(),
            local_path=Path("/tmp/nonexistent"),
            remote_path="/tmp/dsp_stub/run01/stub.py",
        )


def test_validate_upload_transport_forbidden_path(tmp_path: Path):
    local = tmp_path / "stub.py"
    local.write_text("x")
    policy = WebshellSecurityPolicy(allowed_paths=("/var/www/html/", "/tmp/dsp_stub/"))
    with pytest.raises(WebshellTransportValidationError, match="forbidden upload path"):
        validate_upload_transport(
            policy,
            _request(),
            local_path=local,
            remote_path="/var/www/html/shell.jsp",
        )


def test_validate_upload_transport_file_size(tmp_path: Path):
    local = tmp_path / "big.bin"
    local.write_bytes(b"x" * (2 * 1024 * 1024))
    policy = WebshellSecurityPolicy(max_file_size_mb=1.0)
    with pytest.raises(WebshellSecurityViolation, match="exceeds limit"):
        validate_upload_transport(
            policy,
            _request(),
            local_path=local,
            remote_path="/tmp/dsp_stub/run01/big.bin",
        )


def test_validate_download_transport_denied():
    policy = WebshellSecurityPolicy(allow_download=False)
    with pytest.raises(WebshellSecurityViolation, match="download not allowed"):
        validate_download_transport(
            policy,
            _request(),
            remote_path="/tmp/dsp_stub/run01/out.jsonl",
        )


def test_validate_transport_request_rejects_non_positive_timeout():
    policy = WebshellSecurityPolicy()
    with pytest.raises(WebshellTransportValidationError, match="timeout_seconds"):
        validate_transport_request(
            policy,
            TransportRequest(url="https://lab.example/shell.jsp", timeout_seconds=0),
        )
