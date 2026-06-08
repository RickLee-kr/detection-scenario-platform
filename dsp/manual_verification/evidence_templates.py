"""Evidence summary template generation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

EVIDENCE_SUMMARY_FILENAME = "evidence_summary_template.md"


def generate_evidence_summary_template(
    run_id: str,
    output_directory: Path,
    *,
    event_count: int,
    evidence_files: list[str],
    generated_time: datetime | None = None,
) -> Path:
    """Write evidence_summary_template.md with factual fields only."""
    output_directory.mkdir(parents=True, exist_ok=True)
    path = output_directory / EVIDENCE_SUMMARY_FILENAME

    timestamp = generated_time or datetime.now(timezone.utc)
    generated_at = timestamp.isoformat().replace("+00:00", "Z")

    evidence_list = "\n".join(f"- {file_path}" for file_path in evidence_files) or "- (none)"

    lines = [
        "# Evidence Summary",
        "",
        f"Run ID: {run_id}",
        "",
        "## Evidence Files",
        "",
        evidence_list,
        "",
        f"Event Count: {event_count}",
        "",
        f"Generated Time: {generated_at}",
        "",
        "## Reviewer Notes",
        "",
        "________________________",
        "",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path
