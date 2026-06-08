"""Generic webshell provider adapter — Phase X+1G (shared base, no execution)."""

from dsp.execution.providers.webshell.common.generic_exceptions import (
    GenericWebshellProviderError,
    ProviderConfigurationError,
    ProviderNotSupportedError,
    ProviderSessionError,
)
from dsp.execution.providers.webshell.common.generic_models import (
    GENERIC_PROVIDER_VERSION,
    GenericWebshellSession,
)
from dsp.execution.providers.webshell.common.generic_provider import (
    GenericWebshellProvider,
)

__all__ = [
    "GENERIC_PROVIDER_VERSION",
    "GenericWebshellProvider",
    "GenericWebshellProviderError",
    "GenericWebshellSession",
    "ProviderConfigurationError",
    "ProviderNotSupportedError",
    "ProviderSessionError",
]
