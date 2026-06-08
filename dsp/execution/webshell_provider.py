"""Webshell execution provider — Mode B bridge over JSP/PHP/ASPX family adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dsp.engine.scenario_engine import RunContext, ScenarioSummary, TargetSet
from dsp.execution.base import ExecutionProvider
from dsp.execution.exceptions import WebshellExecutionConfigError
from dsp.execution.models import ExecutionContext, ProviderCapabilities
from dsp.execution.providers.runtime.command import (
    CommandExecutionPolicy,
    CommandRequest,
    CommandResult,
)
from dsp.execution.providers.runtime.runtime_models import RuntimeArtifact
from dsp.execution.providers.runtime.transport import TransportRuntimeConfiguration
from dsp.execution.providers.webshell.common.generic_provider import (
    GenericWebshellProvider,
)
from dsp.execution.providers.webshell.provider_factory import create_webshell_provider
from dsp.execution.webshell_config import WebshellExecutionConfig
from dsp.execution.webshell.transport.base import WebshellTransport
from dsp.execution.webshell.transport.real_http_transport import RealHttpTransport
from dsp.execution.remote.models import ScenarioExecutionRequest
from dsp.execution.remote.runner import RemoteScenarioRunner
from dsp.plugins.models import PluginRecord


class WebshellExecutionProvider(ExecutionProvider):
    """ExecutionProvider bridge that wraps a JSP/PHP/ASPX webshell family adapter."""

    def __init__(
        self,
        config: WebshellExecutionConfig,
        *,
        transport: WebshellTransport | None = None,
        family_provider: GenericWebshellProvider | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._family_provider = family_provider
        self._connected = False

    @classmethod
    def from_config(
        cls,
        *,
        transport: WebshellTransport | None = None,
        family_provider: GenericWebshellProvider | None = None,
        **provider_config: Any,
    ) -> WebshellExecutionProvider:
        """Build provider from factory keyword arguments."""
        config_data = dict(provider_config)
        if "provider_type" not in config_data and "webshell_family" in config_data:
            config_data["provider_type"] = config_data.pop("webshell_family")
        if "provider_type" not in config_data:
            raise WebshellExecutionConfigError(
                "provider_type is required (jsp, php, or aspx)",
                field="provider_type",
            )
        if "webshell_url" not in config_data:
            raise WebshellExecutionConfigError(
                "webshell_url is required",
                field="webshell_url",
            )
        config = WebshellExecutionConfig.from_dict(config_data)
        return cls(
            config,
            transport=transport,
            family_provider=family_provider,
        )

    @property
    def provider_type(self) -> str:
        return "webshell"

    @property
    def webshell_family(self) -> str:
        """Selected JSP/PHP/ASPX family identifier."""
        return self._config.provider_type

    @property
    def family_provider(self) -> GenericWebshellProvider | None:
        return self._family_provider

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_type="webshell",
            execution_mode="remote",
            traffic_origin="remote_host",
            supports_udp=False,
            supports_tcp=True,
            supports_http_client=True,
        )

    def get_webshell_metadata(self) -> dict[str, Any]:
        """Expose wrapped family provider metadata when available."""
        if self._family_provider is None:
            return {
                "execution_provider": self.provider_type,
                "webshell_family": self.webshell_family,
                "webshell_url": self._config.webshell_url,
                "transport_type": self._config.transport_type,
            }
        metadata = self._family_provider.get_metadata()
        metadata["execution_provider"] = self.provider_type
        metadata["webshell_url"] = self._config.webshell_url
        return metadata

    def prepare(self, context: ExecutionContext) -> None:
        """Initialize transport, family provider, runtime, and remote session."""
        if self._family_provider is None:
            transport = self._transport or RealHttpTransport(
                retry_policy=self._config.retry_policy,
                verify_tls=self._config.verify_tls,
            )
            self._family_provider = create_webshell_provider(
                self._config.provider_type,
                transport=transport,
                webshell_url=self._config.webshell_url,
                transport_type=self._config.transport_type,
            )
            self._family_provider.create_runtime(
                config=TransportRuntimeConfiguration(
                    enable_healthcheck_on_connect=self._config.enable_healthcheck_on_connect,
                    command_policy=CommandExecutionPolicy(
                        allow_command_execution=True,
                    ),
                ),
            )

        if not self._connected:
            self._family_provider.connect()
            self._connected = True

        context.execution_metadata.update(
            {
                "traffic_origin_host": "remote",
                "execution_provider": self.provider_type,
                "webshell_family": self.webshell_family,
                "webshell_url": self._config.webshell_url,
                "transport_type": self._config.transport_type,
            }
        )

    def execute(
        self,
        context: ExecutionContext,
        record: PluginRecord,
        ctx: RunContext,
        targets: TargetSet,
        *,
        snapshot_dir: Path | None = None,
    ) -> ScenarioSummary | None:
        """Deliver scenario execution remotely via webshell command transport."""
        params = ctx.config.scenario_params.get(record.id, {})
        request = ScenarioExecutionRequest(
            scenario_id=record.id,
            scenario_params=dict(params),
            execution_metadata=dict(context.execution_metadata),
            run_id=context.run_id,
            target_net=context.target_net,
            dry_run=context.dry_run,
        )
        runner = RemoteScenarioRunner()
        result = runner.run(request, self)
        context.execution_metadata["remote_scenario_result"] = result.to_dict()
        context.execution_metadata["remote_execution_id"] = result.remote_execution_id
        return None

    def execute_command(
        self,
        command: CommandRequest | str,
        *,
        arguments: list[str] | None = None,
        timeout_seconds: int = 300,
    ) -> CommandResult:
        """Execute a command through the selected webshell family provider."""
        provider = self._require_family_provider()
        return provider.execute_command(
            command,
            arguments=arguments,
            timeout_seconds=timeout_seconds,
        )

    def upload_file(self, local_file: Path | str, remote_path: str) -> RuntimeArtifact:
        """Upload a local artifact through the selected webshell family provider."""
        provider = self._require_family_provider()
        return provider.upload_file(local_file, remote_path)

    def download_file(self, remote_path: str) -> RuntimeArtifact:
        """Download a remote artifact through the selected webshell family provider."""
        provider = self._require_family_provider()
        return provider.download_file(remote_path)

    def cleanup(self, context: ExecutionContext) -> None:
        """Release webshell runtime session state."""
        if self._family_provider is not None:
            self._family_provider.cleanup()
        self._connected = False

    def _require_family_provider(self) -> GenericWebshellProvider:
        if self._family_provider is None:
            raise RuntimeError(
                "webshell family provider is not initialized; call prepare() first"
            )
        return self._family_provider
