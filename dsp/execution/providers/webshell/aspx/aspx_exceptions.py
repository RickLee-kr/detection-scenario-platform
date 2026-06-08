"""ASPX webshell provider exception types."""

from dsp.execution.providers.webshell.provider_exceptions import (
    ProviderConfigurationError,
    ProviderNotSupportedError,
    ProviderSessionError,
    WebshellProviderError,
)


class AspxProviderError(WebshellProviderError):
    """Base exception for ASPX webshell provider errors."""


class AspxProviderNotReadyError(AspxProviderError):
    """Raised when execution is attempted without transport/runtime readiness."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)


__all__ = [
    "AspxProviderError",
    "AspxProviderNotReadyError",
    "ProviderConfigurationError",
    "ProviderNotSupportedError",
    "ProviderSessionError",
]
