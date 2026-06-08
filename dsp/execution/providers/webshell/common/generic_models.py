"""Generic webshell provider session model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from dsp.execution.providers.webshell.provider_models import (
    ProviderSession,
    ProviderSessionState,
)

GENERIC_PROVIDER_VERSION = "1.0.0"


@dataclass
class GenericWebshellSession(ProviderSession):
    """Shared webshell session metadata — common fields for all family adapters."""

    webshell_url: str = ""
    transport_type: str = "https"
    provider_version: str = GENERIC_PROVIDER_VERSION

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "webshell_url": self.webshell_url,
                "transport_type": self.transport_type,
                "provider_version": self.provider_version,
            }
        )
        return base

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GenericWebshellSession:
        return cls(
            session_id=data["session_id"],
            provider_type=data["provider_type"],
            created_at=datetime.fromisoformat(
                data["created_at"].replace("Z", "+00:00")
            ),
            state=ProviderSessionState(data["state"]),
            metadata=dict(data.get("metadata") or {}),
            webshell_url=str(data.get("webshell_url", "")),
            transport_type=str(data.get("transport_type", "https")),
            provider_version=str(
                data.get("provider_version", GENERIC_PROVIDER_VERSION)
            ),
        )

    @classmethod
    def new(
        cls,
        provider_type: str,
        *,
        session_id: str | None = None,
        state: ProviderSessionState = ProviderSessionState.CREATED,
        webshell_url: str = "",
        transport_type: str = "https",
        provider_version: str = GENERIC_PROVIDER_VERSION,
        metadata: dict[str, Any] | None = None,
    ) -> GenericWebshellSession:
        """Create a session record without transport side effects."""
        return cls(
            session_id=session_id or uuid4().hex,
            provider_type=provider_type,
            created_at=datetime.now(timezone.utc),
            state=state,
            metadata=dict(metadata or {}),
            webshell_url=webshell_url,
            transport_type=transport_type,
            provider_version=provider_version,
        )
