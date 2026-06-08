"""Shared fixtures for JSP webshell provider tests."""

from __future__ import annotations

import pytest

from dsp.execution.providers.webshell import ProviderConfiguration
from dsp.execution.providers.webshell.jsp import JspWebshellProvider
from dsp.execution.webshell.transport import MockHttpTransport


@pytest.fixture
def mock_transport() -> MockHttpTransport:
    return MockHttpTransport()


@pytest.fixture
def jsp_provider(mock_transport: MockHttpTransport) -> JspWebshellProvider:
    return JspWebshellProvider(
        transport=mock_transport,
        webshell_url="https://lab.example/shell.jsp",
        transport_type="https",
    )


@pytest.fixture
def valid_jsp_config() -> ProviderConfiguration:
    return ProviderConfiguration(
        provider_type="jsp",
        transport_type="https",
        safe_mode=True,
    )
