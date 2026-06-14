"""PhpWebshellProvider — PHP family adapter with real execution via runtime."""

from __future__ import annotations

from pathlib import Path

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
from dsp.execution.providers.webshell.php.php_exceptions import (
    PhpProviderError,
    PhpProviderNotReadyError,
)
from dsp.execution.providers.webshell.php.php_models import (
    PHP_PROVIDER_VERSION,
    PhpProviderSession,
)
from dsp.execution.providers.webshell.php.php_runtime import PhpWebshellRuntime


class PhpWebshellProvider(GenericWebshellProvider):
    """PHP webshell provider — delegates execution to ``PhpWebshellRuntime``."""

    provider_type = "php"
    provider_name = "PHP Webshell Provider"
    session_class = PhpProviderSession
    provider_version = PHP_PROVIDER_VERSION

    def create_runtime(
        self,
        *,
        config: TransportRuntimeConfiguration | None = None,
        enable_healthcheck_on_connect: bool = True,
    ) -> PhpWebshellRuntime:
        """Build a PHP runtime bound to this provider's transport and URL."""
        if self._transport is None:
            raise PhpProviderNotReadyError(
                "transport is required to create PHP runtime",
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
        runtime = PhpWebshellRuntime(
            self._transport,
            provider_type=self.provider_type,
            webshell_url=self._webshell_url,
            config=runtime_config,
        )
        self.attach_runtime(runtime)
        return runtime

    def connect(self) -> None:
        """Create a remote session and connect through the attached runtime."""
        runtime = self._require_php_runtime()
        runtime.create_remote_session()
        runtime.connect()

    def execute_command(
        self,
        request: CommandRequest | str,
        *,
        arguments: list[str] | None = None,
        timeout_seconds: int = 300,
    ) -> CommandResult:
        """Execute a command through the PHP webshell transport path."""
        if isinstance(request, str):
            command_request = CommandRequest.new(
                request,
                arguments=arguments,
                timeout_seconds=timeout_seconds,
            )
        else:
            command_request = request
        runtime = self._require_php_runtime()
        return runtime.execute_command(command_request)

    def upload_file(self, local_file: Path | str, remote_path: str) -> RuntimeArtifact:
        """Upload a local file via the transport upload contract."""
        runtime = self._require_php_runtime()
        session = runtime.active_session
        artifact = RuntimeArtifact.new(
            local_path=str(local_file),
            remote_path=remote_path,
        )
        return runtime.upload_artifact(session, artifact)

    def download_file(self, remote_path: str) -> RuntimeArtifact:
        """Download a remote file via the transport download contract."""
        runtime = self._require_php_runtime()
        session = runtime.active_session
        artifact = RuntimeArtifact.new(remote_path=remote_path)
        return runtime.download_artifact(session, artifact)

    def fetch_remote_file_via_cat(self, remote_path: str) -> bytes:
        """Read a remote file through the PHP ``cat`` command transport."""
        from dsp.execution.webshell.cat_transport import read_remote_file_via_cat

        runtime = self._require_php_runtime()
        return read_remote_file_via_cat(runtime, remote_path)

    def cleanup(self) -> None:
        """Release runtime session state."""
        runtime = self._runtime
        if runtime is not None:
            runtime.cleanup()

    def _require_php_runtime(self) -> PhpWebshellRuntime:
        runtime = self._runtime
        if runtime is None:
            raise PhpProviderNotReadyError(
                "PHP runtime is not attached; call create_runtime() first",
                field="runtime",
            )
        if not isinstance(runtime, PhpWebshellRuntime):
            raise PhpProviderNotReadyError(
                "attached runtime must be PhpWebshellRuntime",
                field="runtime",
            )
        return runtime
