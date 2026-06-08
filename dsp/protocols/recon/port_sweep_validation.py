"""Port sweep validation profile templates."""

from __future__ import annotations

from typing import Any

PORT_SWEEP_METRIC_NAMES = [
    "port_probe_count",
    "port_connection_attempt_count",
    "port_connection_success_count",
    "port_connection_failure_count",
]


def port_sweep_validation_profile(**overrides: Any) -> dict[str, Any]:
    """Standard port sweep validation profile for manifest.yaml."""
    profile: dict[str, Any] = {
        "profile_version": "1.0.0",
        "metrics": [
            {
                "name": "port_probe_count",
                "event_filter": {
                    "event": "port_probe_sent",
                    "status": "sent",
                },
                "aggregate": "count",
            },
            {
                "name": "port_connection_attempt_count",
                "event_filter": {
                    "event": [
                        "port_connection_opened",
                        "port_connection_failed",
                    ],
                },
                "aggregate": "count",
            },
            {
                "name": "port_connection_success_count",
                "event_filter": {
                    "event": "port_connection_opened",
                    "status": "sent",
                },
                "aggregate": "count",
            },
            {
                "name": "port_connection_failure_count",
                "event_filter": {
                    "event": "port_connection_failed",
                },
                "aggregate": "count",
            },
        ],
        "success": {
            "port_probe_count": {"min": 1},
            "port_connection_attempt_count": {"min": 1},
        },
        "fail_fast": ["SOT_EMPTY_AFTER_EXECUTE"],
    }
    profile.update(overrides)
    return profile
