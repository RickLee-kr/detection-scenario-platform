"""Shared fixtures for generic webshell provider tests."""

from __future__ import annotations

import pytest

from dsp.execution.providers.webshell import ProviderConfiguration
from dsp.execution.providers.webshell.common import GenericWebshellProvider
from dsp.execution.providers.webshell.common.generic_models import GenericWebshellSession
from dsp.execution.webshell.transport import MockHttpTransport


class _StubGenericProvider(GenericWebshellProvider):
    """Concrete generic provider for unit tests."""

    provider_type = "stub"
    provider_name = "Stub Webshell Provider"
    session_class = GenericWebshellSession


@pytest.fixture
def mock_transport() -> MockHttpTransport:
    return MockHttpTransport()


@pytest.fixture
def generic_provider(mock_transport: MockHttpTransport) -> _StubGenericProvider:
    return _StubGenericProvider(
        transport=mock_transport,
        webshell_url="https://lab.example/shell.stub",
        transport_type="https",
    )


@pytest.fixture
def valid_generic_config() -> ProviderConfiguration:
    return ProviderConfiguration(
        provider_type="stub",
        transport_type="https",
        safe_mode=True,
    )
