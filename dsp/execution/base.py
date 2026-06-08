"""ExecutionProvider interface — pluggable traffic origin abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from dsp.engine.scenario_engine import RunContext, ScenarioSummary, TargetSet
from dsp.execution.models import ExecutionContext, ProviderCapabilities
from dsp.plugins.models import PluginRecord


class ExecutionProvider(ABC):
    """Decides WHERE scenario traffic is generated. Scenario-agnostic."""

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Stable provider identifier (e.g. 'local')."""

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Return provider capability matrix."""

    @abstractmethod
    def prepare(self, context: ExecutionContext) -> None:
        """Establish transport and runtime prerequisites for a run."""

    @abstractmethod
    def execute(
        self,
        context: ExecutionContext,
        record: PluginRecord,
        ctx: RunContext,
        targets: TargetSet,
        *,
        snapshot_dir: Path | None = None,
    ) -> ScenarioSummary | None:
        """Run one scenario through this provider's transport."""

    @abstractmethod
    def cleanup(self, context: ExecutionContext) -> None:
        """Teardown sessions and release provider resources."""
