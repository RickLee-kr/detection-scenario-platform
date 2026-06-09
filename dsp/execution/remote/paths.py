"""Remote execution path helpers."""

from __future__ import annotations


def resolve_remote_bundle_path(remote_work_dir: str, run_id: str) -> str:
    """Derive the remote events.jsonl path from work directory and run ID."""
    base = remote_work_dir.rstrip("/")
    return f"{base}/{run_id}/events.jsonl"
