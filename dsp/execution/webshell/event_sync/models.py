"""Event bundle and sync result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class EventBundleMetadata:
    """Manifest describing a remote event bundle."""

    run_id: str
    scenario_id: str
    scenario_version: str
    generated_at: datetime
    event_count: int
    schema_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
            "generated_at": self.generated_at.isoformat().replace("+00:00", "Z"),
            "event_count": self.event_count,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventBundleMetadata:
        generated = data["generated_at"]
        if isinstance(generated, str):
            generated_at = datetime.fromisoformat(generated.replace("Z", "+00:00"))
        else:
            raise ValueError("generated_at must be an ISO-8601 string")
        return cls(
            run_id=data["run_id"],
            scenario_id=data["scenario_id"],
            scenario_version=data["scenario_version"],
            generated_at=generated_at,
            event_count=int(data["event_count"]),
            schema_version=data["schema_version"],
        )


@dataclass
class EventBundle:
    """Loaded remote event bundle — raw event dicts, unmodified."""

    metadata: EventBundleMetadata
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EventSyncResult:
    """Outcome of importing a bundle into Event Store."""

    imported_count: int
    skipped_count: int
    bundle_metadata: EventBundleMetadata

    def to_dict(self) -> dict[str, Any]:
        return {
            "imported_count": self.imported_count,
            "skipped_count": self.skipped_count,
            "bundle_metadata": self.bundle_metadata.to_dict(),
        }
