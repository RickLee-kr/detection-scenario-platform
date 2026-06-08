"""LDAP enumeration reporting profile templates and report section builders."""

from __future__ import annotations

from typing import Any

from dsp.event_store import ValidationResult
from dsp.protocols.ldap.ldap_validation import LDAP_ENUM_METRIC_NAMES


def ldap_enumeration_report_profile(**overrides: Any) -> dict[str, Any]:
    """Standard LDAP enumeration report_profile block for manifest.yaml."""
    profile: dict[str, Any] = {
        "profile_version": "1.0.0",
        "protocol": "ldap_enumeration",
        "highlight_metrics": list(LDAP_ENUM_METRIC_NAMES),
        "sample_events": 5,
        "sample_filter": {"event": "ldap_search_attempt"},
    }
    profile.update(overrides)
    return profile


def build_ldap_enumeration_report_section(
    result: ValidationResult,
    event_samples: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
) -> list[str]:
    """Build supplementary LDAP Enumeration section for report.md."""
    summary = summary or {}
    lines = [
        f"### LDAP Enumeration — {result.scenario_id}",
        "",
        "| Metric | Value | Store Source |",
        "|--------|-------|--------------|",
    ]
    trace_map = {
        "ldap_connection_attempt_count": "event=ldap_connection_attempt, status=sent",
        "ldap_bind_attempt_count": "event=ldap_bind_attempt, status=sent",
        "ldap_search_attempt_count": "event=ldap_search_attempt, status=sent",
        "ldap_bind_or_search_attempt_count": "event=ldap_bind_attempt|ldap_search_attempt",
        "ldap_bind_failed_count": "event=ldap_bind_failed",
        "ldap_search_failed_count": "event=ldap_search_failed",
    }
    for name in LDAP_ENUM_METRIC_NAMES:
        value = result.metrics.get(name, 0)
        source = trace_map.get(name, "—")
        lines.append(f"| {name} | {value} | {source} |")

    hosts = summary.get("hosts", summary.get("targets", []))
    ports = summary.get("ports", [])
    filters = summary.get("sample_filters", [])
    connection_count = summary.get("connection_attempt_count")
    bind_count = summary.get("bind_attempt_count")
    search_count = summary.get("search_attempt_count")
    duration = summary.get("duration_sec")

    lines.extend(["", "**LDAP Enumeration Summary**", ""])
    if hosts:
        lines.append(f"- **Hosts targeted:** {', '.join(str(h) for h in hosts)}")
    if ports:
        lines.append(f"- **Ports targeted:** {', '.join(str(p) for p in ports)}")
    if connection_count is not None:
        lines.append(f"- **Connection attempts:** {connection_count}")
    if bind_count is not None:
        lines.append(f"- **Bind attempts:** {bind_count}")
    if search_count is not None:
        lines.append(f"- **Search attempts:** {search_count}")
    if filters:
        lines.append(f"- **Sample filters:** {', '.join(str(f) for f in filters[:4])}")
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
