"""Execution provider exceptions."""


class UnsupportedExecutionProviderError(ValueError):
    """Raised when an unknown execution provider is requested."""

    def __init__(self, provider_type: str) -> None:
        self.provider_type = provider_type
        super().__init__(f"unsupported execution provider: {provider_type}")


class WebshellExecutionConfigError(ValueError):
    """Raised when webshell execution provider configuration is invalid."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.field = field
        suffix = f" ({field})" if field else ""
        super().__init__(f"{message}{suffix}")
