"""In-memory registry for webshell provider family classes."""

from __future__ import annotations

from typing import Type

from dsp.execution.providers.webshell.base_provider import WebshellProviderBase
from dsp.execution.providers.webshell.provider_exceptions import (
    ProviderConfigurationError,
    ProviderNotSupportedError,
)


class WebshellProviderRegistry:
    """Registry of webshell provider family classes — no execution."""

    def __init__(self) -> None:
        self._providers: dict[str, Type[WebshellProviderBase]] = {}

    def register_provider(
        self,
        provider_type: str,
        provider_cls: Type[WebshellProviderBase],
    ) -> None:
        """Register a provider class under a stable type key."""
        if provider_type in self._providers:
            raise ProviderConfigurationError(
                f"provider already registered: {provider_type!r}",
                field="provider_type",
            )
        self._providers[provider_type] = provider_cls

    def unregister_provider(self, provider_type: str) -> None:
        """Remove a provider class from the registry."""
        if provider_type not in self._providers:
            raise ProviderNotSupportedError(
                f"provider not registered: {provider_type!r}",
                provider_type=provider_type,
            )
        del self._providers[provider_type]

    def get_provider(self, provider_type: str) -> Type[WebshellProviderBase]:
        """Look up a registered provider class."""
        provider_cls = self._providers.get(provider_type)
        if provider_cls is None:
            raise ProviderNotSupportedError(
                f"provider not registered: {provider_type!r}",
                provider_type=provider_type,
            )
        return provider_cls

    def list_providers(self) -> list[str]:
        """Return sorted registered provider type keys."""
        return sorted(self._providers.keys())

    def clear(self) -> None:
        """Remove all registrations (test helper)."""
        self._providers.clear()


_default_registry = WebshellProviderRegistry()


def register_provider(
    provider_type: str,
    provider_cls: Type[WebshellProviderBase],
) -> None:
    """Register a provider class in the module-level registry."""
    _default_registry.register_provider(provider_type, provider_cls)


def unregister_provider(provider_type: str) -> None:
    """Unregister a provider class from the module-level registry."""
    _default_registry.unregister_provider(provider_type)


def get_provider(provider_type: str) -> Type[WebshellProviderBase]:
    """Look up a provider class from the module-level registry."""
    return _default_registry.get_provider(provider_type)


def list_providers() -> list[str]:
    """List provider types in the module-level registry."""
    return _default_registry.list_providers()
