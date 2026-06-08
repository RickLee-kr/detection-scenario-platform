"""WebshellProviderRegistry tests."""

from __future__ import annotations

import pytest

from dsp.execution.providers.webshell import (
    ProviderConfigurationError,
    ProviderNotSupportedError,
    WebshellProviderRegistry,
)


def test_registry_registration(registry, stub_provider_cls):
    registry.register_provider("stub", stub_provider_cls)
    assert registry.list_providers() == ["stub"]


def test_registry_lookup(registry, stub_provider_cls):
    registry.register_provider("stub", stub_provider_cls)
    assert registry.get_provider("stub") is stub_provider_cls


def test_registry_duplicate_protection(registry, stub_provider_cls):
    registry.register_provider("stub", stub_provider_cls)
    with pytest.raises(ProviderConfigurationError, match="already registered"):
        registry.register_provider("stub", stub_provider_cls)


def test_registry_removal(registry, stub_provider_cls):
    registry.register_provider("stub", stub_provider_cls)
    registry.unregister_provider("stub")
    assert registry.list_providers() == []


def test_registry_lookup_missing_raises(registry):
    with pytest.raises(ProviderNotSupportedError, match="not registered"):
        registry.get_provider("missing")


def test_registry_unregister_missing_raises(registry):
    with pytest.raises(ProviderNotSupportedError, match="not registered"):
        registry.unregister_provider("missing")
