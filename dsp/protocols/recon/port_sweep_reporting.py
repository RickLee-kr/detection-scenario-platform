"""Port sweep reporting profile templates and report section builders."""

from __future__ import annotations

from typing import Any

from dsp.event_store import ValidationResult
from dsp.protocols.recon.port_sweep_validation import PORT_SWEEP_METRIC_NAMES


def port_sweep_report_profile(**overrides: Any) -> dict[str, Any]:
    """Standard port sweep report_profile block for manifest.yaml."""
    profile: dict[str, Any] = {
        "profile_version": "1.0.0",
        "protocol": "port_sweep",
        "highlight_metrics": list(PORT_SWEEP_METRIC_NAMES),
        "sample_events": 5,
        "sample_filter": {"event": "port_probe_sent"},
    }
    profile.update(overrides)
    return profile


def build_port_sweep_report_section(
    result: ValidationResult,
    event_samples: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
) -> list[str]:
    """Build supplementary Port Sweep section for report.md."""
    summary = summary or {}
    lines = [
        f"### Port Sweep — {result.scenario_id}",
        "",
        "| Metric | Value | Store Source |",
        "|--------|-------|--------------|",
    ]
    trace_map = {
        "port_probe_count": "event=port_probe_sent, status=sent",
        "port_connection_attempt_count": "event=port_connection_opened|port_connection_failed",
        "port_connection_success_count": "event=port_connection_opened, status=sent",
        "port_connection_failure_count": "event=port_connection_failed",
    }
    for name in PORT_SWEEP_METRIC_NAMES:
        value = result.metrics.get(name, 0)
        source = trace_map.get(name, "—")
        lines.append(f"| {name} | {value} | {source} |")

    hosts = summary.get("hosts", summary.get("targets", []))
    ports = summary.get("ports", [])
    probe_count = summary.get("probe_count")
    success_count = summary.get("connection_success_count")
    failure_count = summary.get("connection_failure_count")
    duration = summary.get("duration_sec")

    lines.extend(["", "**Port Sweep Summary**", ""])
    if hosts:
        lines.append(f"- **Hosts targeted:** {', '.join(str(h) for h in hosts)}")
    if ports:
        lines.append(f"- **Ports targeted:** {', '.join(str(p) for p in ports)}")
    if probe_count is not None:
        lines.append(f"- **Probe count:** {probe_count}")
    else:
        lines.append(f"- **Probe count:** {result.metrics.get('port_probe_count', 0)}")
    if success_count is not None:
        lines.append(f"- **Connection success count:** {success_count}")
    else:
        lines.append(
            f"- **Connection success count:** "
            f"{result.metrics.get('port_connection_success_count', 0)}"
        )
    if failure_count is not None:
        lines.append(f"- **Connection failure count:** {failure_count}")
    else:
        lines.append(
            f"- **Connection failure count:** "
            f"{result.metrics.get('port_connection_failure_count', 0)}"
        )
    lines.append(f"- **Validation status:** {result.decision.value}")
    if duration is not None:
        lines.append(f"- **Duration:** {duration}s")

    lines.extend(
        [
            "",
            f"**Decision:** {result.decision.value} ({result.reason})",
            "",
        ]
    )

    if event_samples:
        lines.append(f"**Sample events:** {len(event_samples)} excerpt(s) from Event Store")
        lines.append("")

    return lines
