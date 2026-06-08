"""SSH login failure validation profile templates."""

from __future__ import annotations

from typing import Any

SSH_FAILURE_METRIC_NAMES = [
    "ssh_auth_attempt_count",
    "ssh_auth_failed_count",
]


def ssh_failure_validation_profile(**overrides: Any) -> dict[str, Any]:
    """Standard SSH login failure validation profile for manifest.yaml."""
    profile: dict[str, Any] = {
        "profile_version": "1.0.0",
        "metrics": [
            {
                "name": "ssh_auth_attempt_count",
                "event_filter": {
                    "event": "ssh_auth_attempt",
                    "status": "sent",
                },
                "aggregate": "count",
            },
            {
                "name": "ssh_auth_failed_count",
                "event_filter": {
                    "event": "ssh_auth_failed",
                    "status": "auth_failed",
                },
                "aggregate": "count",
            },
        ],
        "success": {
            "ssh_auth_attempt_count": {"min": 1},
            "ssh_auth_failed_count": {"min": 1},
        },
        "fail_fast": ["SOT_EMPTY_AFTER_EXECUTE"],
    }
    profile.update(overrides)
    return profile
