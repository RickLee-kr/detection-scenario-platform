"""LDAP enumeration attempt planning — safe anonymous/failed bind and search only."""

from __future__ import annotations

from dataclasses import dataclass

from dsp.protocols.base import LdapProtocolError

LDAP_PORT_DEFAULT = 389
LDAP_TLS_PORT = 636
MAX_HOSTS_DEFAULT = 5
MAX_QUERIES_PER_HOST_DEFAULT = 10
MAX_QUERIES_PER_HOST_LIMIT = 50

DEFAULT_SAFE_FILTERS: tuple[str, ...] = (
    "(objectClass=*)",
    "(objectClass=user)",
    "(objectClass=computer)",
    "(objectClass=group)",
)

DEFAULT_PORTS: tuple[int, ...] = (LDAP_PORT_DEFAULT, LDAP_TLS_PORT)


@dataclass(frozen=True)
class PlannedLdapAction:
    host: str
    port: int
    action_type: str
    base_dn: str = ""
    search_filter: str = ""
    safe_mode: bool = True

    @property
    def artifact(self) -> str:
        if self.action_type == "search":
            return f"{self.host}:{self.port}:{self.search_filter}"
        return f"{self.host}:{self.port}:{self.action_type}"


def plan_ldap_enumeration(
    hosts: list[str],
    *,
    max_hosts: int = MAX_HOSTS_DEFAULT,
    max_queries_per_host: int = MAX_QUERIES_PER_HOST_DEFAULT,
    ports: tuple[int, ...] | list[int] | None = None,
    filters: tuple[str, ...] | list[str] | None = None,
    safe_mode: bool = True,
) -> list[PlannedLdapAction]:
    """
    Plan safe LDAP enumeration actions per host.

    Sequence per host/port: connection → bind → base DN discovery → safe searches.
    Caps: max 5 hosts, 50 queries per host (default 10).
    """
    if max_hosts < 1:
        raise LdapProtocolError("max_hosts must be positive")
    if max_queries_per_host < 1:
        raise LdapProtocolError("max_queries_per_host must be positive")
    if max_queries_per_host > MAX_QUERIES_PER_HOST_LIMIT:
        raise LdapProtocolError(
            f"max_queries_per_host exceeds maximum ({MAX_QUERIES_PER_HOST_LIMIT})"
        )

    selected = [h.strip() for h in hosts if h.strip()][:max_hosts]
    if not selected:
        raise LdapProtocolError("at least one host is required")

    port_list = tuple(ports if ports is not None else (LDAP_PORT_DEFAULT,))
    filter_list = tuple(filters if filters is not None else DEFAULT_SAFE_FILTERS)

    for port in port_list:
        if port not in (LDAP_PORT_DEFAULT, LDAP_TLS_PORT):
            raise LdapProtocolError(f"unsupported LDAP port: {port}")
        if safe_mode and port not in DEFAULT_PORTS:
            raise LdapProtocolError(f"port {port} not allowed in safe mode")

    for filt in filter_list:
        if filt not in DEFAULT_SAFE_FILTERS and safe_mode:
            raise LdapProtocolError(f"filter not allowed in safe mode: {filt}")

    plans: list[PlannedLdapAction] = []
    for host in selected:
        for port in port_list:
            plans.append(
                PlannedLdapAction(
                    host=host,
                    port=port,
                    action_type="connection",
                    safe_mode=safe_mode,
                )
            )
            plans.append(
                PlannedLdapAction(
                    host=host,
                    port=port,
                    action_type="bind",
                    safe_mode=safe_mode,
                )
            )
            plans.append(
                PlannedLdapAction(
                    host=host,
                    port=port,
                    action_type="search",
                    base_dn="",
                    search_filter="(objectClass=*)",
                    safe_mode=safe_mode,
                )
            )
            for idx in range(max_queries_per_host):
                plans.append(
                    PlannedLdapAction(
                        host=host,
                        port=port,
                        action_type="search",
                        base_dn="",
                        search_filter=filter_list[idx % len(filter_list)],
                        safe_mode=safe_mode,
                    )
                )

    return plans
