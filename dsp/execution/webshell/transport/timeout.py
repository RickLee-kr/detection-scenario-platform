"""Timeout policy profiles for webshell HTTP transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TIMEOUT_PROFILE_FAST = "fast"
TIMEOUT_PROFILE_NORMAL = "normal"
TIMEOUT_PROFILE_LARGE_TRANSFER = "large_transfer"
TIMEOUT_PROFILE_BULK_UPLOAD = "bulk_upload"

VALID_TIMEOUT_PROFILES = frozenset(
    {
        TIMEOUT_PROFILE_FAST,
        TIMEOUT_PROFILE_NORMAL,
        TIMEOUT_PROFILE_LARGE_TRANSFER,
        TIMEOUT_PROFILE_BULK_UPLOAD,
    }
)


@dataclass(frozen=True)
class TimeoutProfile:
    """Documented timeout envelope for a transport operation class."""

    name: str
    connect_seconds: float
    read_seconds: float
    total_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "connect_seconds": self.connect_seconds,
            "read_seconds": self.read_seconds,
            "total_seconds": self.total_seconds,
        }


TIMEOUT_PROFILES: dict[str, TimeoutProfile] = {
    TIMEOUT_PROFILE_FAST: TimeoutProfile(
        name=TIMEOUT_PROFILE_FAST,
        connect_seconds=5.0,
        read_seconds=10.0,
        total_seconds=15.0,
    ),
    TIMEOUT_PROFILE_NORMAL: TimeoutProfile(
        name=TIMEOUT_PROFILE_NORMAL,
        connect_seconds=10.0,
        read_seconds=25.0,
        total_seconds=30.0,
    ),
    TIMEOUT_PROFILE_LARGE_TRANSFER: TimeoutProfile(
        name=TIMEOUT_PROFILE_LARGE_TRANSFER,
        connect_seconds=15.0,
        read_seconds=120.0,
        total_seconds=180.0,
    ),
    TIMEOUT_PROFILE_BULK_UPLOAD: TimeoutProfile(
        name=TIMEOUT_PROFILE_BULK_UPLOAD,
        connect_seconds=20.0,
        read_seconds=300.0,
        total_seconds=600.0,
    ),
}


def get_timeout_profile(name: str) -> TimeoutProfile:
    """Return a named timeout profile or raise ValueError."""
    validate_timeout_profile_name(name)
    return TIMEOUT_PROFILES[name]


def validate_timeout_profile_name(name: str) -> None:
    """Raise ValueError when profile name is unknown."""
    if name not in VALID_TIMEOUT_PROFILES:
        raise ValueError(
            f"unknown timeout profile: {name!r}; "
            f"expected one of {sorted(VALID_TIMEOUT_PROFILES)}"
        )


def validate_timeout_seconds(value: float, *, profile: str | None = None) -> None:
    """Raise ValueError when timeout is non-positive or exceeds profile total."""
    if value <= 0:
        raise ValueError(f"timeout_seconds must be positive, got {value}")
    if profile is not None:
        timeout_profile = get_timeout_profile(profile)
        if value > timeout_profile.total_seconds:
            raise ValueError(
                f"timeout_seconds {value} exceeds profile "
                f"{profile!r} total {timeout_profile.total_seconds}"
            )
