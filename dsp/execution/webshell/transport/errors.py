"""Transport-layer exception hierarchy — extends webshell base errors."""

from __future__ import annotations

from dsp.execution.webshell.exceptions import WebshellError


class WebshellTransportError(WebshellError):
    """Base exception for HTTP transport failures."""


class WebshellTransportTimeoutError(WebshellTransportError):
    """Request exceeded configured timeout."""

    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        super().__init__(message)


class WebshellTransportRetryExhaustedError(WebshellTransportError):
    """All retry attempts failed."""

    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        attempts: int | None = None,
        last_status_code: int | None = None,
    ) -> None:
        self.url = url
        self.attempts = attempts
        self.last_status_code = last_status_code
        super().__init__(message)


class WebshellTransportValidationError(WebshellTransportError):
    """Pre-flight transport request rejected by security validation."""

    def __init__(self, message: str, *, rule: str | None = None) -> None:
        self.rule = rule
        super().__init__(message)
