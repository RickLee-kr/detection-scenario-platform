"""Webshell provider family exception hierarchy."""


class WebshellProviderError(Exception):
    """Base exception for webshell provider family errors."""


class ProviderConfigurationError(WebshellProviderError):
    """Provider or registry configuration is invalid."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)


class ProviderNotSupportedError(WebshellProviderError):
    """Requested provider type is not registered or not reserved."""

    def __init__(self, message: str, *, provider_type: str | None = None) -> None:
        self.provider_type = provider_type
        super().__init__(message)


class ProviderSessionError(WebshellProviderError):
    """Provider session lifecycle error."""

    def __init__(
        self,
        message: str,
        *,
        session_id: str | None = None,
        state: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.state = state
        super().__init__(message)
