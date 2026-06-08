"""GenericWebshellProvider — shared mock-first adapter base (no execution)."""

from __future__ import annotations

from typing import Any, ClassVar

from dsp.execution.providers.runtime.command import CommandExecutionPolicy
from dsp.execution.providers.runtime.runtime_capabilities import RuntimeCapabilities
from dsp.execution.providers.runtime.runtime_contract import ProviderRuntimeContract
from dsp.execution.providers.webshell.base_provider import WebshellProviderBase
from dsp.execution.providers.webshell.common.generic_models import (
    GENERIC_PROVIDER_VERSION,
    GenericWebshellSession,
)
from dsp.execution.providers.webshell.provider_exceptions import (
    ProviderConfigurationError,
)
from dsp.execution.providers.webshell.provider_models import (
    ProviderCapabilities,
    ProviderConfiguration,
)
from dsp.execution.webshell.transport.base import WebshellTransport


class GenericWebshellProvider(WebshellProviderBase):
    """Shared webshell family adapter — metadata, validation, and session only.

    Subclasses declare ``provider_type``, ``provider_name``, and ``session_class``
    only. Must NOT execute commands, transfer files, invoke transport, or open
    network connections.
    """

    provider_type: ClassVar[str]
    provider_name: ClassVar[str]
    session_class: ClassVar[type[GenericWebshellSession]]
    provider_version: ClassVar[str] = GENERIC_PROVIDER_VERSION

    def __init__(
        self,
        transport: WebshellTransport | None = None,
        *,
        webshell_url: str = "",
        transport_type: str = "https",
    ) -> None:
        self._transport = transport
        self._webshell_url = webshell_url
        self._transport_type = transport_type
        self._runtime: ProviderRuntimeContract | None = None

    @property
    def transport(self) -> WebshellTransport | None:
        """Attached transport reference (never invoked in this phase)."""
        return self._transport

    def get_capabilities(self) -> ProviderCapabilities:
        """Return declared capability intent — not implementation status."""
        return ProviderCapabilities(
            upload_supported=True,
            download_supported=True,
            execute_supported=True,
            event_sync_supported=True,
            transport_supported=True,
        )

    def get_runtime_capabilities(self) -> RuntimeCapabilities:
        """Return runtime lifecycle capabilities — True when runtime is attached."""
        if self._runtime is not None:
            return RuntimeCapabilities(
                supports_connect=True,
                supports_upload=True,
                supports_download=True,
                supports_event_bundle=True,
                supports_healthcheck=True,
                supports_cleanup=True,
            )
        return RuntimeCapabilities()

    def get_command_capabilities(self) -> CommandExecutionPolicy:
        """Return command execution policy from attached runtime when available."""
        runtime = self._runtime
        if runtime is not None and hasattr(runtime, "command_policy"):
            return runtime.command_policy
        return CommandExecutionPolicy()

    def supports_command_event_ingestion(self) -> bool:
        """Return whether provider declares command-event ingestion capability."""
        return False

    def supports_command_correlation(self) -> bool:
        """Return whether provider declares command correlation capability."""
        return False

    def attach_runtime(self, runtime: ProviderRuntimeContract) -> None:
        """Store runtime reference — never auto-connects or executes."""
        self._runtime = runtime

    def get_runtime(self) -> ProviderRuntimeContract | None:
        """Return attached runtime reference if present."""
        return self._runtime

    def get_metadata(self) -> dict[str, Any]:
        metadata = super().get_metadata()
        metadata["provider_version"] = self.provider_version
        return metadata

    def validate_configuration(self, config: ProviderConfiguration) -> None:
        """Validate provider configuration without side effects."""
        if config.provider_type != self.provider_type:
            raise ProviderConfigurationError(
                f"provider_type mismatch: expected {self.provider_type!r}, "
                f"got {config.provider_type!r}",
                field="provider_type",
            )
        if not config.transport_type:
            raise ProviderConfigurationError(
                "transport_type must be defined",
                field="transport_type",
            )
        if not isinstance(config.safe_mode, bool):
            raise ProviderConfigurationError(
                "safe_mode must be defined as bool",
                field="safe_mode",
            )
        if not config.timeout_profile:
            raise ProviderConfigurationError(
                "timeout_profile must be defined",
                field="timeout_profile",
            )
        super().validate_configuration(config)

    def create_session(
        self,
        *,
        webshell_url: str | None = None,
        transport_type: str | None = None,
    ) -> GenericWebshellSession:
        """Declare a new session record in CREATED state (no transport)."""
        return self.session_class.new(
            provider_type=self.provider_type,
            webshell_url=webshell_url if webshell_url is not None else self._webshell_url,
            transport_type=transport_type if transport_type is not None else self._transport_type,
            provider_version=self.provider_version,
        )
