"""Execution context and capability models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderCapabilities:
    """Describes what an execution provider can do — scenario-agnostic."""

    provider_type: str
    execution_mode: str  # "local" | "remote"
    traffic_origin: str  # "dsp_host" | "remote_host"
    supports_udp: bool = True
    supports_tcp: bool = True
    supports_http_client: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_type": self.provider_type,
            "execution_mode": self.execution_mode,
            "traffic_origin": self.traffic_origin,
            "supports_udp": self.supports_udp,
            "supports_tcp": self.supports_tcp,
            "supports_http_client": self.supports_http_client,
        }


@dataclass
class ExecutionContext:
    """Provider-scoped runtime context for a run or single scenario execution."""

    run_id: str
    target_net: str
    dry_run: bool
    provider_type: str
    provider_config: dict[str, Any] = field(default_factory=dict)
    scenario_id: str | None = None
    execution_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "target_net": self.target_net,
            "dry_run": self.dry_run,
            "provider_type": self.provider_type,
            "provider_config": self.provider_config,
            "scenario_id": self.scenario_id,
            "execution_metadata": self.execution_metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionContext:
        return cls(
            run_id=data["run_id"],
            target_net=data["target_net"],
            dry_run=data["dry_run"],
            provider_type=data["provider_type"],
            provider_config=dict(data.get("provider_config") or {}),
            scenario_id=data.get("scenario_id"),
            execution_metadata=dict(data.get("execution_metadata") or {}),
        )
