"""S3 detection confirmation report helpers."""

from __future__ import annotations

from typing import Any

from dsp.detection.models import S3Result


def build_detection_confirmation_entries(
    s3_results: list[S3Result],
    evidence_path: str,
) -> list[dict[str, Any]]:
    """Build optional report appendix entries from S3 results."""
    entries: list[dict[str, Any]] = []
    for result in s3_results:
        entries.append(
            {
                "scenario_id": result.scenario,
                "provider": result.vendor,
                "status": result.status.value,
                "evidence_count": result.evidence_count,
                "evidence_path": evidence_path,
                "reason": result.reason,
            }
        )
    return entries
