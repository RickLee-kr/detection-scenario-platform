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

    def __init__(
        self,
        message: str,
        *,
        diagnostics_dir: str | None = None,
        remote_validation: object | None = None,
        cat_validation: object | None = None,
    ) -> None:
        self.diagnostics_dir = diagnostics_dir
        self.remote_validation = remote_validation
        self.cat_validation = cat_validation
        super().__init__(message)
