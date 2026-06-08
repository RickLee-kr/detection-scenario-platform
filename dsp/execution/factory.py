"""Execution provider factory."""

from __future__ import annotations

from typing import Any

from dsp.execution.base import ExecutionProvider
from dsp.execution.exceptions import UnsupportedExecutionProviderError
from dsp.execution.local_provider import LocalExecutionProvider
from dsp.execution.webshell_provider import WebshellExecutionProvider

SUPPORTED_PROVIDERS = frozenset({"local", "webshell"})
FUTURE_PROVIDERS = frozenset({"ssh", "agent"})
DEFAULT_PROVIDER_TYPE = "local"


def _create_webshell_provider(**provider_config: Any) -> WebshellExecutionProvider:
    return WebshellExecutionProvider.from_config(**provider_config)


def create_execution_provider(
    provider_type: str = DEFAULT_PROVIDER_TYPE,
    **provider_config: Any,
) -> ExecutionProvider:
    """Instantiate an execution provider for the given type."""
    if provider_type == "local":
        return LocalExecutionProvider()

    if provider_type == "webshell":
        return _create_webshell_provider(**provider_config)

    if provider_type in FUTURE_PROVIDERS:
        raise NotImplementedError(f"execution provider not implemented: {provider_type}")

    raise UnsupportedExecutionProviderError(provider_type)
