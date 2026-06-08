"""DNS Tunnel reporting profile templates and report section builders."""

from __future__ import annotations

from typing import Any

from dsp.event_store import ValidationResult
from dsp.protocols.dns.tunnel_validation import DNS_TUNNEL_METRIC_NAMES


def dns_tunnel_report_profile(**overrides: Any) -> dict[str, Any]:
    """Standard DNS Tunnel report_profile block for manifest.yaml."""
    profile: dict[str, Any] = {
        "profile_version": "1.0.0",
        "protocol": "dns_tunnel",
        "highlight_metrics": list(DNS_TUNNEL_METRIC_NAMES),
        "sample_events": 5,
        "sample_filter": {"event": "dns_tunnel_query_sent"},
    }
    profile.update(overrides)
    return profile


def build_dns_tunnel_report_section(
    result: ValidationResult,
    event_samples: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
) -> list[str]:
    """Build supplementary DNS Tunnel section for report.md."""
    summary = summary or {}
    lines = [
        f"### DNS Tunnel — {result.scenario_id}",
        "",
        "| Metric | Value | Store Source |",
        "|--------|-------|--------------|",
    ]
    trace_map = {
        "dns_tunnel_chunk_created_count": "event=dns_tunnel_chunk_created, status=info",
        "dns_tunnel_query_sent_count": "event=dns_tunnel_query_sent, status=sent",
    }
    for name in DNS_TUNNEL_METRIC_NAMES:
        value = result.metrics.get(name, 0)
        source = trace_map.get(name, "—")
        lines.append(f"| {name} | {value} | {source} |")

    targets = summary.get("targets", [])
    duration = summary.get("duration_sec")
    sample_fqdns = summary.get("sample_fqdns", [])

    lines.extend(["", "**Tunnel Summary**", ""])
    if targets:
        lines.append(f"- **Targets:** {', '.join(str(t) for t in targets)}")
    if duration is not None:
        lines.append(f"- **Duration:** {duration}s")
    if sample_fqdns:
        lines.append(f"- **Sample FQDNs:** {', '.join(sample_fqdns[:5])}")

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
