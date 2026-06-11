"""Shared protocol result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DnsQuery:
    fqdn: str
    qtype: str = "A"
    resolver: str = "10.10.10.20"
    port: int = 53


@dataclass
class DnsQueryResult:
    fqdn: str
    qtype: str
    outcome: str
    resolver: str = ""
    rcode: int | None = None
    response_summary: dict[str, Any] | None = None
    query_id: str = ""
    dry_run: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class HttpRequest:
    url: str
    method: str = "GET"
    host: str = ""
    port: int = 443
    path: str = "/"
    headers: dict[str, str] | None = None
    body: str | bytes | None = None


@dataclass
class HttpResponseResult:
    url: str
    method: str
    outcome: str
    status_code: int | None = None
    response_summary: dict[str, Any] | None = None
    request_id: str = ""
    dry_run: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class SshAttempt:
    host: str
    port: int = 22
    username: str = "admin"
    password_label: str = ""

    @property
    def target(self) -> str:
        return f"{self.username}@{self.host}:{self.port}"


@dataclass
class SshAttemptResult:
    target: str
    port: int
    username: str
    outcome: str
    attempt_id: str = ""
    dry_run: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class SmbAttempt:
    host: str
    port: int = 445
    username: str = "administrator"
    password_label: str = ""
    safe_mode: bool = True

    @property
    def target(self) -> str:
        return f"{self.username}@{self.host}:{self.port}"


@dataclass
class SmbAttemptResult:
    target: str
    port: int
    username: str
    outcome: str
    attempt_id: str = ""
    dry_run: bool = False
    connection_opened: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class PortProbe:
    host: str
    port: int
    safe_mode: bool = True

    @property
    def target(self) -> str:
        return f"{self.host}:{self.port}"


@dataclass
class PortProbeResult:
    host: str
    port: int
    outcome: str
    probe_id: str = ""
    dry_run: bool = False
    connection_opened: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class LdapAction:
    host: str
    port: int = 389
    action_type: str = "connection"
    base_dn: str = ""
    search_filter: str = ""
    safe_mode: bool = True

    @property
    def target(self) -> str:
        return f"{self.host}:{self.port}"


@dataclass
class LdapActionResult:
    host: str
    port: int
    action_type: str
    outcome: str
    action_id: str = ""
    dry_run: bool = False
    connection_opened: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class KerberosAttempt:
    host: str
    port: int = 88
    username: str = "administrator"
    realm: str = "LOCAL.REALM"
    safe_mode: bool = True

    @property
    def target(self) -> str:
        return f"{self.username}@{self.realm}@{self.host}:{self.port}"


@dataclass
class KerberosAttemptResult:
    target: str
    port: int
    username: str
    realm: str
    outcome: str
    attempt_id: str = ""
    dry_run: bool = False
    connection_opened: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)
