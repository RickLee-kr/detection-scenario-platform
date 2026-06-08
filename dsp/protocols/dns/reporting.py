"""DNS reporting profile templates and report section builders."""

from __future__ import annotations

from typing import Any

from dsp.event_store import ValidationResult
from dsp.protocols.dns.validation import DNS_METRIC_NAMES


def dns_report_profile(**overrides: Any) -> dict[str, Any]:
    """Standard DNS report_profile block for manifest.yaml."""
    profile: dict[str, Any] = {
        "profile_version": "1.0.0",
        "protocol": "dns",
        "highlight_metrics": list(DNS_METRIC_NAMES),
        "sample_events": 5,
        "sample_filter": {"event": "dns_query_sent"},
    }
    profile.update(overrides)
    return profile


def build_dns_report_section(
    result: ValidationResult,
    event_samples: list[dict[str, Any]] | None = None,
) -> list[str]:
    """
    Build supplementary DNS protocol section for report.md.

    Primary decision row remains ValidationResult-only; this section adds
    protocol context traceable to Store aggregates.
    """
    lines = [
        f"### DNS Protocol — {result.scenario_id}",
        "",
        "| Metric | Value | Store Source |",
        "|--------|-------|--------------|",
    ]
    trace_map = {
        "dns_query_sent_count": "event=dns_query_sent, status=sent",
        "dns_response_count": "event=dns_response_received, status=response",
        "dns_nxdomain_count": "event=dns_response_received, status=nxdomain",
        "dns_timeout_count": "event=dns_timeout, status=timeout",
        "dns_error_count": "event=dns_error, status=error",
    }
    for name in DNS_METRIC_NAMES:
        value = result.metrics.get(name, 0)
        source = trace_map.get(name, "—")
        lines.append(f"| {name} | {value} | {source} |")

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
