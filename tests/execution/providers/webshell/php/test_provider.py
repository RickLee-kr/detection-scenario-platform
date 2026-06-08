"""PhpWebshellProvider tests — mock-first, no execution."""

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
from dsp.execution.providers.webshell.php import (
    PHP_PROVIDER_VERSION,
    PhpProviderSession,
    PhpWebshellProvider,
)
from dsp.execution.webshell.transport import MockHttpTransport


def test_provider_creation(php_provider: PhpWebshellProvider):
    assert isinstance(php_provider, PhpWebshellProvider)


def test_provider_metadata_values(php_provider: PhpWebshellProvider):
    assert php_provider.provider_type == "php"
    assert php_provider.provider_name == "PHP Webshell Provider"
    assert php_provider.provider_version == "1.0.0"

    metadata = php_provider.get_metadata()
    assert metadata["provider_type"] == "php"
    assert metadata["provider_name"] == "PHP Webshell Provider"
    assert metadata["provider_version"] == "1.0.0"
    assert metadata["reserved"] is True


def test_capability_defaults(php_provider: PhpWebshellProvider):
    caps = php_provider.get_capabilities()
    assert caps.upload_supported is True
    assert caps.download_supported is True
    assert caps.execute_supported is True
    assert caps.event_sync_supported is True
    assert caps.transport_supported is True


def test_transport_injection(mock_transport: MockHttpTransport):
    provider = PhpWebshellProvider(transport=mock_transport)
    assert provider.transport is mock_transport


def test_configuration_validation_success(
    php_provider: PhpWebshellProvider,
    valid_php_config: ProviderConfiguration,
):
    php_provider.validate_configuration(valid_php_config)


@pytest.mark.parametrize(
    "config,match",
    [
        (
            ProviderConfiguration(provider_type="jsp", transport_type="https"),
            "provider_type mismatch",
        ),
        (
            ProviderConfiguration(provider_type="php", transport_type=""),
            "transport_type",
        ),
        (
            ProviderConfiguration(provider_type="php", transport_type="ftp"),
            "transport_type",
        ),
        (
            ProviderConfiguration(provider_type="php", timeout_profile=""),
            "timeout_profile",
        ),
        (
            ProviderConfiguration(
                provider_type="php",
                transport_type="https",
                timeout_profile="invalid_profile",
            ),
            "timeout_profile",
        ),
    ],
)
def test_configuration_validation_failure(
    php_provider: PhpWebshellProvider,
    config: ProviderConfiguration,
    match: str,
):
    with pytest.raises(ProviderConfigurationError, match=match):
        php_provider.validate_configuration(config)


def test_session_creation(php_provider: PhpWebshellProvider):
    session = php_provider.create_session()
    assert isinstance(session, PhpProviderSession)
    assert session.provider_type == "php"
    assert session.state == ProviderSessionState.CREATED
    assert session.webshell_url == "https://lab.example/shell.php"
    assert session.transport_type == "https"
    assert session.provider_version == PHP_PROVIDER_VERSION
    assert session.session_id


def test_factory_php_support(mock_transport: MockHttpTransport):
    provider = create_webshell_provider("php", transport=mock_transport)
    assert isinstance(provider, PhpWebshellProvider)
    assert provider.transport is mock_transport


def test_registry_registration():
    registry = WebshellProviderRegistry()
    registry.register_provider("php", PhpWebshellProvider)
    assert registry.get_provider("php") is PhpWebshellProvider
    assert registry.list_providers() == ["php"]


def test_provider_isolation(mock_transport: MockHttpTransport):
    """No transport, network, or event sync invocation during provider use."""
    transport = MagicMock(spec=MockHttpTransport)
    transport.send_get = MagicMock()
    transport.send_post = MagicMock()
    transport.send_upload = MagicMock()
    transport.download = MagicMock()
    transport.healthcheck = MagicMock()

    provider = PhpWebshellProvider(transport=transport)
    provider.get_metadata()
    provider.get_capabilities()
    provider.validate_configuration(
        ProviderConfiguration(provider_type="php", transport_type="https")
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
    provider = PhpWebshellProvider(
        transport=mock_transport,
        webshell_url="https://lab.example/shell.php",
    )
    provider.get_metadata()
    provider.get_capabilities()
    provider.validate_configuration(
        ProviderConfiguration(provider_type="php", transport_type="https")
    )
    provider.create_session()

    assert mock_transport.calls == []
