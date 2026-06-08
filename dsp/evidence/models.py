"""Evidence export data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EvidenceExportRequest:
    """Input for exporting Event Store data to evidence files."""

    run_id: str
    output_directory: str | Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "output_directory": str(self.output_directory),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceExportRequest:
        return cls(
            run_id=str(data["run_id"]),
            output_directory=data["output_directory"],
        )


@dataclass
class EvidenceExportResult:
    """Outcome of packaging Event Store events into evidence files."""

    run_id: str
    exported_files: list[str] = field(default_factory=list)
    export_metadata: dict[str, Any] = field(default_factory=dict)
    export_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "exported_files": list(self.exported_files),
            "export_metadata": dict(self.export_metadata),
            "export_duration_ms": self.export_duration_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceExportResult:
        return cls(
            run_id=str(data["run_id"]),
            exported_files=list(data.get("exported_files") or []),
            export_metadata=dict(data.get("export_metadata") or {}),
            export_duration_ms=float(data.get("export_duration_ms", 0.0)),
        )
