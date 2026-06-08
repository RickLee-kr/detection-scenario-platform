"""Provider exception hierarchy tests."""

from __future__ import annotations

from dsp.execution.providers.webshell import (
    ProviderConfigurationError,
    ProviderNotSupportedError,
    ProviderSessionError,
    WebshellProviderError,
)


def test_exception_hierarchy():
    assert issubclass(ProviderConfigurationError, WebshellProviderError)
    assert issubclass(ProviderNotSupportedError, WebshellProviderError)
    assert issubclass(ProviderSessionError, WebshellProviderError)


def test_configuration_error_carries_field():
    exc = ProviderConfigurationError("bad config", field="provider_type")
    assert exc.field == "provider_type"


def test_not_supported_error_carries_provider_type():
    exc = ProviderNotSupportedError("missing", provider_type="jsp")
    assert exc.provider_type == "jsp"


def test_session_error_carries_session_context():
    exc = ProviderSessionError("bad state", session_id="abc", state="error")
    assert exc.session_id == "abc"
    assert exc.state == "error"
