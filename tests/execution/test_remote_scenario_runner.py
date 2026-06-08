"""RemoteScenarioRunner tests — mocked providers only, no live network."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dsp.engine import RunConfig, RunContext
from dsp.event_store import EventStore
from dsp.execution import ExecutionContext, LocalExecutionProvider, WebshellExecutionProvider
from dsp.execution.providers.runtime.command import (
    CommandExecutionPolicy,
    CommandRequest,
    CommandResult,
    CommandStatus,
    CommandTransportError,
)
from dsp.execution.providers.runtime.transport import TransportRuntimeConfiguration
from dsp.execution.providers.webshell.aspx import AspxWebshellProvider
from dsp.execution.providers.webshell.jsp import JspWebshellProvider
from dsp.execution.providers.webshell.php import PhpWebshellProvider
from dsp.execution.remote import (
    FORBIDDEN_RESULT_FIELDS,
    REMOTE_SCENARIO_COMMAND,
    RemoteScenarioExecutionResult,
    RemoteScenarioRunner,
    ScenarioExecutionRequest,
    UnsupportedRemoteProviderError,
    build_scenario_command,
)
from dsp.execution.webshell_config import WebshellExecutionConfig
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


def _connected_execution_provider(
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
    family_provider.connect()
    return WebshellExecutionProvider(
        _webshell_config(family, filename),
        transport=transport,
        family_provider=family_provider,
    )


def _request(**overrides: object) -> ScenarioExecutionRequest:
    defaults = {
        "scenario_id": "dummy",
        "scenario_params": {"action_count": 3},
        "execution_metadata": {"run_tag": "lab01"},
        "run_id": "20260606_abc123",
        "target_net": "10.10.10.0/24",
        "dry_run": False,
    }
    defaults.update(overrides)
    return ScenarioExecutionRequest(**defaults)  # type: ignore[arg-type]


# --- Payload / request model ---


def test_scenario_execution_request_round_trip():
    request = _request()
    restored = ScenarioExecutionRequest.from_dict(request.to_dict())
    assert restored.scenario_id == "dummy"
    assert restored.scenario_params == {"action_count": 3}
    assert restored.execution_metadata == {"run_tag": "lab01"}


def test_build_scenario_command_uses_remote_dispatcher():
    command = build_scenario_command(_request())
    assert command.command == REMOTE_SCENARIO_COMMAND
    assert len(command.arguments) == 1


def test_build_scenario_command_embeds_scenario_id():
    command = build_scenario_command(_request(scenario_id="dns_tunnel"))
    payload = json.loads(command.arguments[0])
    assert payload["scenario_id"] == "dns_tunnel"


def test_build_scenario_command_propagates_scenario_params():
    command = build_scenario_command(
        _request(scenario_params={"action_count": 7, "interval_ms": 100})
    )
    payload = json.loads(command.arguments[0])
    assert payload["scenario_params"] == {"action_count": 7, "interval_ms": 100}


def test_build_scenario_command_propagates_execution_metadata():
    command = build_scenario_command(
        _request(execution_metadata={"webshell_family": "jsp", "lab": "poc"})
    )
    payload = json.loads(command.arguments[0])
    assert payload["execution_metadata"]["webshell_family"] == "jsp"
    assert payload["execution_metadata"]["lab"] == "poc"


def test_build_scenario_command_propagates_run_context_fields():
    command = build_scenario_command(
        _request(run_id="run99", target_net="192.168.1.0/24", dry_run=True)
    )
    payload = json.loads(command.arguments[0])
    assert payload["run_id"] == "run99"
    assert payload["target_net"] == "192.168.1.0/24"
    assert payload["dry_run"] is True


def test_remote_result_forbids_inference_fields_on_init():
    with pytest.raises(ValueError, match="forbidden inference fields"):
        RemoteScenarioExecutionResult(
            scenario_id="dummy",
            remote_execution_id="exec01",
            transport_metadata={"success": True},
        )


def test_remote_result_to_dict_excludes_forbidden_top_level_fields():
    result = RemoteScenarioExecutionResult.new(scenario_id="dummy")
    payload = result.to_dict()
    assert FORBIDDEN_RESULT_FIELDS.isdisjoint(payload.keys())


# --- Unsupported provider ---


def test_unsupported_provider_rejected():
    runner = RemoteScenarioRunner()
    with pytest.raises(UnsupportedRemoteProviderError, match="local"):
        runner.run(_request(), LocalExecutionProvider())  # type: ignore[arg-type]


def test_unsupported_provider_rejected_for_generic_mock():
    runner = RemoteScenarioRunner()
    mock_provider = MagicMock()
    mock_provider.provider_type = "agent"
    with pytest.raises(UnsupportedRemoteProviderError, match="agent"):
        runner.run(_request(), mock_provider)


# --- Mocked provider delegation ---


def test_runner_delegates_execute_command_to_provider():
    mock_provider = MagicMock(spec=WebshellExecutionProvider)
    mock_provider.provider_type = "webshell"
    mock_provider.get_webshell_metadata.return_value = {
        "provider_type": "jsp",
        "execution_provider": "webshell",
    }
    mock_provider.execute_command.return_value = CommandResult.new(
        "cmd01",
        status=CommandStatus.COMPLETED,
        execution_metadata={
            "transport_status": 200,
            "transport_method": "send_get",
            "delivery_only": True,
        },
    )
    result = RemoteScenarioRunner().run(_request(), mock_provider)
    mock_provider.execute_command.assert_called_once()
    assert result.scenario_id == "dummy"
    assert result.transport_metadata["transport_status"] == 200


def test_runner_generates_remote_execution_id():
    mock_provider = MagicMock(spec=WebshellExecutionProvider)
    mock_provider.get_webshell_metadata.return_value = {"provider_type": "jsp"}
    mock_provider.execute_command.return_value = CommandResult.new(
        "cmd01",
        status=CommandStatus.COMPLETED,
        execution_metadata={"transport_status": 200, "delivery_only": True},
    )
    result = RemoteScenarioRunner().run(_request(), mock_provider)
    assert result.remote_execution_id
    assert len(result.remote_execution_id) >= 16


def test_runner_propagates_provider_metadata():
    mock_provider = MagicMock(spec=WebshellExecutionProvider)
    mock_provider.get_webshell_metadata.return_value = {
        "provider_type": "php",
        "provider_name": "PHP Webshell Provider",
        "execution_provider": "webshell",
        "webshell_url": "https://lab/shell.php",
    }
    mock_provider.execute_command.return_value = CommandResult.new(
        "cmd01",
        status=CommandStatus.COMPLETED,
        execution_metadata={"transport_status": 200, "delivery_only": True},
    )
    result = RemoteScenarioRunner().run(_request(), mock_provider)
    assert result.provider_metadata["provider_type"] == "php"
    assert result.provider_metadata["webshell_url"] == "https://lab/shell.php"


def test_runner_propagates_command_metadata():
    mock_provider = MagicMock(spec=WebshellExecutionProvider)
    mock_provider.get_webshell_metadata.return_value = {"provider_type": "aspx"}
    mock_provider.execute_command.return_value = CommandResult.new(
        "cmd99",
        status=CommandStatus.COMPLETED,
        execution_metadata={
            "transport_status": 200,
            "transport_method": "send_post",
            "delivery_only": True,
            "aspx_command_param": "cmd",
        },
    )
    result = RemoteScenarioRunner().run(_request(), mock_provider)
    assert result.command_metadata["command_id"] == "cmd99"
    assert result.command_metadata["command_status"] == "completed"
    assert result.command_metadata["aspx_command_param"] == "cmd"


def test_runner_splits_transport_metadata_from_command_metadata():
    mock_provider = MagicMock(spec=WebshellExecutionProvider)
    mock_provider.get_webshell_metadata.return_value = {"provider_type": "jsp"}
    mock_provider.execute_command.return_value = CommandResult.new(
        "cmd01",
        status=CommandStatus.COMPLETED,
        execution_metadata={
            "transport_status": 200,
            "transport_method": "send_get",
            "transport_response_size": 42,
            "delivery_only": True,
            "jsp_command_param": "cmd",
        },
    )
    result = RemoteScenarioRunner().run(_request(), mock_provider)
    assert result.transport_metadata["transport_status"] == 200
    assert result.transport_metadata["delivery_only"] is True
    assert "transport_status" not in result.command_metadata
    assert result.command_metadata["jsp_command_param"] == "cmd"


def test_runner_propagates_execution_exceptions():
    mock_provider = MagicMock(spec=WebshellExecutionProvider)
    mock_provider.execute_command.side_effect = CommandTransportError(
        "execute_command timed out",
        command_id="cmd01",
    )
    with pytest.raises(CommandTransportError, match="timed out"):
        RemoteScenarioRunner().run(_request(), mock_provider)


# --- Family integration with mocked HTTP backend ---


@pytest.mark.parametrize("family,provider_cls,filename", FAMILY_CASES)
def test_jsp_php_aspx_remote_scenario_execution(family, provider_cls, filename):
    backend = RecordingHttpBackend(responses=[_ok(b"raw-remote-body")])
    provider = _connected_execution_provider(family, provider_cls, filename, backend)
    result = RemoteScenarioRunner().run(_request(scenario_id="dummy"), provider)
    assert result.scenario_id == "dummy"
    assert result.transport_metadata["transport_status"] == 200
    assert result.provider_metadata["provider_type"] == family
    assert backend.calls


@pytest.mark.parametrize("family,provider_cls,filename", FAMILY_CASES)
def test_scenario_params_reach_remote_command(family, provider_cls, filename):
    backend = RecordingHttpBackend(responses=[_ok()])
    provider = _connected_execution_provider(family, provider_cls, filename, backend)
    RemoteScenarioRunner().run(
        _request(scenario_params={"action_count": 9, "mode": "lab"}),
        provider,
    )
    dispatched = backend.calls[-1]
    url_or_body = str(dispatched.get("url", "")) + str(dispatched.get("body", b""))
    assert "action_count" in url_or_body
    assert "9" in url_or_body
    assert "mode" in url_or_body


@pytest.mark.parametrize("family,provider_cls,filename", FAMILY_CASES)
def test_execution_metadata_reaches_remote_command(family, provider_cls, filename):
    backend = RecordingHttpBackend(responses=[_ok()])
    provider = _connected_execution_provider(family, provider_cls, filename, backend)
    RemoteScenarioRunner().run(
        _request(execution_metadata={"webshell_family": family, "lab": "xdr"}),
        provider,
    )
    dispatched = backend.calls[-1]
    url_or_body = str(dispatched.get("url", "")) + str(dispatched.get("body", b""))
    assert "webshell_family" in url_or_body
    assert family in url_or_body


@pytest.mark.parametrize("family,provider_cls,filename", FAMILY_CASES)
def test_transport_metadata_from_remote_delivery(family, provider_cls, filename):
    backend = RecordingHttpBackend(responses=[_ok(b"not-parsed-body")])
    provider = _connected_execution_provider(family, provider_cls, filename, backend)
    result = RemoteScenarioRunner().run(_request(), provider)
    assert result.transport_metadata["transport_status"] == 200
    assert result.transport_metadata["delivery_only"] is True
    assert FORBIDDEN_METADATA_KEYS.isdisjoint(result.transport_metadata.keys())
    assert "not-parsed" not in str(result.transport_metadata)


@pytest.mark.parametrize("family,provider_cls,filename", FAMILY_CASES)
def test_provider_metadata_from_family_adapter(family, provider_cls, filename):
    backend = RecordingHttpBackend(responses=[_ok()])
    provider = _connected_execution_provider(family, provider_cls, filename, backend)
    result = RemoteScenarioRunner().run(_request(), provider)
    assert result.provider_metadata["provider_type"] == family
    assert result.provider_metadata["execution_provider"] == "webshell"


@pytest.mark.parametrize("family,provider_cls,filename", FAMILY_CASES)
def test_remote_execution_id_present(family, provider_cls, filename):
    backend = RecordingHttpBackend(responses=[_ok()])
    provider = _connected_execution_provider(family, provider_cls, filename, backend)
    result = RemoteScenarioRunner().run(_request(), provider)
    assert result.remote_execution_id


# --- WebshellExecutionProvider.execute integration ---


@pytest.mark.parametrize("family,provider_cls,filename", FAMILY_CASES)
def test_webshell_provider_execute_runs_remote_scenario(
    family, provider_cls, filename, tmp_path: Path
):
    backend = RecordingHttpBackend(responses=[_ok()])
    provider = _connected_execution_provider(family, provider_cls, filename, backend)
    loader = PluginLoader()
    record = loader.discover_and_load().get("dummy")
    assert record is not None
    store = EventStore(":memory:")
    run_ctx = RunContext(
        run_id="remote01",
        target_net="10.10.10.0/24",
        event_store=store,
        config=RunConfig(scenario_params={"dummy": {"action_count": 4}}),
        dry_run=False,
    )
    exec_ctx = ExecutionContext(
        run_id="remote01",
        target_net="10.10.10.0/24",
        dry_run=False,
        provider_type="webshell",
        scenario_id="dummy",
        execution_metadata={"webshell_family": family},
    )
    provider.prepare(exec_ctx)
    summary = provider.execute(
        exec_ctx,
        record,
        run_ctx,
        MagicMock(),
        snapshot_dir=tmp_path,
    )
    assert summary is None
    assert "remote_scenario_result" in exec_ctx.execution_metadata
    assert "w5_deferred" not in exec_ctx.execution_metadata
    assert exec_ctx.execution_metadata["remote_execution_id"]
    result = RemoteScenarioExecutionResult.from_dict(
        exec_ctx.execution_metadata["remote_scenario_result"]
    )
    assert result.scenario_id == "dummy"
    assert result.transport_metadata["transport_status"] == 200


def test_webshell_provider_execute_does_not_write_events():
    from dsp.event_store import EventQuery

    backend = RecordingHttpBackend(responses=[_ok()])
    provider = _connected_execution_provider("jsp", JspWebshellProvider, "shell.jsp", backend)
    loader = PluginLoader()
    record = loader.discover_and_load().get("dummy")
    assert record is not None
    store = EventStore(":memory:")
    store.open_run("remote02")
    run_ctx = RunContext(
        run_id="remote02",
        target_net="10.10.10.0/24",
        event_store=store,
        config=RunConfig(),
        dry_run=False,
    )
    exec_ctx = ExecutionContext(
        run_id="remote02",
        target_net="10.10.10.0/24",
        dry_run=False,
        provider_type="webshell",
    )
    provider.prepare(exec_ctx)
    provider.execute(exec_ctx, record, run_ctx, MagicMock())
    assert store.count(EventQuery(run_id="remote02")) == 0


# --- No inference / parsing guards ---


def test_runner_source_has_no_success_inference():
    source = inspect.getsource(RemoteScenarioRunner.run).lower()
    for token in FORBIDDEN_INFERENCE_TOKENS:
        assert token not in source


def test_runner_source_has_no_stdout_stderr_grep():
    source = inspect.getsource(RemoteScenarioRunner)
    for token in ("grep", "stdout", "stderr", "parsed_output"):
        assert token not in source


def test_result_model_has_no_forbidden_fields():
    source = inspect.getsource(RemoteScenarioExecutionResult)
    for field_name in FORBIDDEN_RESULT_FIELDS:
        assert f"{field_name}:" not in source


def test_remote_result_round_trip():
    result = RemoteScenarioExecutionResult.new(
        scenario_id="dummy",
        transport_metadata={"transport_status": 200, "delivery_only": True},
        provider_metadata={"provider_type": "jsp"},
        command_metadata={"command_id": "abc", "command_status": "completed"},
    )
    restored = RemoteScenarioExecutionResult.from_dict(result.to_dict())
    assert restored.scenario_id == "dummy"
    assert restored.remote_execution_id == result.remote_execution_id


def test_runner_does_not_reference_event_store():
    source = inspect.getsource(RemoteScenarioRunner)
    assert "EventStore" not in source
    assert "event_store" not in source
    assert "EventSyncBridge" not in source


def test_runner_does_not_reference_validation_or_reporting():
    source = inspect.getsource(RemoteScenarioRunner.run)
    assert "ValidationEngine" not in source
    assert "ReportingEngine" not in source
    assert "create_detection" not in source
