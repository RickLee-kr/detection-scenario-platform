"""Execution provider framework — pluggable traffic origin abstraction."""

from dsp.execution.base import ExecutionProvider
from dsp.execution.exceptions import (
    UnsupportedExecutionProviderError,
    WebshellExecutionConfigError,
)
from dsp.execution.factory import (
    DEFAULT_PROVIDER_TYPE,
    FUTURE_PROVIDERS,
    SUPPORTED_PROVIDERS,
    create_execution_provider,
)
from dsp.execution.local_provider import LocalExecutionProvider
from dsp.execution.models import ExecutionContext, ProviderCapabilities
from dsp.execution.webshell_config import (
    SUPPORTED_WEBSHELL_FAMILIES,
    WebshellExecutionConfig,
)
from dsp.execution.webshell_provider import WebshellExecutionProvider

__all__ = [
    "DEFAULT_PROVIDER_TYPE",
    "ExecutionContext",
    "ExecutionProvider",
    "FUTURE_PROVIDERS",
    "LocalExecutionProvider",
    "ProviderCapabilities",
    "SUPPORTED_PROVIDERS",
    "SUPPORTED_WEBSHELL_FAMILIES",
    "UnsupportedExecutionProviderError",
    "WebshellExecutionConfig",
    "WebshellExecutionConfigError",
    "WebshellExecutionProvider",
    "create_execution_provider",
]
