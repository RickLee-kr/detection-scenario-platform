"""Webshell contract data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from dsp.execution.webshell.capabilities import WebshellCapabilities


@dataclass
class WebshellSession:
    """Active webshell transport session metadata."""

    session_id: str
    provider_type: str
    webshell_url: str
    created_at: datetime
    last_activity: datetime
    capabilities: WebshellCapabilities
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "provider_type": self.provider_type,
            "webshell_url": self.webshell_url,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "last_activity": self.last_activity.isoformat().replace("+00:00", "Z"),
            "capabilities": self.capabilities.to_dict(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebshellSession:
        return cls(
            session_id=data["session_id"],
            provider_type=data["provider_type"],
            webshell_url=data["webshell_url"],
            created_at=datetime.fromisoformat(
                data["created_at"].replace("Z", "+00:00")
            ),
            last_activity=datetime.fromisoformat(
                data["last_activity"].replace("Z", "+00:00")
            ),
            capabilities=WebshellCapabilities.from_dict(data["capabilities"]),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class WebshellCommand:
    """Remote command dispatch request."""

    command: str
    timeout_seconds: float = 25.0
    working_directory: str | None = None
    environment: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "timeout_seconds": self.timeout_seconds,
            "working_directory": self.working_directory,
            "environment": self.environment,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebshellCommand:
        return cls(
            command=data["command"],
            timeout_seconds=float(data.get("timeout_seconds", 25.0)),
            working_directory=data.get("working_directory"),
            environment=dict(data.get("environment") or {}),
        )


@dataclass
class WebshellCommandResult:
    """Outcome of a remote command invocation."""

    success: bool
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebshellCommandResult:
        return cls(
            success=bool(data["success"]),
            exit_code=data.get("exit_code"),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            duration_ms=float(data.get("duration_ms", 0.0)),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class WebshellHealthResult:
    """Outcome of a webshell healthcheck probe."""

    reachable: bool
    latency_ms: float
    family_detected: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reachable": self.reachable,
            "latency_ms": self.latency_ms,
            "family_detected": self.family_detected,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebshellHealthResult:
        return cls(
            reachable=bool(data["reachable"]),
            latency_ms=float(data.get("latency_ms", 0.0)),
            family_detected=data.get("family_detected"),
            error=data.get("error"),
        )


@dataclass
class WebshellTransferResult:
    """Outcome of a remote file upload or download."""

    success: bool
    remote_path: str
    bytes_transferred: int
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "remote_path": self.remote_path,
            "bytes_transferred": self.bytes_transferred,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebshellTransferResult:
        return cls(
            success=bool(data["success"]),
            remote_path=data["remote_path"],
            bytes_transferred=int(data.get("bytes_transferred", 0)),
            error=data.get("error"),
            metadata=dict(data.get("metadata") or {}),
        )
