"""Shared fixtures for PHP webshell provider tests."""

from __future__ import annotations

import pytest

from dsp.execution.providers.webshell import ProviderConfiguration
from dsp.execution.providers.webshell.php import PhpWebshellProvider
from dsp.execution.webshell.transport import MockHttpTransport


@pytest.fixture
def mock_transport() -> MockHttpTransport:
    return MockHttpTransport()


@pytest.fixture
def php_provider(mock_transport: MockHttpTransport) -> PhpWebshellProvider:
    return PhpWebshellProvider(
        transport=mock_transport,
        webshell_url="https://lab.example/shell.php",
        transport_type="https",
    )


@pytest.fixture
def valid_php_config() -> ProviderConfiguration:
    return ProviderConfiguration(
        provider_type="php",
        transport_type="https",
        safe_mode=True,
    )
