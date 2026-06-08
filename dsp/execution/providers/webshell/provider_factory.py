"""Webshell provider factory — JSP/PHP/ASPX adapters."""

from __future__ import annotations

from typing import Any

from dsp.execution.providers.webshell.base_provider import WebshellProviderBase
from dsp.execution.providers.webshell.provider_exceptions import (
    ProviderNotSupportedError,
)
from dsp.execution.providers.webshell.provider_models import RESERVED_PROVIDER_TYPES

_IMPLEMENTED_PROVIDER_TYPES: frozenset[str] = frozenset({"jsp", "php", "aspx"})


def create_webshell_provider(
    provider_type: str,
    **provider_config: Any,
) -> WebshellProviderBase:
    """Instantiate a webshell family provider.

    ``jsp`` returns ``JspWebshellProvider``. ``php`` returns
    ``PhpWebshellProvider``. ``aspx`` returns ``AspxWebshellProvider``.
    Unknown types raise ``ProviderNotSupportedError``.
    """
    normalized = provider_type.strip().lower()

    if normalized in RESERVED_PROVIDER_TYPES:
        if normalized not in _IMPLEMENTED_PROVIDER_TYPES:
            raise NotImplementedError(
                f"webshell provider not implemented: {normalized}"
            )
        if normalized == "jsp":
            from dsp.execution.providers.webshell.jsp.provider import (
                JspWebshellProvider,
            )

            return JspWebshellProvider(**provider_config)
        if normalized == "php":
            from dsp.execution.providers.webshell.php.provider import (
                PhpWebshellProvider,
            )

            return PhpWebshellProvider(**provider_config)
        if normalized == "aspx":
            from dsp.execution.providers.webshell.aspx.provider import (
                AspxWebshellProvider,
            )

            return AspxWebshellProvider(**provider_config)

    raise ProviderNotSupportedError(
        f"unsupported webshell provider: {provider_type!r}",
        provider_type=provider_type,
    )
