"""Shared fixtures for webshell provider skeleton tests."""

from __future__ import annotations

import pytest

from dsp.execution.providers.webshell import (
    ProviderCapabilities,
    ProviderConfiguration,
    WebshellProviderBase,
    WebshellProviderRegistry,
)
from dsp.execution.providers.webshell.provider_registry import _default_registry


class StubWebshellProvider(WebshellProviderBase):
    """Test double — metadata and session only, no execution."""

    @property
    def provider_type(self) -> str:
        return "stub"

    @property
    def provider_name(self) -> str:
        return "Stub Provider"

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()


@pytest.fixture
def stub_provider_cls():
    return StubWebshellProvider


@pytest.fixture
def stub_provider(stub_provider_cls):
    return stub_provider_cls()


@pytest.fixture
def valid_config():
    return ProviderConfiguration(provider_type="stub", transport_type="https")


@pytest.fixture
def registry() -> WebshellProviderRegistry:
    saved = dict(_default_registry._providers)
    _default_registry.clear()
    yield _default_registry
    _default_registry._providers = saved
