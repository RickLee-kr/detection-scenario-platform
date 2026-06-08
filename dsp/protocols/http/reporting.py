"""HTTP Follow-up reporting profile templates and report section builders."""

from __future__ import annotations

from typing import Any

from dsp.event_store import ValidationResult
from dsp.protocols.http.validation import HTTP_FOLLOWUP_METRIC_NAMES


def http_followup_report_profile(**overrides: Any) -> dict[str, Any]:
    """Standard HTTP Follow-up report_profile block for manifest.yaml."""
    profile: dict[str, Any] = {
        "profile_version": "1.0.0",
        "protocol": "http_followup",
        "highlight_metrics": list(HTTP_FOLLOWUP_METRIC_NAMES),
        "sample_events": 5,
        "sample_filter": {"event": "http_request_sent"},
    }
    profile.update(overrides)
    return profile


def build_http_followup_report_section(
    result: ValidationResult,
    event_samples: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
) -> list[str]:
    """Build supplementary HTTP Follow-up section for report.md."""
    summary = summary or {}
    lines = [
        f"### HTTP Follow-up — {result.scenario_id}",
        "",
        "| Metric | Value | Store Source |",
        "|--------|-------|--------------|",
    ]
    trace_map = {
        "http_request_sent_count": "event=http_request_sent, status=sent",
        "http_response_received_count": "event=http_response_received, status=response",
    }
    for name in HTTP_FOLLOWUP_METRIC_NAMES:
        value = result.metrics.get(name, 0)
        source = trace_map.get(name, "—")
        lines.append(f"| {name} | {value} | {source} |")

    targets = summary.get("targets", [])
    ports_used = summary.get("ports_used", [])
    sample_urls = summary.get("sample_urls", [])
    duration = summary.get("duration_sec")
    request_count = summary.get("request_count")

    lines.extend(["", "**HTTP Follow-up Summary**", ""])
    if targets:
        lines.append(f"- **Targets:** {', '.join(str(t) for t in targets)}")
    if ports_used:
        lines.append(f"- **Ports used:** {', '.join(str(p) for p in ports_used)}")
    if request_count is not None:
        lines.append(f"- **Request count:** {request_count}")
    lines.append(f"- **Response count:** {result.metrics.get('http_response_received_count', 0)}")
    if duration is not None:
        lines.append(f"- **Duration:** {duration}s")
    if sample_urls:
        lines.append(f"- **Sample URLs:** {', '.join(sample_urls[:5])}")

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
