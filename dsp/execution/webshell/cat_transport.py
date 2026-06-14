"""Webshell ``cat`` transport helper for remote file reads."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from dsp.execution.providers.runtime.command import CommandRequest
from dsp.execution.webshell.event_sync.bundle_content import strip_webshell_exit_marker

if TYPE_CHECKING:
    from dsp.execution.providers.runtime.transport import TransportBackedRuntime


def read_remote_file_via_cat(
    runtime: TransportBackedRuntime,
    remote_path: str,
) -> bytes:
    """Fetch a remote file through the webshell ``cat`` command transport."""
    session = runtime._active_session()
    runtime._require_connected(session, operation="read_remote_file_via_cat")
    cat_command = f"cat {shlex.quote(remote_path)}"
    command = CommandRequest.new(cat_command)
    encoded_payload = runtime._command_encoder.encode_request(command)
    transport_request = runtime._command_transport_request(
        encoded_payload,
        transport_method="send_get",
        timeout_seconds=300.0,
    )
    response = runtime._dispatch_command(
        "read_remote_file_via_cat",
        command.command_id,
        lambda: runtime._transport.send_get(transport_request),
    )
    return strip_webshell_exit_marker(response.body)
