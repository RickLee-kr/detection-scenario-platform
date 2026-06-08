"""JSP webshell command encoding — cmd parameter only, no response parsing."""

from __future__ import annotations

from dsp.execution.providers.runtime.command import CommandEncoder, CommandRequest


class JspCommandEncoder(CommandEncoder):
    """Encode command requests for JSP shells using the ``cmd`` parameter.

    JSP shells accept ``shell.jsp?cmd=whoami`` (GET) or POST body ``cmd=whoami``.
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
        """Return the JSP command line string (not JSON)."""
        self._require_encoding(encoding)
        return self.format_command_line(request)

    def encode_shell_command(self, request: CommandRequest) -> str:
        """Alias for transport dispatch — explicit JSP naming."""
        return self.format_command_line(request)
