"""HTTP transport request/response models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TransportRequest:
    """Normalized HTTP request envelope for webshell transport."""

    url: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)
    body: bytes | str | None = None
    timeout_seconds: float = 25.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        body_value: str | None
        if self.body is None:
            body_value = None
        elif isinstance(self.body, bytes):
            body_value = self.body.decode("utf-8", errors="replace")
        else:
            body_value = self.body
        return {
            "url": self.url,
            "method": self.method,
            "headers": dict(self.headers),
            "cookies": dict(self.cookies),
            "params": dict(self.params),
            "body": body_value,
            "timeout_seconds": self.timeout_seconds,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransportRequest:
        raw_body = data.get("body")
        body: bytes | str | None
        if raw_body is None:
            body = None
        elif isinstance(raw_body, bytes):
            body = raw_body
        else:
            body = str(raw_body)
        return cls(
            url=data["url"],
            method=str(data.get("method", "GET")),
            headers=dict(data.get("headers") or {}),
            cookies=dict(data.get("cookies") or {}),
            params=dict(data.get("params") or {}),
            body=body,
            timeout_seconds=float(data.get("timeout_seconds", 25.0)),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class TransportResponse:
    """Normalized HTTP response envelope from webshell transport."""

    status_code: int
    headers: dict[str, str]
    body: bytes
    duration_ms: float
    success: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status_code": self.status_code,
            "headers": dict(self.headers),
            "body": self.body.decode("utf-8", errors="replace"),
            "duration_ms": self.duration_ms,
            "success": self.success,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransportResponse:
        raw_body = data.get("body", "")
        if isinstance(raw_body, bytes):
            body = raw_body
        else:
            body = str(raw_body).encode("utf-8")
        return cls(
            status_code=int(data["status_code"]),
            headers=dict(data.get("headers") or {}),
            body=body,
            duration_ms=float(data.get("duration_ms", 0.0)),
            success=bool(data.get("success", False)),
            metadata=dict(data.get("metadata") or {}),
        )
