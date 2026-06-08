"""Remote scenario execution data models — transport metadata only."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

FORBIDDEN_RESULT_FIELDS = frozenset(
    {
        "success",
        "failed",
        "detected",
        "attack_success",
        "alert_created",
    }
)

TRANSPORT_METADATA_KEYS = frozenset(
    {
        "delivery_only",
        "request_size",
        "transport_duration_ms",
        "transport_method",
        "transport_response_size",
        "transport_status",
    }
)


@dataclass
class ScenarioExecutionRequest:
    """Minimum payload for remote scenario dispatch."""

    scenario_id: str
    scenario_params: dict[str, Any] = field(default_factory=dict)
    execution_metadata: dict[str, Any] = field(default_factory=dict)
    run_id: str | None = None
    target_net: str | None = None
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_params": dict(self.scenario_params),
            "execution_metadata": dict(self.execution_metadata),
            "run_id": self.run_id,
            "target_net": self.target_net,
            "dry_run": self.dry_run,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScenarioExecutionRequest:
        return cls(
            scenario_id=str(data["scenario_id"]),
            scenario_params=dict(data.get("scenario_params") or {}),
            execution_metadata=dict(data.get("execution_metadata") or {}),
            run_id=data.get("run_id"),
            target_net=data.get("target_net"),
            dry_run=bool(data.get("dry_run", False)),
        )


@dataclass
class RemoteScenarioExecutionResult:
    """Remote scenario delivery outcome — transport metadata only."""

    scenario_id: str
    remote_execution_id: str
    transport_metadata: dict[str, Any] = field(default_factory=dict)
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    command_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for bucket in (
            self.transport_metadata,
            self.provider_metadata,
            self.command_metadata,
        ):
            forbidden = FORBIDDEN_RESULT_FIELDS.intersection(bucket.keys())
            if forbidden:
                raise ValueError(
                    f"forbidden inference fields in result metadata: {sorted(forbidden)}"
                )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "scenario_id": self.scenario_id,
            "remote_execution_id": self.remote_execution_id,
            "transport_metadata": dict(self.transport_metadata),
            "provider_metadata": dict(self.provider_metadata),
            "command_metadata": dict(self.command_metadata),
        }
        forbidden = FORBIDDEN_RESULT_FIELDS.intersection(payload.keys())
        if forbidden:
            raise ValueError(
                f"forbidden inference fields in result: {sorted(forbidden)}"
            )
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RemoteScenarioExecutionResult:
        return cls(
            scenario_id=str(data["scenario_id"]),
            remote_execution_id=str(data["remote_execution_id"]),
            transport_metadata=dict(data.get("transport_metadata") or {}),
            provider_metadata=dict(data.get("provider_metadata") or {}),
            command_metadata=dict(data.get("command_metadata") or {}),
        )

    @classmethod
    def new(
        cls,
        *,
        scenario_id: str,
        remote_execution_id: str | None = None,
        transport_metadata: dict[str, Any] | None = None,
        provider_metadata: dict[str, Any] | None = None,
        command_metadata: dict[str, Any] | None = None,
    ) -> RemoteScenarioExecutionResult:
        return cls(
            scenario_id=scenario_id,
            remote_execution_id=remote_execution_id or uuid4().hex,
            transport_metadata=dict(transport_metadata or {}),
            provider_metadata=dict(provider_metadata or {}),
            command_metadata=dict(command_metadata or {}),
        )
