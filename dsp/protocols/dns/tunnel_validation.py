"""DNS Tunnel validation profile templates."""

from __future__ import annotations

from typing import Any

DNS_TUNNEL_METRIC_NAMES = [
    "dns_tunnel_chunk_created_count",
    "dns_tunnel_query_sent_count",
]


def dns_tunnel_validation_profile(**overrides: Any) -> dict[str, Any]:
    """Standard DNS Tunnel validation profile for manifest.yaml."""
    profile: dict[str, Any] = {
        "profile_version": "1.0.0",
        "metrics": [
            {
                "name": "dns_tunnel_chunk_created_count",
                "event_filter": {
                    "event": "dns_tunnel_chunk_created",
                    "status": "info",
                },
                "aggregate": "count",
            },
            {
                "name": "dns_tunnel_query_sent_count",
                "event_filter": {
                    "event": "dns_tunnel_query_sent",
                    "status": "sent",
                },
                "aggregate": "count",
            },
        ],
        "success": {
            "dns_tunnel_query_sent_count": {"min": 1},
            "dns_tunnel_chunk_created_count": {"min": 1},
        },
        "fail_fast": ["SOT_EMPTY_AFTER_EXECUTE"],
    }
    profile.update(overrides)
    return profile
