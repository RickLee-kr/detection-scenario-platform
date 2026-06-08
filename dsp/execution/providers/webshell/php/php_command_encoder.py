"""PHP webshell command encoder — ``cmd`` GET/POST parameter format."""

from __future__ import annotations

from dsp.execution.providers.runtime.command import CommandEncoder, CommandRequest


class PhpCommandEncoder(CommandEncoder):
    """Encode command requests for PHP shells using the ``cmd`` parameter.

    PHP shells accept ``shell.php?cmd=whoami`` (GET) or POST body ``cmd=whoami``.
    Returns the command line string; transport layer maps it to HTTP parameters.
    """

    COMMAND_PARAM = "cmd"

    def format_command_line(self, request: CommandRequest) -> str:
        """Build a shell command line from request metadata."""
        command = request.command.strip()
        if not command:
            return ""
        if request.arguments:
            return " ".join([command, *request.arguments])
        return command

    def encode_request(
        self,
        request: CommandRequest,
        *,
        encoding: str = "json",
    ) -> str:
        """Return the PHP command line string (not JSON)."""
        self._require_encoding(encoding)
        return self.format_command_line(request)

    def encode_shell_command(self, request: CommandRequest) -> str:
        """Alias for transport dispatch — explicit PHP naming."""
        return self.format_command_line(request)
