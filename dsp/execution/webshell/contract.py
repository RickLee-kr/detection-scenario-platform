"""WebshellContract ABC — family-agnostic transport interface (no implementation)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from dsp.execution.webshell.models import (
    WebshellCommand,
    WebshellCommandResult,
    WebshellHealthResult,
    WebshellTransferResult,
)


class WebshellContract(ABC):
    """Family-agnostic webshell transport contract.

    JSP, PHP, ASPX, and generic HTTP adapters implement this interface.
    No HTTP or network logic in this module — contract only.
    """

    @abstractmethod
    def healthcheck(self) -> WebshellHealthResult:
        """Verify webshell reachability and detect family if possible."""

    @abstractmethod
    def execute(self, command: str | WebshellCommand) -> WebshellCommandResult:
        """Run a shell command on the remote host via webshell."""

    @abstractmethod
    def upload(self, local_file: Path, remote_path: str) -> WebshellTransferResult:
        """Upload a file from DSP Host to the remote host."""

    @abstractmethod
    def download(self, remote_path: str) -> WebshellTransferResult:
        """Download a file from the remote host."""

    @abstractmethod
    def cleanup(self) -> None:
        """Remove staged artifacts and release transport resources."""

    @abstractmethod
    def capture_stdout(self, result: WebshellCommandResult) -> str:
        """Normalize stdout from family-specific response wrapping."""

    @abstractmethod
    def capture_stderr(self, result: WebshellCommandResult) -> str:
        """Normalize stderr from family-specific response wrapping."""
