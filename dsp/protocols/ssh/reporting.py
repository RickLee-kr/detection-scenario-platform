"""SSH login failure reporting profile templates and report section builders."""

from __future__ import annotations

from typing import Any

from dsp.event_store import ValidationResult
from dsp.protocols.ssh.validation import SSH_FAILURE_METRIC_NAMES


def ssh_failure_report_profile(**overrides: Any) -> dict[str, Any]:
    """Standard SSH login failure report_profile block for manifest.yaml."""
    profile: dict[str, Any] = {
        "profile_version": "1.0.0",
        "protocol": "ssh_failure",
        "highlight_metrics": list(SSH_FAILURE_METRIC_NAMES),
        "sample_events": 5,
        "sample_filter": {"event": "ssh_auth_attempt"},
    }
    profile.update(overrides)
    return profile


def build_ssh_failure_report_section(
    result: ValidationResult,
    event_samples: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
) -> list[str]:
    """Build supplementary SSH Login Failure section for report.md."""
    summary = summary or {}
    lines = [
        f"### SSH Login Failure — {result.scenario_id}",
        "",
        "| Metric | Value | Store Source |",
        "|--------|-------|--------------|",
    ]
    trace_map = {
        "ssh_auth_attempt_count": "event=ssh_auth_attempt, status=sent",
        "ssh_auth_failed_count": "event=ssh_auth_failed, status=auth_failed",
    }
    for name in SSH_FAILURE_METRIC_NAMES:
        value = result.metrics.get(name, 0)
        source = trace_map.get(name, "—")
        lines.append(f"| {name} | {value} | {source} |")

    targets = summary.get("targets", [])
    sample_usernames = summary.get("sample_usernames", [])
    duration = summary.get("duration_sec")
    attempt_count = summary.get("attempt_count")
    failure_count = summary.get("failure_count")

    lines.extend(["", "**SSH Login Failure Summary**", ""])
    if targets:
        lines.append(f"- **Targets:** {', '.join(str(t) for t in targets)}")
    if attempt_count is not None:
        lines.append(f"- **Attempt count:** {attempt_count}")
    if failure_count is not None:
        lines.append(f"- **Failure count:** {failure_count}")
    else:
        lines.append(
            f"- **Failure count:** {result.metrics.get('ssh_auth_failed_count', 0)}"
        )
    if sample_usernames:
        lines.append(
            f"- **Sample usernames:** {', '.join(str(u) for u in sample_usernames[:5])}"
        )
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
