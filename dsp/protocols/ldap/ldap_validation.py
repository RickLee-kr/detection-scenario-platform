"""LDAP enumeration validation profile templates."""

from __future__ import annotations

from typing import Any

LDAP_ENUM_METRIC_NAMES = [
    "ldap_connection_attempt_count",
    "ldap_bind_attempt_count",
    "ldap_search_attempt_count",
    "ldap_bind_or_search_attempt_count",
    "ldap_bind_failed_count",
    "ldap_search_failed_count",
]


def ldap_enumeration_validation_profile(**overrides: Any) -> dict[str, Any]:
    """Standard LDAP enumeration validation profile for manifest.yaml."""
    profile: dict[str, Any] = {
        "profile_version": "1.0.0",
        "metrics": [
            {
                "name": "ldap_connection_attempt_count",
                "event_filter": {
                    "event": "ldap_connection_attempt",
                    "status": "sent",
                },
                "aggregate": "count",
            },
            {
                "name": "ldap_bind_attempt_count",
                "event_filter": {
                    "event": "ldap_bind_attempt",
                    "status": "sent",
                },
                "aggregate": "count",
            },
            {
                "name": "ldap_search_attempt_count",
                "event_filter": {
                    "event": "ldap_search_attempt",
                    "status": "sent",
                },
                "aggregate": "count",
            },
            {
                "name": "ldap_bind_or_search_attempt_count",
                "event_filter": {
                    "event": [
                        "ldap_bind_attempt",
                        "ldap_search_attempt",
                    ],
                    "status": "sent",
                },
                "aggregate": "count",
            },
            {
                "name": "ldap_bind_failed_count",
                "event_filter": {
                    "event": "ldap_bind_failed",
                },
                "aggregate": "count",
            },
            {
                "name": "ldap_search_failed_count",
                "event_filter": {
                    "event": "ldap_search_failed",
                },
                "aggregate": "count",
            },
        ],
        "success": {
            "ldap_connection_attempt_count": {"min": 1},
            "ldap_bind_or_search_attempt_count": {"min": 1},
        },
        "fail_fast": ["SOT_EMPTY_AFTER_EXECUTE"],
    }
    profile.update(overrides)
    return profile
