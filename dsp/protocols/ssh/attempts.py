"""SSH login failure attempt planning — fixed usernames and dummy passwords."""

from __future__ import annotations

from dataclasses import dataclass

from dsp.protocols.base import SshProtocolError

SSH_PORT_DEFAULT = 22
MAX_HOSTS_DEFAULT = 2
MAX_ATTEMPTS_PER_HOST_DEFAULT = 30
MAX_ATTEMPTS_TOTAL_DEFAULT = 60

DEFAULT_USERNAMES: tuple[str, ...] = ("admin", "root", "test", "ubuntu", "user")
DEFAULT_PASSWORDS: tuple[str, ...] = ("Password123", "Welcome123", "Test123")


@dataclass(frozen=True)
class PlannedSshAttempt:
    host: str
    port: int
    username: str
    password_label: str

    @property
    def target(self) -> str:
        return f"{self.username}@{self.host}:{self.port}"


def plan_ssh_attempts(
    hosts: list[str],
    *,
    max_hosts: int = MAX_HOSTS_DEFAULT,
    max_per_host: int = MAX_ATTEMPTS_PER_HOST_DEFAULT,
    max_total: int = MAX_ATTEMPTS_TOTAL_DEFAULT,
    port: int = SSH_PORT_DEFAULT,
    usernames: tuple[str, ...] = DEFAULT_USERNAMES,
    passwords: tuple[str, ...] = DEFAULT_PASSWORDS,
) -> list[PlannedSshAttempt]:
    """
    Plan SSH authentication failure attempts across hosts.

    Caps: max 2 hosts, 30 attempts per host, 60 attempts total.
    Password labels are dummy evidence only — not used for live auth.
    """
    if max_hosts < 1 or max_per_host < 1 or max_total < 1:
        raise SshProtocolError("attempt caps must be positive")
    if port <= 0:
        raise SshProtocolError("port must be positive")
    if not usernames:
        raise SshProtocolError("at least one username is required")
    if not passwords:
        raise SshProtocolError("at least one password label is required")

    selected = [h.strip() for h in hosts if h.strip()][:max_hosts]
    if not selected:
        raise SshProtocolError("at least one host is required")

    plans: list[PlannedSshAttempt] = []
    for host in selected:
        host_count = 0
        username_index = 0
        password_index = 0
        while host_count < max_per_host and len(plans) < max_total:
            plans.append(
                PlannedSshAttempt(
                    host=host,
                    port=port,
                    username=usernames[username_index % len(usernames)],
                    password_label=passwords[password_index % len(passwords)],
                )
            )
            host_count += 1
            username_index += 1
            password_index += 1

    return plans
