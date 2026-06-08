"""Vendor-neutral S3 status and evidence models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class S3Status(str, Enum):
    """Detection confirmation status — independent of S2 ValidationResult."""

    S3_CONFIRMED = "S3_CONFIRMED"
    S3_NOT_OBSERVED = "S3_NOT_OBSERVED"
    S3_INCONCLUSIVE = "S3_INCONCLUSIVE"


@dataclass
class CorrelationContext:
    """Inputs for vendor correlation — built from Event Store (read-only consumer)."""

    run_id: str
    scenario_id: str
    time_window_start: datetime
    time_window_end: datetime
    source_ip: str | None = None
    destination_ip: str | None = None
    scenario_type: str | None = None
    dry_run: bool = False
    s2_decision: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "time_window_start": self.time_window_start.isoformat().replace("+00:00", "Z"),
            "time_window_end": self.time_window_end.isoformat().replace("+00:00", "Z"),
            "source_ip": self.source_ip,
            "destination_ip": self.destination_ip,
            "scenario_type": self.scenario_type,
            "dry_run": self.dry_run,
            "s2_decision": self.s2_decision,
            "metadata": self.metadata,
        }


@dataclass
class EvidenceBase:
    """Common fields for all vendor-neutral evidence objects."""

    evidence_id: str
    vendor: str
    collected_at: datetime
    run_id: str
    scenario_id: str
    correlation_score: float = 0.0
    raw_ref: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def base_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "vendor": self.vendor,
            "collected_at": self.collected_at.isoformat().replace("+00:00", "Z"),
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "correlation_score": self.correlation_score,
            "raw_ref": self.raw_ref,
            "attributes": self.attributes,
        }


@dataclass
class AlertEvidence(EvidenceBase):
    alert_name: str = ""
    severity: str = ""
    observed_at: datetime | None = None
    entity_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = self.base_dict()
        data.update(
            {
                "type": "alert",
                "alert_name": self.alert_name,
                "severity": self.severity,
                "observed_at": (
                    self.observed_at.isoformat().replace("+00:00", "Z")
                    if self.observed_at
                    else None
                ),
                "entity_refs": self.entity_refs,
            }
        )
        return data


@dataclass
class AnalyticsEvidence(EvidenceBase):
    analytic_type: str = ""
    incident_id: str = ""
    observed_at: datetime | None = None
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = self.base_dict()
        data.update(
            {
                "type": "analytics",
                "analytic_type": self.analytic_type,
                "incident_id": self.incident_id,
                "observed_at": (
                    self.observed_at.isoformat().replace("+00:00", "Z")
                    if self.observed_at
                    else None
                ),
                "summary": self.summary,
            }
        )
        return data


@dataclass
class EntityEvidence(EvidenceBase):
    entity_type: str = ""
    entity_value: str = ""
    role: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = self.base_dict()
        data.update(
            {
                "type": "entity",
                "entity_type": self.entity_type,
                "entity_value": self.entity_value,
                "role": self.role,
            }
        )
        return data


@dataclass
class TimelineEvidence(EvidenceBase):
    event_type: str = ""
    observed_at: datetime | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = self.base_dict()
        data.update(
            {
                "type": "timeline",
                "event_type": self.event_type,
                "observed_at": (
                    self.observed_at.isoformat().replace("+00:00", "Z")
                    if self.observed_at
                    else None
                ),
                "description": self.description,
            }
        )
        return data


@dataclass
class ArtifactEvidence(EvidenceBase):
    artifact_type: str = ""
    artifact_value: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = self.base_dict()
        data.update(
            {
                "type": "artifact",
                "artifact_type": self.artifact_type,
                "artifact_value": self.artifact_value,
            }
        )
        return data


EvidenceItem = AlertEvidence | AnalyticsEvidence | EntityEvidence | TimelineEvidence | ArtifactEvidence


@dataclass
class EvidencePack:
    """Collected vendor-neutral evidence for one scenario confirmation attempt."""

    run_id: str
    scenario_id: str
    vendor: str
    alerts: list[AlertEvidence] = field(default_factory=list)
    analytics: list[AnalyticsEvidence] = field(default_factory=list)
    entities: list[EntityEvidence] = field(default_factory=list)
    timeline: list[TimelineEvidence] = field(default_factory=list)
    artifacts: list[ArtifactEvidence] = field(default_factory=list)

    @property
    def evidence_count(self) -> int:
        return (
            len(self.alerts)
            + len(self.analytics)
            + len(self.entities)
            + len(self.timeline)
            + len(self.artifacts)
        )

    def all_items(self) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        items.extend(self.alerts)
        items.extend(self.analytics)
        items.extend(self.entities)
        items.extend(self.timeline)
        items.extend(self.artifacts)
        return items

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "vendor": self.vendor,
            "evidence_count": self.evidence_count,
            "alerts": [a.to_dict() for a in self.alerts],
            "analytics": [a.to_dict() for a in self.analytics],
            "entities": [e.to_dict() for e in self.entities],
            "timeline": [t.to_dict() for t in self.timeline],
            "artifacts": [a.to_dict() for a in self.artifacts],
        }


@dataclass
class S3Result:
    """S3 confirmation outcome — never alters S2 ValidationResult."""

    run_id: str
    scenario: str
    status: S3Status
    vendor: str
    evidence_count: int
    timestamp: datetime
    correlation_context: CorrelationContext | None = None
    reason: str = ""
    evidence_pack: EvidencePack | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario": self.scenario,
            "status": self.status.value,
            "vendor": self.vendor,
            "evidence_count": self.evidence_count,
            "timestamp": self.timestamp.isoformat().replace("+00:00", "Z"),
            "reason": self.reason,
            "correlation_context": (
                self.correlation_context.to_dict() if self.correlation_context else None
            ),
        }
