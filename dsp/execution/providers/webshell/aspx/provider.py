"""AspxWebshellProvider — ASPX family adapter with real execution via runtime."""

from __future__ import annotations

from pathlib import Path

from dsp.execution.providers.runtime.command import (
    CommandExecutionPolicy,
    CommandRequest,
    CommandResult,
)
from dsp.execution.providers.runtime.runtime_models import RuntimeArtifact
from dsp.execution.providers.runtime.transport import TransportRuntimeConfiguration
from dsp.execution.providers.webshell.aspx.aspx_exceptions import AspxProviderNotReadyError
from dsp.execution.providers.webshell.aspx.aspx_models import (
    ASPX_PROVIDER_VERSION,
    AspxProviderSession,
)
from dsp.execution.providers.webshell.aspx.aspx_runtime import AspxWebshellRuntime
from dsp.execution.providers.webshell.common.generic_provider import (
    GenericWebshellProvider,
)


class AspxWebshellProvider(GenericWebshellProvider):
    """ASPX webshell provider — delegates execution to ``AspxWebshellRuntime``."""

    provider_type = "aspx"
    provider_name = "ASPX Webshell Provider"
    session_class = AspxProviderSession
    provider_version = ASPX_PROVIDER_VERSION

    def create_runtime(
        self,
        *,
        config: TransportRuntimeConfiguration | None = None,
        enable_healthcheck_on_connect: bool = True,
    ) -> AspxWebshellRuntime:
        """Build an ASPX runtime bound to this provider's transport and URL."""
        if self._transport is None:
            raise AspxProviderNotReadyError(
                "transport is required to create ASPX runtime",
                field="transport",
            )
        if config is None:
            runtime_config = TransportRuntimeConfiguration(
                enable_healthcheck_on_connect=enable_healthcheck_on_connect,
                command_policy=CommandExecutionPolicy(allow_command_execution=True),
            )
        else:
            policy = config.command_policy
            if not policy.allow_command_execution:
                policy = CommandExecutionPolicy(
                    allow_command_execution=True,
                    allow_file_modification=policy.allow_file_modification,
                    allow_network_access=policy.allow_network_access,
                    allow_privilege_escalation=policy.allow_privilege_escalation,
                    max_timeout_seconds=policy.max_timeout_seconds,
                )
            runtime_config = TransportRuntimeConfiguration(
                enable_healthcheck_on_connect=config.enable_healthcheck_on_connect,
                command_get_post_threshold_bytes=config.command_get_post_threshold_bytes,
                command_policy=policy,
            )
        runtime = AspxWebshellRuntime(
            self._transport,
            provider_type=self.provider_type,
            webshell_url=self._webshell_url,
            config=runtime_config,
        )
        self.attach_runtime(runtime)
        return runtime

    def connect(self) -> None:
        """Create a remote session and connect through the attached runtime."""
        runtime = self._require_aspx_runtime()
        runtime.create_remote_session()
        runtime.connect()

    def execute_command(
        self,
        request: CommandRequest | str,
        *,
        arguments: list[str] | None = None,
        timeout_seconds: int = 300,
    ) -> CommandResult:
        """Execute a command through the ASPX webshell transport path."""
        if isinstance(request, str):
            command_request = CommandRequest.new(
                request,
                arguments=arguments,
                timeout_seconds=timeout_seconds,
            )
        else:
            command_request = request
        runtime = self._require_aspx_runtime()
        return runtime.execute_command(command_request)

    def upload_file(self, local_file: Path | str, remote_path: str) -> RuntimeArtifact:
        """Upload a local file via the transport upload contract."""
        runtime = self._require_aspx_runtime()
        session = runtime.active_session
        artifact = RuntimeArtifact.new(
            local_path=str(local_file),
            remote_path=remote_path,
        )
        return runtime.upload_artifact(session, artifact)

    def download_file(self, remote_path: str) -> RuntimeArtifact:
        """Download a remote file via the transport download contract."""
        runtime = self._require_aspx_runtime()
        session = runtime.active_session
        artifact = RuntimeArtifact.new(remote_path=remote_path)
        return runtime.download_artifact(session, artifact)

    def fetch_remote_file_via_cat(self, remote_path: str) -> bytes:
        """Read a remote file through the ASPX ``cat`` command transport."""
        from dsp.execution.webshell.cat_transport import read_remote_file_via_cat

        runtime = self._require_aspx_runtime()
        return read_remote_file_via_cat(runtime, remote_path)

    def cleanup(self) -> None:
        """Release runtime session state."""
        runtime = self._runtime
        if runtime is not None:
            runtime.cleanup()

    def _require_aspx_runtime(self) -> AspxWebshellRuntime:
        runtime = self._runtime
        if runtime is None:
            raise AspxProviderNotReadyError(
                "ASPX runtime is not attached; call create_runtime() first",
                field="runtime",
            )
        if not isinstance(runtime, AspxWebshellRuntime):
            raise AspxProviderNotReadyError(
                "attached runtime must be AspxWebshellRuntime",
                field="runtime",
            )
        return runtime
