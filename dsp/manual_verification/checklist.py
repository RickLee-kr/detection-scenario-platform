"""Verification checklist template generation."""

from __future__ import annotations

from pathlib import Path

CHECKLIST_FILENAME = "verification_checklist.md"


def generate_verification_checklist(run_id: str, output_directory: Path) -> Path:
    """Write verification_checklist.md — template only, no filled results."""
    output_directory.mkdir(parents=True, exist_ok=True)
    path = output_directory / CHECKLIST_FILENAME

    lines = [
        "# Verification Checklist",
        "",
        f"Run ID: {run_id}",
        "",
        "## Evidence Review",
        "",
        "[ ] Evidence files reviewed",
        "",
        "[ ] Event count reviewed",
        "",
        "[ ] Timeline reviewed",
        "",
        "## External Platform Review",
        "",
        "[ ] Detection platform checked",
        "",
        "[ ] Alerts reviewed manually",
        "",
        "[ ] Cases reviewed manually",
        "",
        "## Notes",
        "",
        "________________________",
        "",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path
