"""Remote scenario execution exceptions."""

from __future__ import annotations


class RemoteScenarioRunnerError(Exception):
    """Base exception for remote scenario runner errors."""


class UnsupportedRemoteProviderError(RemoteScenarioRunnerError, TypeError):
    """Raised when a provider does not support remote scenario execution."""

    def __init__(self, provider_type: str) -> None:
        self.provider_type = provider_type
        super().__init__(
            f"unsupported remote scenario provider: {provider_type!r}; "
            "expected WebshellExecutionProvider"
        )


class RemoteEventCollectionError(Exception):
    """Base exception for remote event collection errors."""
