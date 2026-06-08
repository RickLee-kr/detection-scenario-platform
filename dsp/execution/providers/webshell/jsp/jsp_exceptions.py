"""JSP webshell provider exception types."""

from dsp.execution.providers.webshell.provider_exceptions import (
    ProviderConfigurationError,
    ProviderNotSupportedError,
    ProviderSessionError,
    WebshellProviderError,
)


class JspProviderError(WebshellProviderError):
    """Base exception for JSP webshell provider errors."""


class JspProviderNotReadyError(JspProviderError):
    """Raised when execution is attempted without transport/runtime readiness."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)


__all__ = [
    "JspProviderError",
    "JspProviderNotReadyError",
    "ProviderConfigurationError",
    "ProviderNotSupportedError",
    "ProviderSessionError",
]
