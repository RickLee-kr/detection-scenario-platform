"""AspxWebshellProvider tests — mock-first, no execution."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dsp.execution.providers.webshell import (
    ProviderConfiguration,
    ProviderConfigurationError,
    ProviderSessionState,
    WebshellProviderRegistry,
    create_webshell_provider,
)
from dsp.execution.providers.webshell.aspx import (
    ASPX_PROVIDER_VERSION,
    AspxProviderSession,
    AspxWebshellProvider,
)
from dsp.execution.providers.webshell.common import GenericWebshellProvider
from dsp.execution.webshell.transport import MockHttpTransport


def test_provider_creation(aspx_provider: AspxWebshellProvider):
    assert isinstance(aspx_provider, AspxWebshellProvider)


def test_provider_metadata_values(aspx_provider: AspxWebshellProvider):
    assert aspx_provider.provider_type == "aspx"
    assert aspx_provider.provider_name == "ASPX Webshell Provider"
    assert aspx_provider.provider_version == "1.0.0"

    metadata = aspx_provider.get_metadata()
    assert metadata["provider_type"] == "aspx"
    assert metadata["provider_name"] == "ASPX Webshell Provider"
    assert metadata["provider_version"] == "1.0.0"
    assert metadata["reserved"] is True


def test_capability_inheritance(aspx_provider: AspxWebshellProvider):
    caps = aspx_provider.get_capabilities()
    assert caps.upload_supported is True
    assert caps.download_supported is True
    assert caps.execute_supported is True
    assert caps.event_sync_supported is True
    assert caps.transport_supported is True


def test_transport_injection(mock_transport: MockHttpTransport):
    provider = AspxWebshellProvider(transport=mock_transport)
    assert provider.transport is mock_transport


def test_configuration_validation_success(
    aspx_provider: AspxWebshellProvider,
    valid_aspx_config: ProviderConfiguration,
):
    aspx_provider.validate_configuration(valid_aspx_config)


@pytest.mark.parametrize(
    "config,match",
    [
        (
            ProviderConfiguration(provider_type="jsp", transport_type="https"),
            "provider_type mismatch",
        ),
        (
            ProviderConfiguration(provider_type="aspx", transport_type=""),
            "transport_type",
        ),
        (
            ProviderConfiguration(provider_type="aspx", transport_type="ftp"),
            "transport_type",
        ),
        (
            ProviderConfiguration(provider_type="aspx", timeout_profile=""),
            "timeout_profile",
        ),
        (
            ProviderConfiguration(
                provider_type="aspx",
                transport_type="https",
                timeout_profile="invalid_profile",
            ),
            "timeout_profile",
        ),
    ],
)
def test_configuration_validation_failure(
    aspx_provider: AspxWebshellProvider,
    config: ProviderConfiguration,
    match: str,
):
    with pytest.raises(ProviderConfigurationError, match=match):
        aspx_provider.validate_configuration(config)


def test_session_creation(aspx_provider: AspxWebshellProvider):
    session = aspx_provider.create_session()
    assert isinstance(session, AspxProviderSession)
    assert session.provider_type == "aspx"
    assert session.state == ProviderSessionState.CREATED
    assert session.webshell_url == "https://lab.example/shell.aspx"
    assert session.transport_type == "https"
    assert session.provider_version == ASPX_PROVIDER_VERSION
    assert session.session_id


def test_factory_aspx_support(mock_transport: MockHttpTransport):
    provider = create_webshell_provider("aspx", transport=mock_transport)
    assert isinstance(provider, AspxWebshellProvider)
    assert provider.transport is mock_transport


def test_registry_registration():
    registry = WebshellProviderRegistry()
    registry.register_provider("aspx", AspxWebshellProvider)
    assert registry.get_provider("aspx") is AspxWebshellProvider
    assert registry.list_providers() == ["aspx"]


def test_provider_isolation(mock_transport: MockHttpTransport):
    """No transport, network, or event sync invocation during provider use."""
    transport = MagicMock(spec=MockHttpTransport)
    transport.send_get = MagicMock()
    transport.send_post = MagicMock()
    transport.send_upload = MagicMock()
    transport.download = MagicMock()
    transport.healthcheck = MagicMock()

    provider = AspxWebshellProvider(transport=transport)
    provider.get_metadata()
    provider.get_capabilities()
    provider.validate_configuration(
        ProviderConfiguration(provider_type="aspx", transport_type="https")
    )
    provider.create_session()

    transport.send_get.assert_not_called()
    transport.send_post.assert_not_called()
    transport.send_upload.assert_not_called()
    transport.download.assert_not_called()
    transport.healthcheck.assert_not_called()

    assert len(mock_transport.calls) == 0


def test_transport_never_called(mock_transport: MockHttpTransport):
    """Explicit assertion that injected MockHttpTransport receives no calls."""
    provider = AspxWebshellProvider(
        transport=mock_transport,
        webshell_url="https://lab.example/shell.aspx",
    )
    provider.get_metadata()
    provider.get_capabilities()
    provider.validate_configuration(
        ProviderConfiguration(provider_type="aspx", transport_type="https")
    )
    provider.create_session()

    assert mock_transport.calls == []


def test_generic_inheritance_validation(mock_transport: MockHttpTransport):
    provider = AspxWebshellProvider(transport=mock_transport)
    assert isinstance(provider, GenericWebshellProvider)
    assert provider.provider_type == "aspx"
    assert provider.provider_name == "ASPX Webshell Provider"
    assert provider.session_class.__name__ == "AspxProviderSession"
