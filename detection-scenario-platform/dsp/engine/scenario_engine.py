"""Scenario interface per SCENARIO_INTERFACE_FREEZE v1.0.0."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from dsp.event_store import EventStore


class ScenarioSkipError(Exception):
    """Raised from prepare() to skip scenario execution."""


class SafetyViolationError(Exception):
    """Raised when safety constraints are violated — aborts entire run."""


@dataclass
class RunConfig:
    target_net: str = "10.10.10.0/24"
    dry_run: bool = False
    scenario_params: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class RunContext:
    run_id: str
    target_net: str
    event_store: EventStore
    config: RunConfig
    dry_run: bool = False
    cancelled: bool = False
    deadline: datetime | None = None


@dataclass
class ScenarioSummary:
    scenario_id: str
    metrics: dict[str, int | float | str]
    event_count: int
    notes: list[str] = field(default_factory=list)


class Scenario(ABC):
    """Frozen Scenario protocol v1.0.0."""

    @classmethod
    @abstractmethod
    def scenario_id(cls) -> str: ...

    @abstractmethod
    def prepare(self, ctx: RunContext, targets: TargetSet) -> None: ...

    @abstractmethod
    def execute(self, ctx: RunContext, targets: TargetSet) -> None: ...

    @abstractmethod
    def summarize(self, ctx: RunContext) -> ScenarioSummary: ...


@dataclass
class TargetSet:
    """Minimal TargetSet stub for Phase 1A."""

    target_net: str
    hosts: list[str] = field(default_factory=list)
    capabilities: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def stub(cls, target_net: str = "10.10.10.0/24") -> TargetSet:
        from dsp.engine.target_engine import resolve_targets

        return resolve_targets(target_net)
