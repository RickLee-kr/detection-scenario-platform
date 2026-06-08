"""Generic webshell provider exception types."""

from dsp.execution.providers.webshell.provider_exceptions import (
    ProviderConfigurationError,
    ProviderNotSupportedError,
    ProviderSessionError,
    WebshellProviderError,
)


class GenericWebshellProviderError(WebshellProviderError):
    """Base exception for generic webshell provider errors."""


__all__ = [
    "GenericWebshellProviderError",
    "ProviderConfigurationError",
    "ProviderNotSupportedError",
    "ProviderSessionError",
]
