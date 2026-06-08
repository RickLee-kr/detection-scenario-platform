"""DNS validation profile templates — manifest-driven, no scenario branches."""

from __future__ import annotations

from typing import Any


def dns_validation_profile(**overrides: Any) -> dict[str, Any]:
    """
    Standard DNS validation profile for manifest.yaml validation_profile block.

    Metrics are computed exclusively via EventStore.aggregate().
    """
    profile: dict[str, Any] = {
        "profile_version": "1.0.0",
        "metrics": [
            {
                "name": "dns_query_sent_count",
                "event_filter": {"event": "dns_query_sent", "status": "sent"},
                "aggregate": "count",
            },
            {
                "name": "dns_response_count",
                "event_filter": {"event": "dns_response_received", "status": "response"},
                "aggregate": "count",
            },
            {
                "name": "dns_nxdomain_count",
                "event_filter": {"event": "dns_response_received", "status": "nxdomain"},
                "aggregate": "count",
            },
            {
                "name": "dns_timeout_count",
                "event_filter": {"event": "dns_timeout", "status": "timeout"},
                "aggregate": "count",
            },
            {
                "name": "dns_error_count",
                "event_filter": {"event": "dns_error", "status": "error"},
                "aggregate": "count",
            },
        ],
        "success": {
            "dns_query_sent_count": {"min": 1},
            "dns_response_count": {"min": 1},
        },
        "fail_fast": ["SOT_EMPTY_AFTER_EXECUTE"],
    }
    profile.update(overrides)
    return profile


DNS_METRIC_NAMES = [
    "dns_query_sent_count",
    "dns_response_count",
    "dns_nxdomain_count",
    "dns_timeout_count",
    "dns_error_count",
]
