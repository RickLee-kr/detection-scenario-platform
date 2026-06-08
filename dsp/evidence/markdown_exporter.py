"""Markdown evidence export — Event Store data only, no interpretation."""

from __future__ import annotations

from pathlib import Path

from dsp.event_store.models import Event


def export_run_markdown(events: list[Event], run_id: str, output_directory: Path) -> Path:
    """Write run_<run_id>.md with run info and chronological event listing."""
    output_directory.mkdir(parents=True, exist_ok=True)
    path = output_directory / f"run_{run_id}.md"

    lines: list[str] = [
        "# Run Information",
        "",
        f"Run ID: {run_id}",
        "",
        "# Event Summary",
        "",
        f"Total Events: {len(events)}",
        "",
        "# Events",
        "",
    ]

    for event in events:
        timestamp = event.timestamp.isoformat().replace("+00:00", "Z")
        lines.append(f"- timestamp: {timestamp}")
        lines.append(f"  event_type: {event.event}")
        lines.append(f"  source: {event.source}")
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path
