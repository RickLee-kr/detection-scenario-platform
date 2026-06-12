"""HTTP Follow-up URL planning — bash stellar_poc_followup.sh parity."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from dsp.protocols.base import HttpProtocolError

# Plain HTTP first for sensor-visible URL/UA anomaly; HTTPS as fallback only
HTTP_PORT_PRIORITY = (80, 8080, 8000, 8888, 9000, 9090)
HTTPS_PORT_PRIORITY = (443, 8443)
PORT_PRIORITY = HTTP_PORT_PRIORITY + HTTPS_PORT_PRIORITY
HTTPS_PORTS = frozenset(HTTPS_PORT_PRIORITY)

# stellar_poc_followup.sh mandatory_payload_urls
MANDATORY_PAYLOAD_PATHS = (
    "/WEB-INF/web.xml",
    "/../../etc/passwd",
    "/cmd.jsp",
    "/backdoor.jsp",
    "/admin",
    "/swagger",
    "/graphql",
)

# stellar_poc_followup.sh payload_recon_urls
PAYLOAD_RECON_PATHS = (
    "/WEB-INF/web.xml",
    "/WEB-INF/classes/",
    "/.env",
    "/backup.zip",
    "/admin/login",
    "/actuator/env",
    "/cmd.jsp",
    "/backdoor.jsp",
    "/swagger",
    "/swagger-ui.html",
    "/graphql",
    "/graphql/console",
    "/shell.jsp",
    "/../../etc/passwd",
    "/conf/server.xml",
)

# Legacy alias used in tests/docs
ATTACK_SCAN_PATHS = MANDATORY_PAYLOAD_PATHS

# stellar_poc_followup.sh pick_bad_query_attack
BAD_QUERY_ATTACKS = (
    "?file=../../../../WEB-INF/web.xml",
    "?path=..%2f..%2f..%2fetc%2fpasswd",
    "?id=%00%00%00",
    "?action=../../../../secret/config",
    "?cmd=|whoami&file=../../../../WEB-INF/classes/",
    "?%00=1&page=admin",
    "?file=%2e%2e%2f%2e%2e%2fweb.xml",
    "?id=%25%25%25invalid%25%25%25",
)

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

MAX_HOSTS_DEFAULT = 1
MAX_REQUESTS_PER_HOST_DEFAULT = 300
MAX_REQUESTS_TOTAL_DEFAULT = 300
REQUEST_DUMP_SAMPLE_SIZE = 100


@dataclass(frozen=True)
class PlannedHttpRequest:
    host: str
    port: int
    path: str
    method: str = "GET"
    headers: dict[str, str] | None = None
    query: str = ""
    body: str | None = None

    @property
    def full_path(self) -> str:
        return f"{self.path}{self.query}" if self.query else self.path

    @property
    def url(self) -> str:
        return build_url(self.host, self.port, self.full_path)

    @property
    def scheme(self) -> str:
        return "https" if self.port in HTTPS_PORTS else "http"

    @property
    def host_header(self) -> str:
        return self.host


def build_url(host: str, port: int, path: str) -> str:
    """Build HTTP/HTTPS URL for a host, port, and path (may include query)."""
    host = host.strip()
    if not host:
        raise HttpProtocolError("host is required")
    if port <= 0:
        raise HttpProtocolError("port must be positive")
    base_path = path.split("?", 1)[0]
    if not base_path.startswith("/"):
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


def pick_bad_query() -> str:
    """Bash pick_bad_query_attack — random malicious query string."""
    return random.choice(BAD_QUERY_ATTACKS)


def pick_followup_method(*, allow_post: bool = True) -> str:
    """Bash pick_method — GET-heavy with HEAD/POST mix."""
    roll = random.randrange(10)
    if roll <= 6:
        return "GET"
    if roll == 7:
        return "HEAD"
    if allow_post and roll == 9:
        return "POST"
    return "GET"


@dataclass
class _AttackUrlPlanner:
    """Stateful bash next_attack_url parity."""

    mandatory_idx: int = 0
    payload_idx: int = 0
    seen: set[str] = field(default_factory=set)

    def next_path_query(self) -> tuple[str, str]:
        if self.mandatory_idx < len(MANDATORY_PAYLOAD_PATHS):
            base = MANDATORY_PAYLOAD_PATHS[self.mandatory_idx]
            self.mandatory_idx += 1
        else:
            base = PAYLOAD_RECON_PATHS[self.payload_idx % len(PAYLOAD_RECON_PATHS)]
            self.payload_idx += 1
        query = pick_bad_query()
        full = f"{base}{query}"
        guard = 0
        while full in self.seen and guard < 32:
            query = pick_bad_query()
            full = f"{base}{query}"
            guard += 1
        self.seen.add(full)
        return base, query


def compute_requests_per_target(
    num_targets: int,
    max_total: int,
    *,
    min_per_target: int = 100,
) -> int:
    """Even per-target request budget (minimum when total volume allows)."""
    if num_targets < 1 or max_total < 1:
        raise HttpProtocolError("target count and max_total must be positive")
    per_target = max_total // num_targets
    if per_target < min_per_target and num_targets * min_per_target <= max_total:
        per_target = min_per_target
    return per_target


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
    Plan HTTP follow-up requests with bash next_attack_url + bad query parity.

    Concentrates on up to max_hosts endpoints; default profile uses one host.
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

    plans: list[PlannedHttpRequest] = []
    planner = _AttackUrlPlanner()

    for host, port in selected:
        host_sent = 0
        while host_sent < max_per_host and len(plans) < max_total:
            if include_attack_paths:
                path, query = planner.next_path_query()
            else:
                path = FIXED_PATHS[host_sent % len(FIXED_PATHS)]
                query = ""
            method = pick_followup_method()
            plans.append(
                PlannedHttpRequest(
                    host=host,
                    port=port,
                    path=path,
                    query=query,
                    method=method,
                )
            )
            host_sent += 1

    return plans
