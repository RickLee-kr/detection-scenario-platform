"""Remote event collection data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RemoteEventCollectionRequest:
    """Input for collecting a remote event bundle after scenario execution."""

    remote_execution_id: str
    remote_bundle_path: str
    local_bundle_path: str | Path | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "remote_execution_id": self.remote_execution_id,
            "remote_bundle_path": self.remote_bundle_path,
        }
        if self.local_bundle_path is not None:
            payload["local_bundle_path"] = str(self.local_bundle_path)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RemoteEventCollectionRequest:
        local_raw = data.get("local_bundle_path")
        return cls(
            remote_execution_id=str(data["remote_execution_id"]),
            remote_bundle_path=str(data["remote_bundle_path"]),
            local_bundle_path=str(local_raw) if local_raw is not None else None,
        )


@dataclass
class RemoteEventCollectionResult:
    """Outcome of downloading and importing a remote event bundle."""

    remote_execution_id: str
    remote_bundle_path: str
    local_bundle_path: str
    events_imported: int
    collection_metadata: dict[str, Any] = field(default_factory=dict)
    import_duration_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "remote_execution_id": self.remote_execution_id,
            "remote_bundle_path": self.remote_bundle_path,
            "local_bundle_path": self.local_bundle_path,
            "events_imported": self.events_imported,
            "collection_metadata": dict(self.collection_metadata),
        }
        if self.import_duration_ms is not None:
            payload["import_duration_ms"] = self.import_duration_ms
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RemoteEventCollectionResult:
        import_duration_raw = data.get("import_duration_ms")
        return cls(
            remote_execution_id=str(data["remote_execution_id"]),
            remote_bundle_path=str(data["remote_bundle_path"]),
            local_bundle_path=str(data["local_bundle_path"]),
            events_imported=int(data["events_imported"]),
            collection_metadata=dict(data.get("collection_metadata") or {}),
            import_duration_ms=(
                float(import_duration_raw)
                if import_duration_raw is not None
                else None
            ),
        )
