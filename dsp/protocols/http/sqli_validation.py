"""SQL injection validation profile templates."""

from __future__ import annotations

from typing import Any

SQL_INJECTION_METRIC_NAMES = [
    "sql_payload_generated_count",
    "sql_request_sent_count",
]


def sql_injection_validation_profile(**overrides: Any) -> dict[str, Any]:
    """Standard SQL injection validation profile for manifest.yaml."""
    profile: dict[str, Any] = {
        "profile_version": "1.0.0",
        "metrics": [
            {
                "name": "sql_payload_generated_count",
                "event_filter": {
                    "event": "sql_payload_generated",
                    "status": "info",
                },
                "aggregate": "count",
            },
            {
                "name": "sql_request_sent_count",
                "event_filter": {
                    "event": "sql_request_sent",
                    "status": "sent",
                },
                "aggregate": "count",
            },
        ],
        "success": {
            "sql_payload_generated_count": {"min": 1},
            "sql_request_sent_count": {"min": 1},
        },
        "fail_fast": ["SOT_EMPTY_AFTER_EXECUTE"],
    }
    profile.update(overrides)
    return profile
