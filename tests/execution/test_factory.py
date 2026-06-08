"""Execution provider factory tests."""

from __future__ import annotations

import pytest

from dsp.execution import (
    DEFAULT_PROVIDER_TYPE,
    FUTURE_PROVIDERS,
    SUPPORTED_PROVIDERS,
    LocalExecutionProvider,
    UnsupportedExecutionProviderError,
    create_execution_provider,
)


def test_default_provider_is_local():
    provider = create_execution_provider()
    assert isinstance(provider, LocalExecutionProvider)
    assert provider.provider_type == DEFAULT_PROVIDER_TYPE


def test_create_local_provider():
    provider = create_execution_provider("local")
    assert isinstance(provider, LocalExecutionProvider)
    assert provider.provider_type == "local"


@pytest.mark.parametrize("provider_type", sorted(FUTURE_PROVIDERS))
def test_future_providers_raise_not_implemented(provider_type: str):
    with pytest.raises(NotImplementedError, match=provider_type):
        create_execution_provider(provider_type)


def test_unknown_provider_raises():
    with pytest.raises(UnsupportedExecutionProviderError) as exc_info:
        create_execution_provider("unknown")
    assert exc_info.value.provider_type == "unknown"


def test_supported_providers_contains_local_and_webshell():
    assert SUPPORTED_PROVIDERS == frozenset({"local", "webshell"})
    assert "local" in SUPPORTED_PROVIDERS
    assert "webshell" in SUPPORTED_PROVIDERS
