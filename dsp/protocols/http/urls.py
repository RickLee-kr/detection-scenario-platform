"""HTTP Follow-up URL planning — fixed paths, attack paths, port priority."""

from __future__ import annotations

from dataclasses import dataclass

from dsp.protocols.base import HttpProtocolError

# Plain HTTP first for sensor-visible URL/UA anomaly; HTTPS as fallback only
HTTP_PORT_PRIORITY = (80, 8080, 8000, 8888, 9000, 9090)
HTTPS_PORT_PRIORITY = (443, 8443)
PORT_PRIORITY = HTTP_PORT_PRIORITY + HTTPS_PORT_PRIORITY
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
# stellar_poc_followup.sh mandatory_payload_urls + payload_recon_urls (subset)
ATTACK_SCAN_PATHS = (
    "/WEB-INF/web.xml",
    "/.env",
    "/../../etc/passwd",
    "/cmd.jsp",
    "/backdoor.jsp",
    "/shell.jsp",
    "/actuator/env",
    "/swagger",
    "/graphql",
    "/WEB-INF/classes/",
    "/swagger-ui.html",
    "/graphql/console",
)
MAX_HOSTS_DEFAULT = 2
MAX_REQUESTS_PER_HOST_DEFAULT = 10
MAX_REQUESTS_TOTAL_DEFAULT = 20
HTTPS_PORTS = frozenset(HTTPS_PORT_PRIORITY)


@dataclass(frozen=True)
class PlannedHttpRequest:
    host: str
    port: int
    path: str
    method: str = "GET"
    headers: dict[str, str] | None = None

    @property
    def url(self) -> str:
        return build_url(self.host, self.port, self.path)

    @property
    def scheme(self) -> str:
        return "https" if self.port in HTTPS_PORTS else "http"


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


def _dedupe_paths(*groups: tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for group in groups:
        for path in group:
            if path not in seen:
                seen.add(path)
                ordered.append(path)
    return ordered


def plan_followup_requests(
    hosts: list[str] | None = None,
    *,
    endpoints: list[tuple[str, int]] | None = None,
    max_hosts: int = MAX_HOSTS_DEFAULT,
    max_per_host: int = MAX_REQUESTS_PER_HOST_DEFAULT,
    max_total: int = MAX_REQUESTS_TOTAL_DEFAULT,
    port_priority: tuple[int, ...] = PORT_PRIORITY,
    include_attack_paths: bool = True,
) -> list[PlannedHttpRequest]:
    """
    Plan HTTP follow-up / URL scan requests across hosts or explicit endpoints.

    When include_attack_paths is True, bash mandatory attack paths are prepended.
    Paths cycle when max_per_host exceeds unique path count (bash HTTP_SCAN_REPEAT parity).
    """
    if max_hosts < 1 or max_per_host < 1 or max_total < 1:
        raise HttpProtocolError("request caps must be positive")

    if endpoints:
        selected: list[tuple[str, int]] = [(h.strip(), int(p)) for h, p in endpoints if h.strip()][:max_hosts]
    elif hosts:
        selected = [
            (h.strip(), select_port_for_host(i, port_priority))
            for i, h in enumerate(h for h in hosts if h.strip())
        ][:max_hosts]
    else:
        raise HttpProtocolError("at least one host or endpoint is required")

    if not selected:
        raise HttpProtocolError("at least one host is required")

    if include_attack_paths:
        all_paths = _dedupe_paths(ATTACK_SCAN_PATHS, FIXED_PATHS)
    else:
        all_paths = list(FIXED_PATHS)
    if not all_paths:
        raise HttpProtocolError("no paths available for follow-up requests")

    plans: list[PlannedHttpRequest] = []

    for host, port in selected:
        path_idx = 0
        host_sent = 0
        while host_sent < max_per_host and len(plans) < max_total:
            path = all_paths[path_idx % len(all_paths)]
            plans.append(PlannedHttpRequest(host=host, port=port, path=path))
            host_sent += 1
            path_idx += 1

    return plans
