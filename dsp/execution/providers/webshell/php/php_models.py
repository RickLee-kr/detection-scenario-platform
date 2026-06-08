"""PHP webshell provider session model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dsp.execution.providers.webshell.common.generic_models import (
    GenericWebshellSession,
)
from dsp.execution.providers.webshell.provider_models import ProviderSessionState

PHP_PROVIDER_VERSION = "1.0.0"


@dataclass
class PhpProviderSession(GenericWebshellSession):
    """PHP provider session metadata — extends generic session with PHP defaults."""

    provider_version: str = PHP_PROVIDER_VERSION

    @classmethod
    def new(
        cls,
        provider_type: str = "php",
        *,
        session_id: str | None = None,
        state: ProviderSessionState = ProviderSessionState.CREATED,
        webshell_url: str = "",
        transport_type: str = "https",
        provider_version: str = PHP_PROVIDER_VERSION,
        metadata: dict[str, Any] | None = None,
    ) -> PhpProviderSession:
        """Create a PHP session record without transport side effects."""
        return super().new(
            provider_type=provider_type,
            session_id=session_id,
            state=state,
            webshell_url=webshell_url,
            transport_type=transport_type,
            provider_version=provider_version,
            metadata=metadata,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PhpProviderSession:
        base = GenericWebshellSession.from_dict(data)
        return cls(
            session_id=base.session_id,
            provider_type=base.provider_type,
            created_at=base.created_at,
            state=base.state,
            metadata=base.metadata,
            webshell_url=base.webshell_url,
            transport_type=base.transport_type,
            provider_version=str(data.get("provider_version", PHP_PROVIDER_VERSION)),
        )
