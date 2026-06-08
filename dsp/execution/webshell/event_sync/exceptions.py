"""Event sync exception hierarchy."""


class EventSyncError(Exception):
    """Base exception for event synchronization errors."""


class BundleNotFoundError(EventSyncError):
    """Bundle file does not exist or is not readable."""

    def __init__(self, message: str, *, path: str | None = None) -> None:
        self.path = path
        super().__init__(message)


class BundleValidationError(EventSyncError):
    """Bundle failed structural validation."""

    def __init__(
        self,
        message: str,
        *,
        rule: str | None = None,
        line_number: int | None = None,
    ) -> None:
        self.rule = rule
        self.line_number = line_number
        super().__init__(message)


class BundleSchemaError(EventSyncError):
    """Bundle schema version is unsupported or mismatched."""

    def __init__(
        self,
        message: str,
        *,
        schema_version: str | None = None,
        expected: str | None = None,
    ) -> None:
        self.schema_version = schema_version
        self.expected = expected
        super().__init__(message)


class EventImportError(EventSyncError):
    """Single event could not be imported into Event Store."""

    def __init__(
        self,
        message: str,
        *,
        line_number: int | None = None,
        event_name: str | None = None,
    ) -> None:
        self.line_number = line_number
        self.event_name = event_name
        super().__init__(message)
