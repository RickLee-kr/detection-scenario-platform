"""SMB login failure validation profile templates."""

from __future__ import annotations

from typing import Any

SMB_LOGIN_FAILURE_METRIC_NAMES = [
    "smb_auth_attempt_count",
    "smb_auth_failed_count",
]


def smb_login_failure_validation_profile(**overrides: Any) -> dict[str, Any]:
    """Standard SMB login failure validation profile for manifest.yaml."""
    profile: dict[str, Any] = {
        "profile_version": "1.0.0",
        "metrics": [
            {
                "name": "smb_auth_attempt_count",
                "event_filter": {
                    "event": "smb_auth_attempt",
                    "status": "sent",
                },
                "aggregate": "count",
            },
            {
                "name": "smb_auth_failed_count",
                "event_filter": {
                    "event": "smb_auth_failed",
                    "status": "auth_failed",
                },
                "aggregate": "count",
            },
        ],
        "success": {
            "smb_auth_attempt_count": {"min": 1},
            "smb_auth_failed_count": {"min": 1},
        },
        "fail_fast": ["SOT_EMPTY_AFTER_EXECUTE"],
    }
    profile.update(overrides)
    return profile
