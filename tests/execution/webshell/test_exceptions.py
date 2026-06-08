"""Webshell exception hierarchy tests."""

from __future__ import annotations

from dsp.execution.webshell import (
    WebshellAuthenticationError,
    WebshellConnectionError,
    WebshellDownloadError,
    WebshellError,
    WebshellExecutionError,
    WebshellSecurityViolation,
    WebshellUploadError,
)


def test_exception_hierarchy():
    assert issubclass(WebshellConnectionError, WebshellError)
    assert issubclass(WebshellAuthenticationError, WebshellError)
    assert issubclass(WebshellExecutionError, WebshellError)
    assert issubclass(WebshellUploadError, WebshellError)
    assert issubclass(WebshellDownloadError, WebshellError)
    assert issubclass(WebshellSecurityViolation, WebshellError)


def test_exception_attributes():
    conn = WebshellConnectionError("timeout", url="http://lab/ws.jsp")
    assert conn.url == "http://lab/ws.jsp"

    auth = WebshellAuthenticationError("denied", mode="basic")
    assert auth.mode == "basic"

    exec_err = WebshellExecutionError("failed", command="id", exit_code=1)
    assert exec_err.exit_code == 1

    upload = WebshellUploadError(
        "fail",
        local_path="/a",
        remote_path="/tmp/dsp_stub/x",
    )
    assert upload.local_path == "/a"

    sec = WebshellSecurityViolation("blocked", rule="blocked_commands")
    assert sec.rule == "blocked_commands"
