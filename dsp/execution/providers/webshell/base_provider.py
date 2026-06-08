"""WebshellProviderBase — family adapter skeleton (no execution)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from dsp.execution.providers.webshell.provider_exceptions import (
    ProviderConfigurationError,
)
from dsp.execution.providers.webshell.provider_models import (
    RESERVED_PROVIDER_TYPES,
    VALID_TRANSPORT_TYPES,
    ProviderCapabilities,
    ProviderConfiguration,
    ProviderSession,
)
from dsp.execution.webshell.transport.timeout import VALID_TIMEOUT_PROFILES


class WebshellProviderBase(ABC):
    """Abstract webshell family provider — metadata and session declaration only.

    Must NOT execute commands, transfer files, or open network connections.
  """

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Stable family identifier (e.g. ``jsp``, ``php``, ``aspx``)."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider label for metadata and logging."""

    @abstractmethod
    def get_capabilities(self) -> ProviderCapabilities:
        """Return the capability matrix for this provider family."""

    def get_metadata(self) -> dict[str, Any]:
        """Return static provider metadata (no runtime probing)."""
        return {
            "provider_type": self.provider_type,
            "provider_name": self.provider_name,
            "capabilities": self.get_capabilities().to_dict(),
            "reserved": self.provider_type in RESERVED_PROVIDER_TYPES,
        }

    def create_session(self) -> ProviderSession:
        """Declare a new session record in CREATED state (no transport)."""
        return ProviderSession.new(self.provider_type)

    def validate_configuration(self, config: ProviderConfiguration) -> None:
        """Validate provider configuration without side effects."""
        if config.provider_type != self.provider_type:
            raise ProviderConfigurationError(
                f"provider_type mismatch: expected {self.provider_type!r}, "
                f"got {config.provider_type!r}",
                field="provider_type",
            )
        if config.transport_type not in VALID_TRANSPORT_TYPES:
            raise ProviderConfigurationError(
                f"unsupported transport_type: {config.transport_type!r}",
                field="transport_type",
            )
        if config.timeout_profile not in VALID_TIMEOUT_PROFILES:
            raise ProviderConfigurationError(
                f"unsupported timeout_profile: {config.timeout_profile!r}",
                field="timeout_profile",
            )
