"""Webshell provider factory tests."""

from __future__ import annotations

import pytest

from dsp.execution.providers.webshell import (
    ProviderNotSupportedError,
    RESERVED_PROVIDER_TYPES,
    create_webshell_provider,
)
from dsp.execution.providers.webshell.aspx import AspxWebshellProvider
from dsp.execution.providers.webshell.jsp import JspWebshellProvider
from dsp.execution.providers.webshell.php import PhpWebshellProvider


@pytest.mark.parametrize(
    "provider_type,expected_cls",
    [
        ("jsp", JspWebshellProvider),
        ("php", PhpWebshellProvider),
        ("aspx", AspxWebshellProvider),
    ],
)
def test_factory_reserved_providers(provider_type, expected_cls):
    provider = create_webshell_provider(provider_type)
    assert isinstance(provider, expected_cls)
    assert provider.provider_type == provider_type
    assert provider_type in RESERVED_PROVIDER_TYPES


def test_factory_unsupported_provider_raises():
    with pytest.raises(ProviderNotSupportedError) as exc_info:
        create_webshell_provider("unknown")
    assert exc_info.value.provider_type == "unknown"
