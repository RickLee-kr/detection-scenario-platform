"""Transport error hierarchy tests."""

from __future__ import annotations

from dsp.execution.webshell import WebshellError
from dsp.execution.webshell.transport import (
    WebshellTransportError,
    WebshellTransportRetryExhaustedError,
    WebshellTransportTimeoutError,
    WebshellTransportValidationError,
)


def test_transport_errors_extend_webshell_error():
    assert issubclass(WebshellTransportError, WebshellError)
    assert issubclass(WebshellTransportTimeoutError, WebshellTransportError)
    assert issubclass(WebshellTransportRetryExhaustedError, WebshellTransportError)
    assert issubclass(WebshellTransportValidationError, WebshellTransportError)


def test_transport_error_context_attributes():
    timeout = WebshellTransportTimeoutError(
        "timed out",
        url="https://lab.example/shell.jsp",
        timeout_seconds=10.0,
    )
    assert timeout.url == "https://lab.example/shell.jsp"
    assert timeout.timeout_seconds == 10.0

    retry = WebshellTransportRetryExhaustedError(
        "retries exhausted",
        attempts=3,
        last_status_code=503,
    )
    assert retry.attempts == 3
    assert retry.last_status_code == 503

    validation = WebshellTransportValidationError("blocked", rule="blocked_url_scheme")
    assert validation.rule == "blocked_url_scheme"
