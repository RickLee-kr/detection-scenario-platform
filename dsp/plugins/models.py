"""Plugin Loader models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Type


class PluginStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"
    CONFLICT = "conflict"


@dataclass
class Manifest:
    raw: dict[str, Any]
    path: Path

    @property
    def id(self) -> str:
        return str(self.raw["id"])

    @property
    def version(self) -> str:
        return str(self.raw["version"])

    @property
    def enabled(self) -> bool:
        return bool(self.raw.get("enabled", True))

    @property
    def validation_profile(self) -> dict[str, Any]:
        return dict(self.raw.get("validation_profile", {}))

    @property
    def report_profile(self) -> dict[str, Any]:
        return dict(self.raw.get("report_profile", {}))

    @property
    def safety(self) -> dict[str, Any]:
        return dict(self.raw.get("safety", {}))

    @property
    def defaults(self) -> dict[str, Any]:
        return dict(self.raw.get("defaults", {}))

    @property
    def executor(self) -> dict[str, Any]:
        return dict(self.raw.get("executor", {}))


@dataclass
class PluginRecord:
    id: str
    manifest: Manifest
    status: PluginStatus
    status_reason: str | None = None
    scenario_class: Type | None = None
    discovered_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    manifest_path: Path | None = None
    load_error: str | None = None

    @property
    def is_runnable(self) -> bool:
        return self.status == PluginStatus.ACTIVE
