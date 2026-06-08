"""JSP webshell execution tests — mocked backend only, no live network."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dsp.execution.providers.runtime.command import (
    CommandRequest,
    CommandStatus,
    CommandTransportError,
)
from dsp.execution.providers.runtime.command import CommandExecutionPolicy
from dsp.execution.providers.runtime.transport import TransportRuntimeConfiguration
from dsp.execution.providers.webshell.jsp import (
    JspCommandEncoder,
    JspProviderNotReadyError,
    JspWebshellProvider,
    JspWebshellRuntime,
)
from dsp.execution.webshell.transport import (
    RealHttpTransport,
    RetryPolicy,
    TransportRequest,
    WebshellTransportTimeoutError,
)
from dsp.execution.webshell.transport.real_http_transport import HttpBackendResponse


@dataclass
class RecordingHttpBackend:
    responses: list[HttpBackendResponse | Exception] = field(default_factory=list)
    calls: list[dict[str, object]] = field(default_factory=list)
    _index: int = 0

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> HttpBackendResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": body,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self._index >= len(self.responses):
            raise AssertionError(f"no scripted response for call {self._index + 1}")
        scripted = self.responses[self._index]
        self._index += 1
        if isinstance(scripted, Exception):
            raise scripted
        return scripted


def _ok(body: bytes = b"jsp-output", **headers: str) -> HttpBackendResponse:
    merged = {"content-type": "text/html", **headers}
    return HttpBackendResponse(status_code=200, headers=merged, body=body)


def _connected_provider(
    backend: RecordingHttpBackend,
    *,
    enable_healthcheck: bool = False,
    retry_policy: RetryPolicy | None = None,
) -> JspWebshellProvider:
    transport = RealHttpTransport(
        backend=backend,
        retry_policy=retry_policy or RetryPolicy(max_retries=0),
    )
    provider = JspWebshellProvider(
        transport=transport,
        webshell_url="https://lab.example/shell.jsp",
    )
    provider.create_runtime(
        config=TransportRuntimeConfiguration(
            enable_healthcheck_on_connect=enable_healthcheck,
            command_policy=CommandExecutionPolicy(allow_command_execution=True),
        ),
    )
    provider.connect()
    return provider


def test_jsp_execute_get_cmd_param():
    backend = RecordingHttpBackend(responses=[_ok(b"root\n")])
    provider = _connected_provider(backend)
    result = provider.execute_command("whoami")
    assert result.status == CommandStatus.COMPLETED
    call = backend.calls[-1]
    assert call["method"] == "GET"
    assert "cmd=whoami" in str(call["url"])
    assert result.execution_metadata["transport_method"] == "send_get"
    assert result.execution_metadata["jsp_command_param"] == "cmd"


def test_jsp_execute_post_cmd_form():
    backend = RecordingHttpBackend(responses=[_ok()])
    provider = _connected_provider(backend)
    large_arg = "x" * 3000
    result = provider.execute_command("run", arguments=[large_arg])
    call = backend.calls[-1]
    assert call["method"] == "POST"
    assert call["body"] == f"cmd=run+{large_arg}".encode()
    assert result.execution_metadata["transport_method"] == "send_post"


def test_command_payload_propagation():
    backend = RecordingHttpBackend(responses=[_ok()])
    provider = _connected_provider(backend)
    provider.execute_command("echo", arguments=["hello", "world"])
    assert "cmd=echo+hello+world" in str(backend.calls[-1]["url"])


def test_response_passthrough_without_parsing():
    backend = RecordingHttpBackend(responses=[_ok(b"root\nuid=0", x_exit="0")])
    provider = _connected_provider(backend)
    result = provider.execute_command("id")
    metadata = result.execution_metadata
    assert metadata["transport_response_size"] == len(b"root\nuid=0")
    assert metadata["transport_status"] == 200
    forbidden = {"stdout", "stderr", "output", "parsed_output", "execution_success"}
    assert forbidden.isdisjoint(metadata.keys())
    assert "root" not in str(metadata)


def test_upload_file_invocation(tmp_path: Path):
    local = tmp_path / "payload.txt"
    local.write_text("data")
    backend = RecordingHttpBackend(responses=[_ok(b"uploaded")])
    provider = _connected_provider(backend)
    artifact = provider.upload_file(local, "/tmp/dsp_stub/run01/payload.txt")
    assert artifact.transfer_status == "uploaded"
    call = backend.calls[-1]
    assert call["method"] == "POST"
    assert b"payload.txt" in call["body"]  # type: ignore[operator]
    assert b"/tmp/dsp_stub/run01/payload.txt" in call["body"]  # type: ignore[operator]


def test_download_file_invocation():
    backend = RecordingHttpBackend(responses=[_ok(b"file-bytes")])
    provider = _connected_provider(backend)
    artifact = provider.download_file("/tmp/dsp_stub/run01/events.jsonl")
    assert artifact.transfer_status == "downloaded"
    assert "remote_path=%2Ftmp%2Fdsp_stub%2Frun01%2Fevents.jsonl" in str(
        backend.calls[-1]["url"]
    )


def test_cleanup_invocation():
    backend = RecordingHttpBackend(responses=[_ok()])
    provider = _connected_provider(backend)
    runtime = provider.get_runtime()
    assert isinstance(runtime, JspWebshellRuntime)
    provider.cleanup()
    with pytest.raises(Exception):
        runtime.active_session


def test_timeout_propagation():
    backend = RecordingHttpBackend(
        responses=[
            WebshellTransportTimeoutError(
                "request timeout after 10.0s",
                url="https://lab.example/shell.jsp",
                timeout_seconds=10.0,
            )
        ]
    )
    provider = _connected_provider(backend)
    with pytest.raises(CommandTransportError, match="execute_command timed out"):
        provider.execute_command("id")


def test_retry_propagation_on_5xx():
    backend = RecordingHttpBackend(
        responses=[
            HttpBackendResponse(status_code=503, headers={}, body=b"down"),
            _ok(b"ok"),
        ]
    )
    transport = RealHttpTransport(
        backend=backend,
        retry_policy=RetryPolicy(max_retries=1, backoff_seconds=0, retry_on_http_5xx=True),
    )
    provider = JspWebshellProvider(
        transport=transport,
        webshell_url="https://lab.example/shell.jsp",
    )
    provider.create_runtime(
        config=TransportRuntimeConfiguration(
            enable_healthcheck_on_connect=False,
            command_policy=CommandExecutionPolicy(allow_command_execution=True),
        ),
    )
    provider.connect()
    result = provider.execute_command("hostname")
    assert result.status == CommandStatus.COMPLETED
    assert len(backend.calls) == 2


def test_transport_exception_propagation():
    backend = RecordingHttpBackend(
        responses=[HttpBackendResponse(status_code=401, headers={}, body=b"denied")]
    )
    provider = _connected_provider(backend)
    with pytest.raises(CommandTransportError, match="execute_command rejected"):
        provider.execute_command("id")


def test_execute_without_runtime_raises():
    provider = JspWebshellProvider(
        transport=MagicMock(),
        webshell_url="https://lab.example/shell.jsp",
    )
    with pytest.raises(JspProviderNotReadyError, match="create_runtime"):
        provider.execute_command("id")


def test_no_success_inference():
    source = inspect.getsource(JspWebshellRuntime.execute_command)
    lowered = source.lower()
    for token in (
        "execution_success",
        "command_succeeded",
        "attack_success",
        "detection",
        "alert",
        "correlation",
    ):
        assert token not in lowered


def test_no_stdout_stderr_parsing_in_runtime():
    source = inspect.getsource(
        __import__(
            "dsp.execution.providers.webshell.jsp.jsp_runtime",
            fromlist=["JspWebshellRuntime"],
        )
    )
    lowered = source.lower()
    assert "stdout" not in lowered
    assert "stderr" not in lowered
    assert "grep" not in lowered


def test_jsp_command_encoder_format():
    encoder = JspCommandEncoder()
    line = encoder.format_command_line(CommandRequest.new("whoami"))
    assert line == "whoami"
    line_with_args = encoder.format_command_line(
        CommandRequest.new("echo", arguments=["a", "b"])
    )
    assert line_with_args == "echo a b"


def test_transport_request_preserves_response_headers():
    backend = RecordingHttpBackend(
        responses=[
            _ok(b"cmd-out", **{"x-custom": "preserved"}),
            _ok(b"probe", **{"x-custom": "preserved"}),
        ]
    )
    provider = _connected_provider(backend)
    result = provider.execute_command("id")
    assert result.execution_metadata["transport_status"] == 200
    runtime = provider.get_runtime()
    assert isinstance(runtime, JspWebshellRuntime)
    response = runtime.transport.send_get(
        TransportRequest(url="https://lab.example/shell.jsp")
    )
    assert response.headers.get("x-custom") == "preserved"
    assert response.body == b"probe"
