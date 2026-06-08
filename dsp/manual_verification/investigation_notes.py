"""Investigation notes template generation."""

from __future__ import annotations

from pathlib import Path

INVESTIGATION_NOTES_FILENAME = "investigation_notes.md"


def generate_investigation_notes(run_id: str, output_directory: Path) -> Path:
    """Write investigation_notes.md — blank sections for human entry."""
    output_directory.mkdir(parents=True, exist_ok=True)
    path = output_directory / INVESTIGATION_NOTES_FILENAME

    lines = [
        "# Investigation Notes",
        "",
        f"Run ID: {run_id}",
        "",
        "Reviewer:",
        "",
        "Review Date:",
        "",
        "## Observations",
        "",
        "________________________",
        "",
        "## Findings",
        "",
        "________________________",
        "",
        "## Follow Up Actions",
        "",
        "________________________",
        "",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path
