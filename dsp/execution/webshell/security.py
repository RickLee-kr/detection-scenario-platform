"""Webshell security policy model and validation helpers — no runtime enforcement."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dsp.execution.webshell.exceptions import WebshellSecurityViolation

DEFAULT_BLOCKED_COMMANDS = frozenset(
    {
        "rm -rf /",
        "mkfs",
        "dd if=/dev/zero",
        ":(){ :|:& };:",
    }
)

DEFAULT_ALLOWED_PATH_PREFIXES = ("/tmp/dsp_stub/",)


@dataclass
class WebshellSecurityPolicy:
    """Lab security envelope for webshell operations."""

    allow_execute: bool = True
    allow_upload: bool = True
    allow_download: bool = True
    allowed_paths: tuple[str, ...] = DEFAULT_ALLOWED_PATH_PREFIXES
    blocked_commands: frozenset[str] = field(default_factory=lambda: DEFAULT_BLOCKED_COMMANDS)
    max_file_size_mb: float = 10.0
    safe_mode: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_execute": self.allow_execute,
            "allow_upload": self.allow_upload,
            "allow_download": self.allow_download,
            "allowed_paths": list(self.allowed_paths),
            "blocked_commands": sorted(self.blocked_commands),
            "max_file_size_mb": self.max_file_size_mb,
            "safe_mode": self.safe_mode,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebshellSecurityPolicy:
        return cls(
            allow_execute=bool(data.get("allow_execute", True)),
            allow_upload=bool(data.get("allow_upload", True)),
            allow_download=bool(data.get("allow_download", True)),
            allowed_paths=tuple(data.get("allowed_paths") or DEFAULT_ALLOWED_PATH_PREFIXES),
            blocked_commands=frozenset(data.get("blocked_commands") or DEFAULT_BLOCKED_COMMANDS),
            max_file_size_mb=float(data.get("max_file_size_mb", 10.0)),
            safe_mode=bool(data.get("safe_mode", True)),
        )


def validate_execute_allowed(policy: WebshellSecurityPolicy) -> None:
    if not policy.allow_execute:
        raise WebshellSecurityViolation("execute not allowed by policy", rule="allow_execute")


def validate_upload_allowed(policy: WebshellSecurityPolicy) -> None:
    if not policy.allow_upload:
        raise WebshellSecurityViolation("upload not allowed by policy", rule="allow_upload")


def validate_download_allowed(policy: WebshellSecurityPolicy) -> None:
    if not policy.allow_download:
        raise WebshellSecurityViolation("download not allowed by policy", rule="allow_download")


def validate_remote_path_allowed(policy: WebshellSecurityPolicy, remote_path: str) -> None:
    normalized = _normalize_remote_path(remote_path)
    if not policy.allowed_paths:
        return
    if not any(normalized.startswith(prefix) for prefix in policy.allowed_paths):
        raise WebshellSecurityViolation(
            f"remote path not allowed: {remote_path}",
            rule="allowed_paths",
        )


def validate_command_allowed(policy: WebshellSecurityPolicy, command: str) -> None:
    if not policy.safe_mode:
        return
    lowered = command.lower()
    for blocked in policy.blocked_commands:
        if blocked.lower() in lowered:
            raise WebshellSecurityViolation(
                f"blocked command pattern detected: {blocked}",
                rule="blocked_commands",
            )


def validate_file_size_allowed(
    policy: WebshellSecurityPolicy,
    size_bytes: int,
) -> None:
    max_bytes = int(policy.max_file_size_mb * 1024 * 1024)
    if size_bytes > max_bytes:
        raise WebshellSecurityViolation(
            f"file size {size_bytes} exceeds limit {max_bytes}",
            rule="max_file_size_mb",
        )


def validate_local_file_allowed(
    policy: WebshellSecurityPolicy,
    local_file: Path,
) -> None:
    if not local_file.exists():
        raise WebshellSecurityViolation(
            f"local file does not exist: {local_file}",
            rule="local_file_exists",
        )
    validate_file_size_allowed(policy, local_file.stat().st_size)


def _normalize_remote_path(remote_path: str) -> str:
    path = remote_path.strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return re.sub(r"/+", "/", path)
