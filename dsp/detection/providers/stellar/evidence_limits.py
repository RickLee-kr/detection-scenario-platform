"""Evidence size protection — safe truncation for large Stellar responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidenceLimitConfig:
    """Maximum raw evidence items retained per category."""

    max_alerts: int = 500
    max_analytics: int = 500
    max_entities: int = 500
    max_timeline: int = 1000


@dataclass
class TruncationRecord:
    """Describes evidence truncated before normalization."""

    evidence_type: str
    original_count: int
    retained_count: int
    limit: int

    @property
    def truncated(self) -> bool:
        return self.original_count > self.retained_count


@dataclass
class TruncationSummary:
    """Aggregate truncation state for one evidence collection."""

    records: list[TruncationRecord] = field(default_factory=list)

    @property
    def any_truncated(self) -> bool:
        return any(record.truncated for record in self.records)

    def to_dict(self) -> dict[str, Any]:
        return {
            "any_truncated": self.any_truncated,
            "records": [
                {
                    "evidence_type": record.evidence_type,
                    "original_count": record.original_count,
                    "retained_count": record.retained_count,
                    "limit": record.limit,
                    "truncated": record.truncated,
                }
                for record in self.records
            ],
        }


def truncate_items(
    items: list[dict[str, Any]],
    *,
    evidence_type: str,
    limit: int,
    summary: TruncationSummary,
) -> list[dict[str, Any]]:
    """Return a safely truncated copy and record truncation metadata."""
    original_count = len(items)
    if original_count <= limit:
        summary.records.append(
            TruncationRecord(
                evidence_type=evidence_type,
                original_count=original_count,
                retained_count=original_count,
                limit=limit,
            )
        )
        return list(items)

    truncated = list(items[:limit])
    summary.records.append(
        TruncationRecord(
            evidence_type=evidence_type,
            original_count=original_count,
            retained_count=len(truncated),
            limit=limit,
        )
    )
    return truncated


def apply_evidence_limits(
    *,
    alerts: list[dict[str, Any]],
    analytics: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    config: EvidenceLimitConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], TruncationSummary]:
    """Truncate oversized evidence buckets without raising."""
    summary = TruncationSummary()
    return (
        truncate_items(alerts, evidence_type="alerts", limit=config.max_alerts, summary=summary),
        truncate_items(analytics, evidence_type="analytics", limit=config.max_analytics, summary=summary),
        truncate_items(entities, evidence_type="entities", limit=config.max_entities, summary=summary),
        truncate_items(timeline, evidence_type="timeline", limit=config.max_timeline, summary=summary),
        summary,
    )
