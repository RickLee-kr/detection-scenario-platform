"""Event Store entity models aligned with EVENT_SCHEMA_FREEZE v1.0.0."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from dsp import EVENT_SCHEMA_VERSION

FORBIDDEN_EVENT_STATUSES = frozenset({"success", "failed", "partial", "skipped"})

ALLOWED_EVENT_STATUSES = frozenset(
    {
        "info",
        "sent",
        "response",
        "nxdomain",
        "timeout",
        "error",
        "connection_refused",
        "dns_failure",
        "auth_failed",
    }
)

ALLOWED_EVENT_SOURCES = frozenset({"local", "remote", "dry_run", "runner"})


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ABORTED = "aborted"
    CONFIG_ERROR = "config_error"


class ValidationDecision(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"
    CODE_FAILURE = "code_failure"


@dataclass
class Run:
    run_id: str
    event_schema_version: str = EVENT_SCHEMA_VERSION
    target_net: str = "10.10.10.0/24"
    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: RunStatus = RunStatus.PENDING
    dry_run: bool = False
    requested_scenarios: list[str] = field(default_factory=list)
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    dsp_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "event_schema_version": self.event_schema_version,
            "target_net": self.target_net,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "status": self.status.value,
            "dry_run": self.dry_run,
            "requested_scenarios": self.requested_scenarios,
            "config_snapshot": self.config_snapshot,
            "dsp_version": self.dsp_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Run:
        started = data.get("started_at")
        ended = data.get("ended_at")
        return cls(
            run_id=data["run_id"],
            event_schema_version=data.get("event_schema_version", EVENT_SCHEMA_VERSION),
            target_net=data.get("target_net", "10.10.10.0/24"),
            started_at=datetime.fromisoformat(started.replace("Z", "+00:00")) if started else None,
            ended_at=datetime.fromisoformat(ended.replace("Z", "+00:00")) if ended else None,
            status=RunStatus(data.get("status", "pending")),
            dry_run=data.get("dry_run", False),
            requested_scenarios=list(data.get("requested_scenarios", [])),
            config_snapshot=dict(data.get("config_snapshot", {})),
            dsp_version=data.get("dsp_version", "1.0.0"),
        )


@dataclass
class Event:
    run_id: str
    scenario_id: str
    timestamp: datetime
    stage: str
    event: str
    status: str
    target: str = ""
    artifact: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    source: str = "local"
    exit_code: int | None = None
    tags: list[str] = field(default_factory=list)
    id: int | None = None
    event_schema_version: str = EVENT_SCHEMA_VERSION

    def validate(self) -> None:
        if self.status in FORBIDDEN_EVENT_STATUSES:
            raise ValueError(f"Forbidden event status: {self.status}")
        if self.status not in ALLOWED_EVENT_STATUSES:
            raise ValueError(f"Unknown event status: {self.status}")
        if self.source not in ALLOWED_EVENT_SOURCES:
            raise ValueError(f"Unknown event source: {self.source}")
        if not self.run_id:
            raise ValueError("run_id is required")


@dataclass
class EventQuery:
    run_id: str
    scenario_id: str | None = None
    event: str | list[str] | None = None
    status: str | list[str] | None = None
    stage: str | None = None


@dataclass
class MetricDef:
    name: str
    event_filter: dict[str, str | list[str]]
    aggregate: str
    json_path: str | None = None


@dataclass
class ValidationResult:
    run_id: str
    scenario_id: str
    decision: ValidationDecision
    reason: str
    metrics: dict[str, int | float | str | bool]
    fail_fast_codes: list[str] = field(default_factory=list)
    validated_at: datetime | None = None
    validation_profile_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "decision": self.decision.value,
            "reason": self.reason,
            "metrics": self.metrics,
            "fail_fast_codes": self.fail_fast_codes,
            "validated_at": (
                self.validated_at.isoformat().replace("+00:00", "Z")
                if self.validated_at
                else None
            ),
            "validation_profile_version": self.validation_profile_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationResult:
        validated = data.get("validated_at")
        return cls(
            run_id=data["run_id"],
            scenario_id=data["scenario_id"],
            decision=ValidationDecision(data["decision"]),
            reason=data["reason"],
            metrics=dict(data.get("metrics", {})),
            fail_fast_codes=list(data.get("fail_fast_codes", [])),
            validated_at=(
                datetime.fromisoformat(validated.replace("Z", "+00:00")) if validated else None
            ),
            validation_profile_version=data.get("validation_profile_version", "1.0.0"),
        )


class EventStoreError(Exception):
    """Base Event Store error."""


class RunClosedError(EventStoreError):
    """Attempted write on a completed run."""


class RunNotOpenError(EventStoreError):
    """Operation requires an open run."""
