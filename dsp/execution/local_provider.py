"""Local execution provider — in-process traffic generation on DSP host."""

from __future__ import annotations

from pathlib import Path

from dsp.engine.orchestrator import run_scenario
from dsp.engine.scenario_engine import RunContext, ScenarioSummary, TargetSet
from dsp.execution.base import ExecutionProvider
from dsp.execution.models import ExecutionContext, ProviderCapabilities
from dsp.plugins.models import PluginRecord


class LocalExecutionProvider(ExecutionProvider):
    """Adapter for current Mode A behavior — scenario runs in-process on DSP host."""

    @property
    def provider_type(self) -> str:
        return "local"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_type="local",
            execution_mode="local",
            traffic_origin="dsp_host",
            supports_udp=True,
            supports_tcp=True,
            supports_http_client=True,
        )

    def prepare(self, context: ExecutionContext) -> None:
        context.execution_metadata.setdefault("traffic_origin_host", "local")

    def execute(
        self,
        context: ExecutionContext,
        record: PluginRecord,
        ctx: RunContext,
        targets: TargetSet,
        *,
        snapshot_dir: Path | None = None,
    ) -> ScenarioSummary | None:
        return run_scenario(record, ctx, targets, snapshot_dir=snapshot_dir)

    def cleanup(self, context: ExecutionContext) -> None:
        pass
