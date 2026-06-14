"""WebshellExecutionProvider bridge tests — mocked backend only, no live network."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dsp.engine import RunConfig, RunContext
from dsp.event_store import EventStore
from dsp.execution import (
    ExecutionContext,
    LocalExecutionProvider,
    SUPPORTED_PROVIDERS,
    SUPPORTED_WEBSHELL_FAMILIES,
    WebshellExecutionConfig,
    WebshellExecutionConfigError,
    WebshellExecutionProvider,
    create_execution_provider,
)
from dsp.execution.providers.runtime.command import (
    CommandExecutionPolicy,
    CommandRequest,
    CommandResult,
    CommandStatus,
)
from dsp.execution.providers.runtime.runtime_models import RuntimeArtifact
from dsp.execution.providers.runtime.transport import TransportRuntimeConfiguration
from dsp.execution.providers.webshell.aspx import AspxWebshellProvider
from dsp.execution.providers.webshell.jsp import JspWebshellProvider
from dsp.execution.providers.webshell.php import PhpWebshellProvider
from dsp.execution.webshell.transport import RealHttpTransport, RetryPolicy
from dsp.execution.webshell.transport.real_http_transport import HttpBackendResponse
from dsp.plugins import PluginLoader

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

FAMILY_CASES = [
    pytest.param("jsp", JspWebshellProvider, "shell.jsp", id="jsp"),
    pytest.param("php", PhpWebshellProvider, "shell.php", id="php"),
    pytest.param("aspx", AspxWebshellProvider, "shell.aspx", id="aspx"),
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


def _ok(body: bytes = b"transport-delivered") -> HttpBackendResponse:
    return HttpBackendResponse(
        status_code=200,
        headers={"content-type": "text/html"},
        body=body,
    )


def _webshell_config(family: str, filename: str) -> WebshellExecutionConfig:
    return WebshellExecutionConfig(
        provider_type=family,
        webshell_url=f"https://lab.example/{filename}",
    )


def _connected_provider(
    family: str,
    provider_cls: type,
    filename: str,
    backend: RecordingHttpBackend,
) -> WebshellExecutionProvider:
    transport = RealHttpTransport(backend=backend, retry_policy=RetryPolicy(max_retries=0))
    family_provider = provider_cls(
        transport=transport,
        webshell_url=f"https://lab.example/{filename}",
    )
    family_provider.create_runtime(
        config=TransportRuntimeConfiguration(
            enable_healthcheck_on_connect=False,
            command_policy=CommandExecutionPolicy(allow_command_execution=True),
        ),
    )
    return WebshellExecutionProvider(
        _webshell_config(family, filename),
        transport=transport,
        family_provider=family_provider,
    )


def _exec_context(**overrides: object) -> ExecutionContext:
    defaults = {
        "run_id": "ws01",
        "target_net": "10.10.10.0/24",
        "dry_run": False,
        "provider_type": "webshell",
    }
    defaults.update(overrides)
    return ExecutionContext(**defaults)  # type: ignore[arg-type]


# --- Config validation ---


def test_config_requires_provider_type():
    with pytest.raises(WebshellExecutionConfigError, match="provider_type"):
        WebshellExecutionConfig(provider_type="", webshell_url="https://x/s.jsp")


def test_config_requires_webshell_url():
    with pytest.raises(WebshellExecutionConfigError, match="webshell_url"):
        WebshellExecutionConfig(provider_type="jsp", webshell_url="")


def test_config_rejects_unsupported_family():
    with pytest.raises(WebshellExecutionConfigError, match="unsupported webshell family"):
        WebshellExecutionConfig(provider_type="unknown", webshell_url="https://x/s.jsp")


def test_config_rejects_invalid_transport_type():
    with pytest.raises(WebshellExecutionConfigError, match="transport_type"):
        WebshellExecutionConfig(
            provider_type="jsp",
            webshell_url="https://x/s.jsp",
            transport_type="ftp",
        )


def test_config_round_trip_dict():
    config = WebshellExecutionConfig(
        provider_type="php",
        webshell_url="https://lab/shell.php",
        verify_tls=False,
        max_retries=2,
    )
    restored = WebshellExecutionConfig.from_dict(config.to_dict())
    assert restored.provider_type == "php"
    assert restored.webshell_url == "https://lab/shell.php"
    assert restored.verify_tls is False
    assert restored.max_retries == 2


def test_supported_webshell_families():
    assert SUPPORTED_WEBSHELL_FAMILIES == frozenset({"jsp", "php", "aspx"})


# --- Factory integration ---


@pytest.mark.parametrize("family,expected_cls,filename", FAMILY_CASES)
def test_factory_creates_webshell_provider(family, expected_cls, filename):
    provider = create_execution_provider(
        "webshell",
        webshell_family=family,
        webshell_url=f"https://lab.example/{filename}",
    )
    assert isinstance(provider, WebshellExecutionProvider)
    assert provider.webshell_family == family


def test_factory_webshell_accepts_provider_type_in_config_dict():
    provider = WebshellExecutionProvider.from_config(
        provider_type="jsp",
        webshell_url="https://lab.example/shell.jsp",
    )
    assert provider.webshell_family == "jsp"


def test_factory_webshell_missing_provider_type():
    with pytest.raises(WebshellExecutionConfigError, match="provider_type"):
        create_execution_provider("webshell", webshell_url="https://x/s.jsp")


def test_factory_webshell_missing_webshell_url():
    with pytest.raises(WebshellExecutionConfigError, match="webshell_url"):
        create_execution_provider("webshell", webshell_family="jsp")


def test_factory_webshell_unsupported_family():
    with pytest.raises(WebshellExecutionConfigError, match="unsupported webshell family"):
        create_execution_provider(
            "webshell",
            webshell_family="generic",
            webshell_url="https://x/s.jsp",
        )


def test_factory_still_creates_local_provider():
    provider = create_execution_provider("local")
    assert isinstance(provider, LocalExecutionProvider)
    assert provider.provider_type == "local"


def test_factory_default_provider_is_local():
    provider = create_execution_provider()
    assert isinstance(provider, LocalExecutionProvider)


def test_supported_providers_includes_webshell():
    assert "webshell" in SUPPORTED_PROVIDERS
    assert "local" in SUPPORTED_PROVIDERS


# --- ExecutionProvider contract ---


def test_webshell_provider_type_is_webshell():
    provider = create_execution_provider(
        "webshell",
        webshell_family="jsp",
        webshell_url="https://lab.example/shell.jsp",
    )
    assert provider.provider_type == "webshell"


def test_webshell_capabilities_remote_mode():
    provider = create_execution_provider(
        "webshell",
        webshell_family="jsp",
        webshell_url="https://lab.example/shell.jsp",
    )
    caps = provider.capabilities()
    assert caps.provider_type == "webshell"
    assert caps.execution_mode == "remote"
    assert caps.traffic_origin == "remote_host"


def test_prepare_sets_execution_metadata():
    backend = RecordingHttpBackend(responses=[_ok()])
    provider = _connected_provider("jsp", JspWebshellProvider, "shell.jsp", backend)
    ctx = _exec_context()
    provider.prepare(ctx)
    assert ctx.execution_metadata["traffic_origin_host"] == "remote"
    assert ctx.execution_metadata["webshell_family"] == "jsp"
    assert ctx.execution_metadata["execution_provider"] == "webshell"


def test_execute_scenario_via_remote_runner():
    mock_family = MagicMock()
    mock_family.execute_command.return_value = CommandResult.new(
        "cmd01",
        status=CommandStatus.COMPLETED,
        execution_metadata={"transport_status": 200, "delivery_only": True},
    )
    config = WebshellExecutionConfig(
        provider_type="jsp",
        webshell_url="https://lab.example/shell.jsp",
    )
    provider = WebshellExecutionProvider(config, family_provider=mock_family)
    loader = PluginLoader()
    record = loader.discover_and_load().get("dummy")
    assert record is not None
    store = EventStore(":memory:")
    run_ctx = RunContext(
        run_id="defer01",
        target_net="10.10.10.0/24",
        event_store=store,
        config=RunConfig(dry_run=True),
        dry_run=True,
    )
    exec_ctx = ExecutionContext(
        run_id="defer01",
        target_net="10.10.10.0/24",
        dry_run=True,
        provider_type="webshell",
    )
    summary = provider.execute(exec_ctx, record, run_ctx, MagicMock())
    assert summary is None
    mock_family.execute_command.assert_called_once()
    assert "remote_scenario_result" in exec_ctx.execution_metadata


def test_webshell_provider_execute_stores_remote_execution_id():
    mock_family = MagicMock()
    mock_family.execute_command.return_value = CommandResult.new(
        "cmd01",
        status=CommandStatus.COMPLETED,
        execution_metadata={"transport_status": 200, "delivery_only": True},
    )
    config = WebshellExecutionConfig(
        provider_type="jsp",
        webshell_url="https://lab.example/shell.jsp",
    )
    provider = WebshellExecutionProvider(config, family_provider=mock_family)
    loader = PluginLoader()
    record = loader.discover_and_load().get("dummy")
    assert record is not None
    run_ctx = RunContext(
        run_id="w5note01",
        target_net="10.10.10.0/24",
        event_store=EventStore(":memory:"),
        config=RunConfig(),
        dry_run=False,
    )
    exec_ctx = ExecutionContext(
        run_id="w5note01",
        target_net="10.10.10.0/24",
        dry_run=False,
        provider_type="webshell",
    )
    provider.execute(exec_ctx, record, run_ctx, MagicMock())
    assert exec_ctx.execution_metadata["remote_execution_id"]
    assert "remote_scenario_result" in exec_ctx.execution_metadata


# --- Delegation with mocked family provider ---


@pytest.mark.parametrize("family", ["jsp", "php", "aspx"])
def test_execute_command_delegates_to_family_provider(family: str):
    mock_family = MagicMock()
    mock_family.execute_command.return_value = CommandResult.new(
        "cmd01",
        status=CommandStatus.COMPLETED,
        execution_metadata={"transport_status": 200, "delivery_only": True},
    )
    config = WebshellExecutionConfig(
        provider_type=family,
        webshell_url=f"https://lab.example/shell.{family}",
    )
    provider = WebshellExecutionProvider(config, family_provider=mock_family)
    result = provider.execute_command("whoami")
    mock_family.execute_command.assert_called_once()
    assert result.status == CommandStatus.COMPLETED
    assert result.execution_metadata["transport_status"] == 200


@pytest.mark.parametrize("family", ["jsp", "php", "aspx"])
def test_upload_delegates_to_family_provider(family: str, tmp_path: Path):
    mock_family = MagicMock()
    artifact = RuntimeArtifact.new(
        local_path=str(tmp_path / "payload.txt"),
        remote_path="/tmp/payload.txt",
        transfer_status="uploaded",
    )
    mock_family.upload_file.return_value = artifact
    config = WebshellExecutionConfig(
        provider_type=family,
        webshell_url=f"https://lab.example/shell.{family}",
    )
    provider = WebshellExecutionProvider(config, family_provider=mock_family)
    local = tmp_path / "payload.txt"
    local.write_text("data")
    result = provider.upload_file(local, "/tmp/payload.txt")
    mock_family.upload_file.assert_called_once_with(local, "/tmp/payload.txt")
    assert result.transfer_status == "uploaded"


@pytest.mark.parametrize("family", ["jsp", "php", "aspx"])
def test_download_delegates_to_family_provider(family: str):
    mock_family = MagicMock()
    artifact = RuntimeArtifact.new(
        remote_path="/tmp/events.jsonl",
        transfer_status="downloaded",
    )
    mock_family.download_file.return_value = artifact
    config = WebshellExecutionConfig(
        provider_type=family,
        webshell_url=f"https://lab.example/shell.{family}",
    )
    provider = WebshellExecutionProvider(config, family_provider=mock_family)
    result = provider.download_file("/tmp/events.jsonl")
    mock_family.download_file.assert_called_once_with("/tmp/events.jsonl")
    assert result.transfer_status == "downloaded"


@pytest.mark.parametrize("family", ["jsp", "php", "aspx"])
def test_cleanup_delegates_to_family_provider(family: str):
    mock_family = MagicMock()
    config = WebshellExecutionConfig(
        provider_type=family,
        webshell_url=f"https://lab.example/shell.{family}",
    )
    provider = WebshellExecutionProvider(config, family_provider=mock_family)
    provider.cleanup(_exec_context())
    mock_family.cleanup.assert_called_once()


def test_operations_require_prepare_when_no_family_injected():
    provider = create_execution_provider(
        "webshell",
        webshell_family="jsp",
        webshell_url="https://lab.example/shell.jsp",
    )
    with pytest.raises(RuntimeError, match="call prepare\\(\\) first"):
        provider.execute_command("id")


# --- End-to-end bridge with RecordingHttpBackend (mocked transport) ---


@pytest.mark.parametrize("family,provider_cls,filename", FAMILY_CASES)
def test_bridge_execute_command_transport_delivery(family, provider_cls, filename):
    backend = RecordingHttpBackend(responses=[_ok(b"raw-body-not-parsed")])
    provider = _connected_provider(family, provider_cls, filename, backend)
    ctx = _exec_context()
    provider.prepare(ctx)
    result = provider.execute_command("whoami")
    assert result.status == CommandStatus.COMPLETED
    assert result.execution_metadata["transport_status"] == 200
    assert backend.calls
    forbidden = FORBIDDEN_METADATA_KEYS
    assert forbidden.isdisjoint(result.execution_metadata.keys())


@pytest.mark.parametrize("family,provider_cls,filename", FAMILY_CASES)
def test_bridge_upload_transport_delivery(family, provider_cls, filename, tmp_path: Path):
    backend = RecordingHttpBackend(responses=[_ok(b"uploaded")])
    provider = _connected_provider(family, provider_cls, filename, backend)
    provider.prepare(_exec_context())
    local = tmp_path / "stub.txt"
    local.write_text("payload")
    artifact = provider.upload_file(local, f"/tmp/dsp/{family}/stub.txt")
    assert artifact.transfer_status == "uploaded"
    assert backend.calls[-1]["method"] == "POST"


@pytest.mark.parametrize("family,provider_cls,filename", FAMILY_CASES)
def test_bridge_download_transport_delivery(family, provider_cls, filename):
    backend = RecordingHttpBackend(responses=[_ok(b'{"_bundle_metadata":true}\n')])
    provider = _connected_provider(family, provider_cls, filename, backend)
    provider.prepare(_exec_context())
    artifact = provider.download_file(f"/tmp/dsp/{family}/events.jsonl")
    assert artifact.transfer_status == "downloaded"
    assert backend.calls[-1]["method"] == "GET"


@pytest.mark.parametrize("family,provider_cls,filename", FAMILY_CASES)
def test_bridge_cleanup_releases_session(family, provider_cls, filename):
    backend = RecordingHttpBackend(responses=[_ok()])
    provider = _connected_provider(family, provider_cls, filename, backend)
    ctx = _exec_context()
    provider.prepare(ctx)
    provider.cleanup(ctx)
    assert provider.family_provider is not None


def test_get_webshell_metadata_exposes_family():
    backend = RecordingHttpBackend(responses=[_ok()])
    provider = _connected_provider("jsp", JspWebshellProvider, "shell.jsp", backend)
    provider.prepare(_exec_context())
    metadata = provider.get_webshell_metadata()
    assert metadata["execution_provider"] == "webshell"
    assert metadata["provider_type"] == "jsp"
    assert metadata["webshell_url"] == "https://lab.example/shell.jsp"


def test_no_success_inference_in_provider_source():
    source = inspect.getsource(WebshellExecutionProvider)
    lowered = source.lower()
    for token in FORBIDDEN_INFERENCE_TOKENS:
        assert token not in lowered


def test_no_stdout_stderr_grep_parsing_in_provider_source():
    source = inspect.getsource(WebshellExecutionProvider)
    forbidden_ops = ("grep", "stdout", "stderr", "parsed_output")
    for op in forbidden_ops:
        assert op not in source


def test_command_result_metadata_is_delivery_only():
    backend = RecordingHttpBackend(responses=[_ok(b"uid=0(root) not interpreted")])
    provider = _connected_provider("jsp", JspWebshellProvider, "shell.jsp", backend)
    provider.prepare(_exec_context())
    result = provider.execute_command("id")
    metadata = result.execution_metadata
    assert metadata.get("delivery_only") is True
    assert "root" not in str(metadata)
    assert FORBIDDEN_METADATA_KEYS.isdisjoint(metadata.keys())


def test_verify_tls_config_applied_to_transport():
    backend = RecordingHttpBackend(responses=[_ok()])
    config = WebshellExecutionConfig(
        provider_type="jsp",
        webshell_url="https://lab.example/shell.jsp",
        verify_tls=False,
    )
    transport = RealHttpTransport(
        backend=backend,
        verify_tls=config.verify_tls,
        retry_policy=config.retry_policy,
    )
    provider = WebshellExecutionProvider(config, transport=transport)
    provider.prepare(_exec_context())
    assert isinstance(transport.backend, object)
    assert transport.verify_tls is False
