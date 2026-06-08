"""RemoteScenarioRunner — dispatch scenario execution via webshell command delivery."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dsp.execution.providers.runtime.command import CommandResult
from dsp.execution.remote.exceptions import UnsupportedRemoteProviderError
from dsp.execution.remote.models import (
    TRANSPORT_METADATA_KEYS,
    RemoteScenarioExecutionResult,
    ScenarioExecutionRequest,
)
from dsp.execution.remote.payload import build_scenario_command

if TYPE_CHECKING:
    from dsp.execution.webshell_provider import WebshellExecutionProvider


class RemoteScenarioRunner:
    """Convert scenario execution requests into webshell command delivery.

    Does not interact with Event Store, Validation, Reporting, or Detection.
    """

    def run(
        self,
        request: ScenarioExecutionRequest,
        provider: WebshellExecutionProvider,
        *,
        timeout_seconds: int = 300,
    ) -> RemoteScenarioExecutionResult:
        """Deliver a remote scenario execution command through the webshell provider."""
        self._validate_provider(provider)
        command = build_scenario_command(request, timeout_seconds=timeout_seconds)
        command_result = provider.execute_command(command)
        return self._build_result(request, provider, command_result)

    @staticmethod
    def _validate_provider(provider: object) -> None:
        from dsp.execution.webshell_provider import WebshellExecutionProvider

        if not isinstance(provider, WebshellExecutionProvider):
            provider_type = getattr(provider, "provider_type", type(provider).__name__)
            raise UnsupportedRemoteProviderError(str(provider_type))

    @staticmethod
    def _build_result(
        request: ScenarioExecutionRequest,
        provider: WebshellExecutionProvider,
        command_result: CommandResult,
    ) -> RemoteScenarioExecutionResult:
        execution_metadata = dict(command_result.execution_metadata)
        transport_metadata = {
            key: execution_metadata[key]
            for key in TRANSPORT_METADATA_KEYS
            if key in execution_metadata
        }
        command_metadata = {
            "command_id": command_result.command_id,
            "command_status": command_result.status.value,
        }
        for key, value in execution_metadata.items():
            if key not in TRANSPORT_METADATA_KEYS:
                command_metadata[key] = value

        if command_result.started_at is not None:
            command_metadata["started_at"] = (
                command_result.started_at.isoformat().replace("+00:00", "Z")
            )
        if command_result.completed_at is not None:
            command_metadata["completed_at"] = (
                command_result.completed_at.isoformat().replace("+00:00", "Z")
            )

        return RemoteScenarioExecutionResult.new(
            scenario_id=request.scenario_id,
            transport_metadata=transport_metadata,
            provider_metadata=provider.get_webshell_metadata(),
            command_metadata=command_metadata,
        )
