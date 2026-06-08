"""Webshell provider exception hierarchy."""


class WebshellError(Exception):
    """Base exception for webshell provider errors."""


class WebshellConnectionError(WebshellError):
    """Webshell endpoint unreachable or transport failure."""

    def __init__(self, message: str, *, url: str | None = None) -> None:
        self.url = url
        super().__init__(message)


class WebshellAuthenticationError(WebshellError):
    """Authentication or authorization failure."""

    def __init__(self, message: str, *, mode: str | None = None) -> None:
        self.mode = mode
        super().__init__(message)


class WebshellExecutionError(WebshellError):
    """Remote command execution failed at transport layer."""

    def __init__(
        self,
        message: str,
        *,
        command: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        self.command = command
        self.exit_code = exit_code
        super().__init__(message)


class WebshellUploadError(WebshellError):
    """File upload to remote host failed."""

    def __init__(
        self,
        message: str,
        *,
        local_path: str | None = None,
        remote_path: str | None = None,
    ) -> None:
        self.local_path = local_path
        self.remote_path = remote_path
        super().__init__(message)


class WebshellDownloadError(WebshellError):
    """File download from remote host failed."""

    def __init__(self, message: str, *, remote_path: str | None = None) -> None:
        self.remote_path = remote_path
        super().__init__(message)


class WebshellSecurityViolation(WebshellError):
    """Operation blocked by security policy."""

    def __init__(self, message: str, *, rule: str | None = None) -> None:
        self.rule = rule
        super().__init__(message)
