"""Webshell execution provider contract — Phase X+1A (no transport implementation)."""

from dsp.execution.webshell.capabilities import WebshellCapabilities
from dsp.execution.webshell.contract import WebshellContract
from dsp.execution.webshell.exceptions import (
    WebshellAuthenticationError,
    WebshellConnectionError,
    WebshellDownloadError,
    WebshellError,
    WebshellExecutionError,
    WebshellSecurityViolation,
    WebshellUploadError,
)
from dsp.execution.webshell.models import (
    WebshellCommand,
    WebshellCommandResult,
    WebshellHealthResult,
    WebshellSession,
    WebshellTransferResult,
)
from dsp.execution.webshell.security import (
    WebshellSecurityPolicy,
    validate_command_allowed,
    validate_download_allowed,
    validate_execute_allowed,
    validate_file_size_allowed,
    validate_local_file_allowed,
    validate_remote_path_allowed,
    validate_upload_allowed,
)

__all__ = [
    "WebshellAuthenticationError",
    "WebshellCapabilities",
    "WebshellCommand",
    "WebshellCommandResult",
    "WebshellConnectionError",
    "WebshellContract",
    "WebshellDownloadError",
    "WebshellError",
    "WebshellExecutionError",
    "WebshellHealthResult",
    "WebshellSecurityPolicy",
    "WebshellSecurityViolation",
    "WebshellSession",
    "WebshellTransferResult",
    "WebshellUploadError",
    "validate_command_allowed",
    "validate_download_allowed",
    "validate_execute_allowed",
    "validate_file_size_allowed",
    "validate_local_file_allowed",
    "validate_remote_path_allowed",
    "validate_upload_allowed",
]
