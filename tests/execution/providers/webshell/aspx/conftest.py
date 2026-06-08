"""Shared fixtures for ASPX webshell provider tests."""

from __future__ import annotations

import pytest

from dsp.execution.providers.webshell import ProviderConfiguration
from dsp.execution.providers.webshell.aspx import AspxWebshellProvider
from dsp.execution.webshell.transport import MockHttpTransport


@pytest.fixture
def mock_transport() -> MockHttpTransport:
    return MockHttpTransport()


@pytest.fixture
def aspx_provider(mock_transport: MockHttpTransport) -> AspxWebshellProvider:
    return AspxWebshellProvider(
        transport=mock_transport,
        webshell_url="https://lab.example/shell.aspx",
        transport_type="https",
    )


@pytest.fixture
def valid_aspx_config() -> ProviderConfiguration:
    return ProviderConfiguration(
        provider_type="aspx",
        transport_type="https",
        safe_mode=True,
    )
