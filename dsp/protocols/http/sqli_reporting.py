"""SQL injection reporting profile templates and report section builders."""

from __future__ import annotations

from typing import Any

from dsp.event_store import ValidationResult
from dsp.protocols.http.sqli_validation import SQL_INJECTION_METRIC_NAMES


def sql_injection_report_profile(**overrides: Any) -> dict[str, Any]:
    """Standard SQL injection report_profile block for manifest.yaml."""
    profile: dict[str, Any] = {
        "profile_version": "1.0.0",
        "protocol": "sql_injection",
        "highlight_metrics": list(SQL_INJECTION_METRIC_NAMES),
        "sample_events": 5,
        "sample_filter": {"event": "sql_request_sent"},
    }
    profile.update(overrides)
    return profile


def build_sql_injection_report_section(
    result: ValidationResult,
    event_samples: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
) -> list[str]:
    """Build supplementary SQL Injection section for report.md."""
    summary = summary or {}
    lines = [
        f"### SQL Injection — {result.scenario_id}",
        "",
        "| Metric | Value | Store Source |",
        "|--------|-------|--------------|",
    ]
    trace_map = {
        "sql_payload_generated_count": "event=sql_payload_generated, status=info",
        "sql_request_sent_count": "event=sql_request_sent, status=sent",
    }
    for name in SQL_INJECTION_METRIC_NAMES:
        value = result.metrics.get(name, 0)
        source = trace_map.get(name, "—")
        lines.append(f"| {name} | {value} | {source} |")

    targets = summary.get("targets", [])
    sample_urls = summary.get("sample_urls", [])
    sample_payloads = summary.get("sample_payloads", [])
    duration = summary.get("duration_sec")
    request_count = summary.get("request_count")
    payload_count = summary.get("payload_count")

    lines.extend(["", "**SQL Injection Summary**", ""])
    if targets:
        lines.append(f"- **Targets:** {', '.join(str(t) for t in targets)}")
    if request_count is not None:
        lines.append(f"- **Request count:** {request_count}")
    if payload_count is not None:
        lines.append(f"- **Payload count:** {payload_count}")
    else:
        lines.append(
            f"- **Payload count:** {result.metrics.get('sql_payload_generated_count', 0)}"
        )
    if duration is not None:
        lines.append(f"- **Duration:** {duration}s")
    if sample_urls:
        lines.append(f"- **Sample URLs:** {', '.join(sample_urls[:5])}")
    if sample_payloads:
        lines.append(f"- **Sample payloads:** {', '.join(sample_payloads[:5])}")

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
