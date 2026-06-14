"""JSP/PHP/ASPX provider family parity tests — mocked backend only."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from dsp.execution.providers.runtime.command import CommandExecutionPolicy, CommandStatus
from dsp.execution.providers.runtime.transport import TransportRuntimeConfiguration
from dsp.execution.providers.webshell import (
    WebshellProviderRegistry,
    create_webshell_provider,
)
from dsp.execution.providers.webshell.aspx import (
    AspxProviderNotReadyError,
    AspxWebshellProvider,
    AspxWebshellRuntime,
)
from dsp.execution.providers.webshell.jsp import (
    JspProviderNotReadyError,
    JspWebshellProvider,
    JspWebshellRuntime,
)
from dsp.execution.providers.webshell.php import (
    PhpProviderNotReadyError,
    PhpWebshellProvider,
    PhpWebshellRuntime,
)
from dsp.execution.webshell.transport import RealHttpTransport, RetryPolicy
from dsp.execution.webshell.transport.real_http_transport import HttpBackendResponse

EXECUTION_METHODS = (
    "create_runtime",
    "connect",
    "execute_command",
    "upload_file",
    "download_file",
    "cleanup",
)

COMMON_METADATA_KEYS = frozenset(
    {
        "transport_method",
        "request_size",
        "transport_status",
        "transport_response_size",
        "transport_duration_ms",
        "delivery_only",
    }
)

FORBIDDEN_INFERENCE_TOKENS = (
    "execution_success",
    "command_succeeded",
    "attack_success",
    "detection",
    "alert",
    "correlation",
)

FORBIDDEN_METADATA_KEYS = frozenset(
    {"stdout", "stderr", "output", "parsed_output", "execution_success"}
)

PROVIDER_FAMILY_CASES = [
    pytest.param(
        "jsp",
        JspWebshellProvider,
        JspWebshellRuntime,
        JspProviderNotReadyError,
        "shell.jsp",
        "jsp_command_param",
        id="jsp",
    ),
    pytest.param(
        "php",
        PhpWebshellProvider,
        PhpWebshellRuntime,
        PhpProviderNotReadyError,
        "shell.php",
        "php_command_param",
        id="php",
    ),
    pytest.param(
        "aspx",
        AspxWebshellProvider,
        AspxWebshellRuntime,
        AspxProviderNotReadyError,
        "shell.aspx",
        "aspx_command_param",
        id="aspx",
    ),
]


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


def _ok(body: bytes = b"output") -> HttpBackendResponse:
    return HttpBackendResponse(
        status_code=200,
        headers={"content-type": "text/html"},
        body=body,
    )


def _connected_provider(
    provider_cls: type,
    shell_name: str,
    backend: RecordingHttpBackend,
) -> Any:
    transport = RealHttpTransport(
        backend=backend,
        retry_policy=RetryPolicy(max_retries=0),
    )
    provider = provider_cls(
        transport=transport,
        webshell_url=f"https://lab.example/{shell_name}",
    )
    provider.create_runtime(
        config=TransportRuntimeConfiguration(
            enable_healthcheck_on_connect=False,
            command_policy=CommandExecutionPolicy(allow_command_execution=True),
        ),
    )
    provider.connect()
    return provider


@pytest.mark.parametrize(
    "provider_type,provider_cls,runtime_cls,not_ready_error,shell_name,command_param_key",
    PROVIDER_FAMILY_CASES,
)
def test_family_exposes_execution_methods(
    provider_type: str,
    provider_cls: type,
    runtime_cls: type,
    not_ready_error: type,
    shell_name: str,
    command_param_key: str,
):
    provider = provider_cls(
        transport=MagicMock(),
        webshell_url=f"https://lab.example/{shell_name}",
    )
    for method_name in EXECUTION_METHODS:
        assert hasattr(provider, method_name), f"{provider_type} missing {method_name}"
        assert callable(getattr(provider, method_name))


@pytest.mark.parametrize(
    "provider_type,provider_cls,runtime_cls,not_ready_error,shell_name,command_param_key",
    PROVIDER_FAMILY_CASES,
)
def test_family_execute_get_small_command(
    provider_type: str,
    provider_cls: type,
    runtime_cls: type,
    not_ready_error: type,
    shell_name: str,
    command_param_key: str,
):
    backend = RecordingHttpBackend(responses=[_ok()])
    provider = _connected_provider(provider_cls, shell_name, backend)
    result = provider.execute_command("whoami")
    assert result.status == CommandStatus.COMPLETED
    assert backend.calls[-1]["method"] == "GET"
    assert "cmd=whoami" in str(backend.calls[-1]["url"])
    assert result.execution_metadata["transport_method"] == "send_get"
    assert result.execution_metadata[command_param_key] == "cmd"


@pytest.mark.parametrize(
    "provider_type,provider_cls,runtime_cls,not_ready_error,shell_name,command_param_key",
    PROVIDER_FAMILY_CASES,
)
def test_family_execute_post_large_command(
    provider_type: str,
    provider_cls: type,
    runtime_cls: type,
    not_ready_error: type,
    shell_name: str,
    command_param_key: str,
):
    backend = RecordingHttpBackend(responses=[_ok()])
    provider = _connected_provider(provider_cls, shell_name, backend)
    large_arg = "x" * 3000
    result = provider.execute_command("run", arguments=[large_arg])
    assert backend.calls[-1]["method"] == "POST"
    assert result.execution_metadata["transport_method"] == "send_post"


@pytest.mark.parametrize(
    "provider_type,provider_cls,runtime_cls,not_ready_error,shell_name,command_param_key",
    PROVIDER_FAMILY_CASES,
)
def test_family_delivery_only_metadata(
    provider_type: str,
    provider_cls: type,
    runtime_cls: type,
    not_ready_error: type,
    shell_name: str,
    command_param_key: str,
):
    backend = RecordingHttpBackend(responses=[_ok(b"command-output-body")])
    provider = _connected_provider(provider_cls, shell_name, backend)
    result = provider.execute_command("id")
    metadata = result.execution_metadata
    assert metadata["delivery_only"] is True
    assert COMMON_METADATA_KEYS.issubset(metadata.keys())
    assert FORBIDDEN_METADATA_KEYS.isdisjoint(metadata.keys())
    assert "command-output-body" not in str(metadata)


@pytest.mark.parametrize(
    "provider_type,provider_cls,runtime_cls,not_ready_error,shell_name,command_param_key",
    PROVIDER_FAMILY_CASES,
)
def test_family_no_success_inference_in_runtime(
    provider_type: str,
    provider_cls: type,
    runtime_cls: type,
    not_ready_error: type,
    shell_name: str,
    command_param_key: str,
):
    source = inspect.getsource(runtime_cls.execute_command)
    lowered = source.lower()
    for token in FORBIDDEN_INFERENCE_TOKENS:
        assert token not in lowered, f"{provider_type} runtime references {token}"


@pytest.mark.parametrize(
    "provider_type,provider_cls,runtime_cls,not_ready_error,shell_name,command_param_key",
    PROVIDER_FAMILY_CASES,
)
def test_family_no_stdout_stderr_parsing(
    provider_type: str,
    provider_cls: type,
    runtime_cls: type,
    not_ready_error: type,
    shell_name: str,
    command_param_key: str,
):
    module_name = runtime_cls.__module__
    source = inspect.getsource(__import__(module_name, fromlist=[runtime_cls.__name__]))
    lowered = source.lower()
    assert "stdout" not in lowered, provider_type
    assert "stderr" not in lowered, provider_type
    assert "grep" not in lowered, provider_type


@pytest.mark.parametrize(
    "provider_type,provider_cls,runtime_cls,not_ready_error,shell_name,command_param_key",
    PROVIDER_FAMILY_CASES,
)
def test_family_execute_without_runtime_raises(
    provider_type: str,
    provider_cls: type,
    runtime_cls: type,
    not_ready_error: type,
    shell_name: str,
    command_param_key: str,
):
    provider = provider_cls(
        transport=MagicMock(),
        webshell_url=f"https://lab.example/{shell_name}",
    )
    with pytest.raises(not_ready_error, match="create_runtime"):
        provider.execute_command("id")


@pytest.mark.parametrize(
    "provider_type,provider_cls,runtime_cls,not_ready_error,shell_name,command_param_key",
    PROVIDER_FAMILY_CASES,
)
def test_family_upload_download_cleanup(
    provider_type: str,
    provider_cls: type,
    runtime_cls: type,
    not_ready_error: type,
    shell_name: str,
    command_param_key: str,
    tmp_path: Path,
):
    local = tmp_path / f"{provider_type}_payload.txt"
    local.write_text("data")
    backend = RecordingHttpBackend(
        responses=[_ok(b"uploaded"), _ok(b'{"_bundle_metadata":true}\n')]
    )
    provider = _connected_provider(provider_cls, shell_name, backend)
    upload = provider.upload_file(local, "/tmp/dsp_stub/payload.txt")
    assert upload.transfer_status == "uploaded"
    download = provider.download_file("/tmp/dsp_stub/events.jsonl")
    assert download.transfer_status == "downloaded"
    runtime = provider.get_runtime()
    assert isinstance(runtime, runtime_cls)
    provider.cleanup()
    with pytest.raises(Exception):
        runtime.active_session


@pytest.mark.parametrize(
    "provider_type,expected_cls",
    [
        ("jsp", JspWebshellProvider),
        ("php", PhpWebshellProvider),
        ("aspx", AspxWebshellProvider),
    ],
)
def test_factory_resolves_all_families(provider_type: str, expected_cls: type):
    provider = create_webshell_provider(provider_type, transport=MagicMock())
    assert isinstance(provider, expected_cls)
    assert provider.provider_type == provider_type


def test_registry_resolves_all_families():
    registry = WebshellProviderRegistry()
    registry.register_provider("jsp", JspWebshellProvider)
    registry.register_provider("php", PhpWebshellProvider)
    registry.register_provider("aspx", AspxWebshellProvider)
    assert registry.list_providers() == ["aspx", "jsp", "php"]
    for provider_type, expected_cls in (
        ("jsp", JspWebshellProvider),
        ("php", PhpWebshellProvider),
        ("aspx", AspxWebshellProvider),
    ):
        assert registry.get_provider(provider_type) is expected_cls
