"""JspWebshellProvider tests — mock-first, no execution."""

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
from dsp.execution.providers.webshell.jsp import (
    JSP_PROVIDER_VERSION,
    JspProviderSession,
    JspWebshellProvider,
)
from dsp.execution.webshell.transport import MockHttpTransport


def test_provider_creation(jsp_provider: JspWebshellProvider):
    assert isinstance(jsp_provider, JspWebshellProvider)


def test_provider_metadata_values(jsp_provider: JspWebshellProvider):
    assert jsp_provider.provider_type == "jsp"
    assert jsp_provider.provider_name == "JSP Webshell Provider"
    assert jsp_provider.provider_version == "1.0.0"

    metadata = jsp_provider.get_metadata()
    assert metadata["provider_type"] == "jsp"
    assert metadata["provider_name"] == "JSP Webshell Provider"
    assert metadata["provider_version"] == "1.0.0"
    assert metadata["reserved"] is True


def test_capability_defaults(jsp_provider: JspWebshellProvider):
    caps = jsp_provider.get_capabilities()
    assert caps.upload_supported is True
    assert caps.download_supported is True
    assert caps.execute_supported is True
    assert caps.event_sync_supported is True
    assert caps.transport_supported is True


def test_transport_injection(mock_transport: MockHttpTransport):
    provider = JspWebshellProvider(transport=mock_transport)
    assert provider.transport is mock_transport


def test_configuration_validation_success(
    jsp_provider: JspWebshellProvider,
    valid_jsp_config: ProviderConfiguration,
):
    jsp_provider.validate_configuration(valid_jsp_config)


@pytest.mark.parametrize(
    "config,match",
    [
        (
            ProviderConfiguration(provider_type="php", transport_type="https"),
            "provider_type mismatch",
        ),
        (
            ProviderConfiguration(provider_type="jsp", transport_type=""),
            "transport_type",
        ),
        (
            ProviderConfiguration(provider_type="jsp", transport_type="ftp"),
            "transport_type",
        ),
        (
            ProviderConfiguration(provider_type="jsp", timeout_profile=""),
            "timeout_profile",
        ),
        (
            ProviderConfiguration(
                provider_type="jsp",
                transport_type="https",
                timeout_profile="invalid_profile",
            ),
            "timeout_profile",
        ),
    ],
)
def test_configuration_validation_failure(
    jsp_provider: JspWebshellProvider,
    config: ProviderConfiguration,
    match: str,
):
    with pytest.raises(ProviderConfigurationError, match=match):
        jsp_provider.validate_configuration(config)


def test_session_creation(jsp_provider: JspWebshellProvider):
    session = jsp_provider.create_session()
    assert isinstance(session, JspProviderSession)
    assert session.provider_type == "jsp"
    assert session.state == ProviderSessionState.CREATED
    assert session.webshell_url == "https://lab.example/shell.jsp"
    assert session.transport_type == "https"
    assert session.provider_version == JSP_PROVIDER_VERSION
    assert session.session_id


def test_factory_jsp_support(mock_transport: MockHttpTransport):
    provider = create_webshell_provider("jsp", transport=mock_transport)
    assert isinstance(provider, JspWebshellProvider)
    assert provider.transport is mock_transport


def test_registry_registration():
    registry = WebshellProviderRegistry()
    registry.register_provider("jsp", JspWebshellProvider)
    assert registry.get_provider("jsp") is JspWebshellProvider
    assert registry.list_providers() == ["jsp"]


def test_provider_isolation(mock_transport: MockHttpTransport):
    """No transport, network, or event sync invocation during provider use."""
    transport = MagicMock(spec=MockHttpTransport)
    transport.send_get = MagicMock()
    transport.send_post = MagicMock()
    transport.send_upload = MagicMock()
    transport.download = MagicMock()
    transport.healthcheck = MagicMock()

    provider = JspWebshellProvider(transport=transport)
    provider.get_metadata()
    provider.get_capabilities()
    provider.validate_configuration(
        ProviderConfiguration(provider_type="jsp", transport_type="https")
    )
    provider.create_session()

    transport.send_get.assert_not_called()
    transport.send_post.assert_not_called()
    transport.send_upload.assert_not_called()
    transport.download.assert_not_called()
    transport.healthcheck.assert_not_called()

    assert len(mock_transport.calls) == 0
