"""Manual verification package data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ManualVerificationRequest:
    """Input for generating a human-review verification package."""

    run_id: str
    output_directory: str | Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "output_directory": str(self.output_directory),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManualVerificationRequest:
        return cls(
            run_id=str(data["run_id"]),
            output_directory=data["output_directory"],
        )


@dataclass
class ManualVerificationResult:
    """Outcome of generating manual verification templates."""

    run_id: str
    generated_files: list[str] = field(default_factory=list)
    package_metadata: dict[str, Any] = field(default_factory=dict)
    generation_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "generated_files": list(self.generated_files),
            "package_metadata": dict(self.package_metadata),
            "generation_duration_ms": self.generation_duration_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManualVerificationResult:
        return cls(
            run_id=str(data["run_id"]),
            generated_files=list(data.get("generated_files") or []),
            package_metadata=dict(data.get("package_metadata") or {}),
            generation_duration_ms=float(data.get("generation_duration_ms", 0.0)),
        )
