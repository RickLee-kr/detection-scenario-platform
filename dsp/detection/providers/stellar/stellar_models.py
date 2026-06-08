"""Stellar vendor dataclasses — legacy helpers and re-exports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from dsp.detection.providers.stellar.mock_client import MockStellarClient

__all__ = [
    "MockStellarClient",
    "StellarAlert",
    "StellarAnalytics",
    "StellarEntity",
    "StellarTimelineEvent",
]


@dataclass
class StellarAlert:
    alert_id: str
    name: str
    severity: str
    observed_at: datetime
    run_id: str
    scenario_id: str
    entity_refs: list[str] = field(default_factory=list)
    detection_model_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "name": self.name,
            "severity": self.severity,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "entity_refs": self.entity_refs,
            "detection_model_id": self.detection_model_id,
        }


@dataclass
class StellarAnalytics:
    incident_id: str
    analytic_type: str
    observed_at: datetime
    run_id: str
    scenario_id: str
    summary: str = ""
    detection_model_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "analytic_type": self.analytic_type,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "summary": self.summary,
            "detection_model_id": self.detection_model_id,
        }


@dataclass
class StellarEntity:
    entity_id: str
    entity_type: str
    entity_value: str
    role: str
    run_id: str
    scenario_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "entity_value": self.entity_value,
            "role": self.role,
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
        }


@dataclass
class StellarTimelineEvent:
    event_id: str
    event_type: str
    observed_at: datetime
    description: str
    run_id: str
    scenario_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "description": self.description,
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
        }
