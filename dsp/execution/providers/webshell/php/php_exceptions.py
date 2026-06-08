"""PHP webshell provider exception types."""

from dsp.execution.providers.webshell.provider_exceptions import (
    ProviderConfigurationError,
    ProviderNotSupportedError,
    ProviderSessionError,
    WebshellProviderError,
)


class PhpProviderError(WebshellProviderError):
    """Base exception for PHP webshell provider errors."""


class PhpProviderNotReadyError(PhpProviderError):
    """Raised when execution is attempted without transport/runtime readiness."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)


__all__ = [
    "PhpProviderError",
    "PhpProviderNotReadyError",
    "ProviderConfigurationError",
    "ProviderNotSupportedError",
    "ProviderSessionError",
]
