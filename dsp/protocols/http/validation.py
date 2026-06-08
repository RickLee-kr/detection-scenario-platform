"""HTTP Follow-up validation profile templates."""

from __future__ import annotations

from typing import Any

HTTP_FOLLOWUP_METRIC_NAMES = [
    "http_request_sent_count",
    "http_response_received_count",
]


def http_followup_validation_profile(**overrides: Any) -> dict[str, Any]:
    """Standard HTTP Follow-up validation profile for manifest.yaml."""
    profile: dict[str, Any] = {
        "profile_version": "1.0.0",
        "metrics": [
            {
                "name": "http_request_sent_count",
                "event_filter": {
                    "event": "http_request_sent",
                    "status": "sent",
                },
                "aggregate": "count",
            },
            {
                "name": "http_response_received_count",
                "event_filter": {
                    "event": "http_response_received",
                    "status": "response",
                },
                "aggregate": "count",
            },
        ],
        "success": {
            "http_request_sent_count": {"min": 1},
        },
        "fail_fast": ["SOT_EMPTY_AFTER_EXECUTE"],
    }
    profile.update(overrides)
    return profile
