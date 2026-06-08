"""Provider models and configuration validation tests."""

from __future__ import annotations

import pytest

from dsp.execution.providers.webshell import (
    ProviderCapabilities,
    ProviderConfiguration,
    ProviderConfigurationError,
    ProviderSessionState,
)
from dsp.execution.providers.webshell.provider_models import ProviderSession
from dsp.execution.webshell.transport.timeout import TIMEOUT_PROFILE_FAST
def test_capability_defaults():
    caps = ProviderCapabilities()
    assert caps.upload_supported is False
    assert caps.download_supported is False
    assert caps.execute_supported is False
    assert caps.event_sync_supported is False
    assert caps.transport_supported is False


def test_capabilities_roundtrip():
    original = ProviderCapabilities(
        upload_supported=True,
        download_supported=True,
        execute_supported=True,
        event_sync_supported=True,
        transport_supported=True,
    )
    restored = ProviderCapabilities.from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()


def test_configuration_validation_success(stub_provider, valid_config):
    stub_provider.validate_configuration(valid_config)


def test_configuration_validation_provider_type_mismatch(stub_provider):
    config = ProviderConfiguration(provider_type="other")
    with pytest.raises(ProviderConfigurationError, match="provider_type mismatch"):
        stub_provider.validate_configuration(config)


def test_configuration_validation_transport_type(stub_provider):
    config = ProviderConfiguration(provider_type="stub", transport_type="ftp")
    with pytest.raises(ProviderConfigurationError, match="transport_type"):
        stub_provider.validate_configuration(config)


def test_configuration_validation_timeout_profile(stub_provider):
    config = ProviderConfiguration(
        provider_type="stub",
        timeout_profile="invalid_profile",
    )
    with pytest.raises(ProviderConfigurationError, match="timeout_profile"):
        stub_provider.validate_configuration(config)


def test_session_lifecycle():
    session = ProviderSession.new("stub")
    assert session.state == ProviderSessionState.CREATED
    assert session.provider_type == "stub"
    assert session.session_id

    connected = session.transition(ProviderSessionState.CONNECTED)
    assert connected.state == ProviderSessionState.CONNECTED
    assert connected.session_id == session.session_id

    closed = connected.transition(ProviderSessionState.CLOSED)
    assert closed.state == ProviderSessionState.CLOSED

    error = closed.transition(ProviderSessionState.ERROR)
    assert error.state == ProviderSessionState.ERROR


def test_session_roundtrip():
    session = ProviderSession.new("stub", state=ProviderSessionState.CONNECTED)
    restored = ProviderSession.from_dict(session.to_dict())
    assert restored.to_dict() == session.to_dict()


def test_configuration_roundtrip():
    original = ProviderConfiguration(
        provider_type="stub",
        transport_type="http",
        safe_mode=False,
        timeout_profile=TIMEOUT_PROFILE_FAST,
        metadata={"lab": "xdr"},
    )
    restored = ProviderConfiguration.from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()


def test_provider_metadata(stub_provider):
    metadata = stub_provider.get_metadata()
    assert metadata["provider_type"] == "stub"
    assert metadata["provider_name"] == "Stub Provider"
    assert metadata["reserved"] is False
    assert metadata["capabilities"] == ProviderCapabilities().to_dict()


def test_create_session_returns_created_state(stub_provider):
    session = stub_provider.create_session()
    assert session.state == ProviderSessionState.CREATED
    assert session.provider_type == "stub"
