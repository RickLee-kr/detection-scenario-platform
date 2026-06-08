"""Kerberos auth failure attempt planning — fixed principals, safe mode only."""

from __future__ import annotations

from dataclasses import dataclass

from dsp.protocols.base import KerberosProtocolError

KERBEROS_PORT_DEFAULT = 88
MAX_HOSTS_DEFAULT = 5
ATTEMPTS_PER_HOST_DEFAULT = 10
MAX_ATTEMPTS_PER_HOST = 50
DEFAULT_REALM = "LOCAL.REALM"

DEFAULT_USERNAMES: tuple[str, ...] = ("administrator", "admin", "guest", "test", "user")


@dataclass(frozen=True)
class PlannedKerberosAttempt:
    host: str
    port: int
    username: str
    realm: str
    safe_mode: bool = True

    @property
    def target(self) -> str:
        return f"{self.username}@{self.realm}@{self.host}:{self.port}"


def plan_kerberos_attempts(
    hosts: list[str],
    *,
    max_hosts: int = MAX_HOSTS_DEFAULT,
    attempts_per_host: int = ATTEMPTS_PER_HOST_DEFAULT,
    port: int = KERBEROS_PORT_DEFAULT,
    usernames: tuple[str, ...] = DEFAULT_USERNAMES,
    realm: str = DEFAULT_REALM,
    safe_mode: bool = True,
) -> list[PlannedKerberosAttempt]:
    """
    Plan Kerberos authentication failure attempts across hosts.

    Caps: max 5 hosts, 50 attempts per host (default 10).
    No valid credentials — intentional failures only.
    """
    if max_hosts < 1:
        raise KerberosProtocolError("max_hosts must be positive")
    if attempts_per_host < 1:
        raise KerberosProtocolError("attempts_per_host must be positive")
    if attempts_per_host > MAX_ATTEMPTS_PER_HOST:
        raise KerberosProtocolError(
            f"attempts_per_host exceeds maximum ({MAX_ATTEMPTS_PER_HOST})"
        )
    if port != KERBEROS_PORT_DEFAULT:
        raise KerberosProtocolError(f"unsupported Kerberos port: {port}")
    if not usernames:
        raise KerberosProtocolError("at least one username is required")
    if not realm.strip():
        raise KerberosProtocolError("realm is required")

    selected = [h.strip() for h in hosts if h.strip()][:max_hosts]
    if not selected:
        raise KerberosProtocolError("at least one host is required")

    plans: list[PlannedKerberosAttempt] = []
    for host in selected:
        username_index = 0
        for _ in range(attempts_per_host):
            plans.append(
                PlannedKerberosAttempt(
                    host=host,
                    port=port,
                    username=usernames[username_index % len(usernames)],
                    realm=realm,
                    safe_mode=safe_mode,
                )
            )
            username_index += 1

    return plans
