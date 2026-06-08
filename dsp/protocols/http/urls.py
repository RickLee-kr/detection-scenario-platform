"""HTTP Follow-up URL planning — fixed paths and port priority."""

from __future__ import annotations

from dataclasses import dataclass

from dsp.protocols.base import HttpProtocolError

PORT_PRIORITY = (443, 8443, 80, 8080, 8000)
FIXED_PATHS = (
    "/",
    "/login",
    "/admin",
    "/api",
    "/status",
    "/health",
    "/robots.txt",
    "/favicon.ico",
    "/index.html",
    "/dashboard",
)
MAX_HOSTS_DEFAULT = 2
MAX_REQUESTS_PER_HOST_DEFAULT = 10
MAX_REQUESTS_TOTAL_DEFAULT = 20
HTTPS_PORTS = frozenset({443, 8443})


@dataclass(frozen=True)
class PlannedHttpRequest:
    host: str
    port: int
    path: str
    method: str = "GET"

    @property
    def url(self) -> str:
        return build_url(self.host, self.port, self.path)


def build_url(host: str, port: int, path: str) -> str:
    """Build HTTP/HTTPS URL for a host, port, and fixed path."""
    host = host.strip()
    if not host:
        raise HttpProtocolError("host is required")
    if port <= 0:
        raise HttpProtocolError("port must be positive")
    if not path.startswith("/"):
        raise HttpProtocolError(f"path must start with '/': {path!r}")

    scheme = "https" if port in HTTPS_PORTS else "http"
    if (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
        return f"{scheme}://{host}{path}"
    return f"{scheme}://{host}:{port}{path}"


def select_port_for_host(host_index: int, port_priority: tuple[int, ...] = PORT_PRIORITY) -> int:
    """Pick port from priority list based on host index."""
    if not port_priority:
        raise HttpProtocolError("port_priority is empty")
    return port_priority[host_index % len(port_priority)]


def plan_followup_requests(
    hosts: list[str],
    *,
    max_hosts: int = MAX_HOSTS_DEFAULT,
    max_per_host: int = MAX_REQUESTS_PER_HOST_DEFAULT,
    max_total: int = MAX_REQUESTS_TOTAL_DEFAULT,
    port_priority: tuple[int, ...] = PORT_PRIORITY,
) -> list[PlannedHttpRequest]:
    """
    Plan HTTP follow-up requests across hosts and fixed paths.

    Caps: max 2 hosts, 10 requests per host, 20 requests total.
    """
    if max_hosts < 1 or max_per_host < 1 or max_total < 1:
        raise HttpProtocolError("request caps must be positive")

    selected = [h.strip() for h in hosts if h.strip()][:max_hosts]
    if not selected:
        raise HttpProtocolError("at least one host is required")

    paths = list(FIXED_PATHS)[:max_per_host]
    plans: list[PlannedHttpRequest] = []

    for host_index, host in enumerate(selected):
        port = select_port_for_host(host_index, port_priority)
        for path in paths:
            if len(plans) >= max_total:
                return plans
            plans.append(PlannedHttpRequest(host=host, port=port, path=path))

    return plans
