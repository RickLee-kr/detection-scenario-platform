"""GenericWebshellProvider tests — shared base, no execution."""

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
from dsp.execution.providers.webshell.common import (
    GenericWebshellProvider,
    GenericWebshellSession,
)
from dsp.execution.providers.webshell.aspx import AspxWebshellProvider
from dsp.execution.providers.webshell.jsp import JspWebshellProvider
from dsp.execution.providers.webshell.php import PhpWebshellProvider
from dsp.execution.webshell.transport import MockHttpTransport


def test_generic_provider_creation(generic_provider):
    assert isinstance(generic_provider, GenericWebshellProvider)
    assert generic_provider.provider_type == "stub"
    assert generic_provider.provider_name == "Stub Webshell Provider"


def test_generic_capability_defaults(generic_provider):
    caps = generic_provider.get_capabilities()
    assert caps.upload_supported is True
    assert caps.download_supported is True
    assert caps.execute_supported is True
    assert caps.event_sync_supported is True
    assert caps.transport_supported is True


def test_generic_validation_success(generic_provider, valid_generic_config):
    generic_provider.validate_configuration(valid_generic_config)


@pytest.mark.parametrize(
    "config,match",
    [
        (
            ProviderConfiguration(provider_type="jsp", transport_type="https"),
            "provider_type mismatch",
        ),
        (
            ProviderConfiguration(provider_type="stub", transport_type=""),
            "transport_type",
        ),
        (
            ProviderConfiguration(provider_type="stub", transport_type="ftp"),
            "transport_type",
        ),
        (
            ProviderConfiguration(provider_type="stub", timeout_profile=""),
            "timeout_profile",
        ),
        (
            ProviderConfiguration(
                provider_type="stub",
                transport_type="https",
                timeout_profile="invalid_profile",
            ),
            "timeout_profile",
        ),
    ],
)
def test_generic_validation_failure(generic_provider, config, match):
    with pytest.raises(ProviderConfigurationError, match=match):
        generic_provider.validate_configuration(config)


def test_transport_injection_storage(mock_transport: MockHttpTransport):
    class StubProvider(GenericWebshellProvider):
        provider_type = "stub"
        provider_name = "Stub Webshell Provider"
        session_class = GenericWebshellSession

    provider = StubProvider(transport=mock_transport)
    assert provider.transport is mock_transport


def test_generic_session_creation(generic_provider):
    session = generic_provider.create_session()
    assert isinstance(session, GenericWebshellSession)
    assert session.provider_type == "stub"
    assert session.state == ProviderSessionState.CREATED
    assert session.webshell_url == "https://lab.example/shell.stub"
    assert session.transport_type == "https"
    assert session.session_id


def test_jsp_inheritance_validation(mock_transport: MockHttpTransport):
    provider = JspWebshellProvider(transport=mock_transport)
    assert isinstance(provider, GenericWebshellProvider)
    assert provider.provider_type == "jsp"
    assert provider.provider_name == "JSP Webshell Provider"
    assert provider.session_class.__name__ == "JspProviderSession"


def test_php_inheritance_validation(mock_transport: MockHttpTransport):
    provider = PhpWebshellProvider(transport=mock_transport)
    assert isinstance(provider, GenericWebshellProvider)
    assert provider.provider_type == "php"
    assert provider.provider_name == "PHP Webshell Provider"
    assert provider.session_class.__name__ == "PhpProviderSession"


def test_factory_compatibility(mock_transport: MockHttpTransport):
    jsp = create_webshell_provider("jsp", transport=mock_transport)
    php = create_webshell_provider("php", transport=mock_transport)
    aspx = create_webshell_provider("aspx", transport=mock_transport)
    assert isinstance(jsp, JspWebshellProvider)
    assert isinstance(php, PhpWebshellProvider)
    assert isinstance(aspx, AspxWebshellProvider)
    assert isinstance(jsp, GenericWebshellProvider)
    assert isinstance(php, GenericWebshellProvider)
    assert isinstance(aspx, GenericWebshellProvider)


def test_registry_compatibility():
    registry = WebshellProviderRegistry()
    registry.register_provider("jsp", JspWebshellProvider)
    registry.register_provider("php", PhpWebshellProvider)
    assert registry.get_provider("jsp") is JspWebshellProvider
    assert registry.get_provider("php") is PhpWebshellProvider
    assert sorted(registry.list_providers()) == ["jsp", "php"]


def test_generic_provider_isolation(mock_transport: MockHttpTransport):
    """No transport invocation during generic provider use."""
    class StubProvider(GenericWebshellProvider):
        provider_type = "stub"
        provider_name = "Stub Webshell Provider"
        session_class = GenericWebshellSession

    transport = MagicMock(spec=MockHttpTransport)
    transport.send_get = MagicMock()
    transport.send_post = MagicMock()
    transport.send_upload = MagicMock()
    transport.download = MagicMock()
    transport.healthcheck = MagicMock()

    provider = StubProvider(transport=transport)
    provider.get_metadata()
    provider.get_capabilities()
    provider.validate_configuration(
        ProviderConfiguration(provider_type="stub", transport_type="https")
    )
    provider.create_session()

    transport.send_get.assert_not_called()
    transport.send_post.assert_not_called()
    transport.send_upload.assert_not_called()
    transport.download.assert_not_called()
    transport.healthcheck.assert_not_called()

    assert len(mock_transport.calls) == 0
