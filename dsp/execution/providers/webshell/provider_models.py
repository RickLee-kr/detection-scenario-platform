"""Webshell provider family data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from dsp.execution.webshell.transport.timeout import (
    TIMEOUT_PROFILE_NORMAL,
    VALID_TIMEOUT_PROFILES,
)


class ProviderSessionState(StrEnum):
    """Lifecycle states for a provider session (metadata only — no transport)."""

    CREATED = "created"
    CONNECTED = "connected"
    CLOSED = "closed"
    ERROR = "error"


RESERVED_PROVIDER_TYPES = frozenset({"jsp", "php", "aspx"})
VALID_TRANSPORT_TYPES = frozenset({"http", "https"})


@dataclass
class ProviderCapabilities:
    """Capability matrix exposed by a webshell provider family adapter."""

    upload_supported: bool = False
    download_supported: bool = False
    execute_supported: bool = False
    event_sync_supported: bool = False
    transport_supported: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            "upload_supported": self.upload_supported,
            "download_supported": self.download_supported,
            "execute_supported": self.execute_supported,
            "event_sync_supported": self.event_sync_supported,
            "transport_supported": self.transport_supported,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProviderCapabilities:
        return cls(
            upload_supported=bool(data.get("upload_supported", False)),
            download_supported=bool(data.get("download_supported", False)),
            execute_supported=bool(data.get("execute_supported", False)),
            event_sync_supported=bool(data.get("event_sync_supported", False)),
            transport_supported=bool(data.get("transport_supported", False)),
        )


@dataclass
class ProviderConfiguration:
    """Declarative configuration for a webshell provider instance."""

    provider_type: str
    transport_type: str = "https"
    safe_mode: bool = True
    timeout_profile: str = TIMEOUT_PROFILE_NORMAL
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_type": self.provider_type,
            "transport_type": self.transport_type,
            "safe_mode": self.safe_mode,
            "timeout_profile": self.timeout_profile,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProviderConfiguration:
        return cls(
            provider_type=data["provider_type"],
            transport_type=str(data.get("transport_type", "https")),
            safe_mode=bool(data.get("safe_mode", True)),
            timeout_profile=str(data.get("timeout_profile", TIMEOUT_PROFILE_NORMAL)),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class ProviderSession:
    """Provider session metadata — no network or transport binding."""

    session_id: str
    provider_type: str
    created_at: datetime
    state: ProviderSessionState = ProviderSessionState.CREATED
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "provider_type": self.provider_type,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "state": self.state.value,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProviderSession:
        return cls(
            session_id=data["session_id"],
            provider_type=data["provider_type"],
            created_at=datetime.fromisoformat(
                data["created_at"].replace("Z", "+00:00")
            ),
            state=ProviderSessionState(data["state"]),
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def new(
        cls,
        provider_type: str,
        *,
        session_id: str | None = None,
        state: ProviderSessionState = ProviderSessionState.CREATED,
    ) -> ProviderSession:
        """Create a new session record without transport side effects."""
        return cls(
            session_id=session_id or uuid4().hex,
            provider_type=provider_type,
            created_at=datetime.now(timezone.utc),
            state=state,
        )

    def transition(self, new_state: ProviderSessionState) -> ProviderSession:
        """Return a copy with an updated lifecycle state."""
        return ProviderSession(
            session_id=self.session_id,
            provider_type=self.provider_type,
            created_at=self.created_at,
            state=new_state,
            metadata=dict(self.metadata),
        )
