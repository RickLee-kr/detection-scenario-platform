"""Kerberos failure validation profile templates."""

from __future__ import annotations

from typing import Any

KERBEROS_FAILURE_METRIC_NAMES = [
    "kerberos_auth_attempt_count",
    "kerberos_auth_failed_count",
]


def kerberos_failure_validation_profile(**overrides: Any) -> dict[str, Any]:
    """Standard Kerberos failure validation profile for manifest.yaml."""
    profile: dict[str, Any] = {
        "profile_version": "1.0.0",
        "metrics": [
            {
                "name": "kerberos_auth_attempt_count",
                "event_filter": {
                    "event": "kerberos_auth_attempt",
                    "status": "sent",
                },
                "aggregate": "count",
            },
            {
                "name": "kerberos_auth_failed_count",
                "event_filter": {
                    "event": "kerberos_auth_failed",
                    "status": "auth_failed",
                },
                "aggregate": "count",
            },
        ],
        "success": {
            "kerberos_auth_attempt_count": {"min": 1},
            "kerberos_auth_failed_count": {"min": 1},
        },
        "fail_fast": ["SOT_EMPTY_AFTER_EXECUTE"],
    }
    profile.update(overrides)
    return profile
