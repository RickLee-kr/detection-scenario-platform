"""Human-readable progress and evidence output for operational `dsp run`."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, TextIO

from dsp.runner.traffic_summary import (
    format_scenario_traffic_block,
    traffic_lines_for_scenario,
)
from dsp.runtime.operational_profiles import scenario_display_name

_PROVIDER_LABELS = {
    "local": "local",
    "webshell": "webshell",
}


def format_duration(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    total = max(0, int(seconds))
    return str(timedelta(seconds=total))


class OperationalConsole:
    """Emit structured progress lines during an operational run."""

    def __init__(
        self,
        *,
        provider: str = "local",
        target_net: str = "",
        profile: str | None = None,
        stream: TextIO | None = None,
    ) -> None:
        self.provider = provider
        self.target_net = target_net
        self.profile = profile
        self._stream = stream or sys.stdout
        self._run_started = False
        self._traffic_summaries: dict[str, dict[str, Any]] = {}

    def handle_progress(self, phase: str, data: dict[str, Any]) -> None:
        if phase == "run_started":
            self._emit_run_started(data)
        elif phase == "discovery_started":
            self._write("Discovery Started")
        elif phase == "discovery_completed":
            hosts = data.get("hosts_found", 0)
            self._write("Discovery Completed")
            self._write(f"Hosts Found: {hosts}")
            self._write("")
            self._write("Scenario Execution Started")
            self._write("")
        elif phase == "scenario_started":
            pass
        elif phase == "scenario_completed":
            sid = data.get("scenario_id", "")
            metrics = data.get("metrics") or {}
            if sid:
                if metrics:
                    self._traffic_summaries[sid] = dict(metrics)
                self._write(f"{scenario_display_name(sid)} Completed")
                for label, value in traffic_lines_for_scenario(sid, metrics):
                    self._write(f"  {label}={value}")
                self._write("")
        elif phase == "evidence_generated":
            self._write("Evidence Generated")
            self._write("")
        elif phase == "run_completed":
            duration = data.get("duration_sec", 0.0)
            events = data.get("event_count", 0)
            raw_summaries = data.get("summaries")
            if raw_summaries:
                self._traffic_summaries = self._normalize_summaries(raw_summaries)
            self._write("Run Completed")
            self._write("")
            self._write(f"Duration: {format_duration(duration)}")
            self._write(f"Events Generated: {events}")
            self._write("")

    def print_traffic_summary(self) -> None:
        """Print aggregated per-scenario traffic counters."""
        if not self._traffic_summaries:
            return
        self._write("Traffic Summary")
        self._write("")
        for scenario_id, metrics in self._traffic_summaries.items():
            block = format_scenario_traffic_block(scenario_id, metrics)
            if not block:
                continue
            for line in block:
                self._write(line)
            self._write("")

    def _emit_run_started(self, data: dict[str, Any]) -> None:
        if self._run_started:
            return
        self._run_started = True
        profile = data.get("profile") or self.profile or "normal"
        provider = data.get("provider") or self.provider
        target_net = data.get("target_net") or self.target_net
        self._write("DSP Run Started")
        self._write("")
        self._write(f"Provider: {_PROVIDER_LABELS.get(provider, provider)}")
        self._write(f"Target Net: {target_net}")
        self._write(f"Profile: {profile}")
        self._write("")

    def print_evidence_summary(self, run_dir: Path) -> None:
        """Print artifact paths after run completion."""
        self.print_traffic_summary()
        self._write("Evidence Summary")
        self._write("")
        self._write("Run Directory:")
        self._write(str(run_dir.resolve()))
        self._write("")
        self._write("Events:")
        self._write("events.jsonl")
        self._write("")
        self._write("Report:")
        self._write("report.md")
        self._write("")
        self._write("Validation:")
        self._write("validation.json")

    @staticmethod
    def _normalize_summaries(
        summaries: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        normalized: dict[str, dict[str, Any]] = {}
        for scenario_id, payload in summaries.items():
            if isinstance(payload, dict) and "metrics" in payload:
                normalized[scenario_id] = dict(payload["metrics"])
            elif isinstance(payload, dict):
                normalized[scenario_id] = dict(payload)
        return normalized

    def _write(self, line: str) -> None:
        print(line, file=self._stream, flush=True)
