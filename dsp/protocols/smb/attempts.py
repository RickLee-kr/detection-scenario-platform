"""SMB login failure attempt planning — fixed usernames, safe mode only."""

from __future__ import annotations

from dataclasses import dataclass

from dsp.protocols.base import SmbProtocolError

SMB_PORT_DEFAULT = 445
SMB_ALT_PORT = 139
MAX_HOSTS_DEFAULT = 5
ATTEMPTS_PER_HOST_DEFAULT = 10
MAX_ATTEMPTS_PER_HOST = 50

DEFAULT_USERNAMES: tuple[str, ...] = ("administrator", "admin", "guest", "test", "user")
DEFAULT_PASSWORD_LABELS: tuple[str, ...] = ("InvalidPass1", "InvalidPass2", "InvalidPass3")


@dataclass(frozen=True)
class PlannedSmbAttempt:
    host: str
    port: int
    username: str
    password_label: str
    safe_mode: bool = True

    @property
    def target(self) -> str:
        return f"{self.username}@{self.host}:{self.port}"


def plan_smb_attempts(
    hosts: list[str],
    *,
    max_hosts: int = MAX_HOSTS_DEFAULT,
    attempts_per_host: int = ATTEMPTS_PER_HOST_DEFAULT,
    port: int = SMB_PORT_DEFAULT,
    usernames: tuple[str, ...] = DEFAULT_USERNAMES,
    password_labels: tuple[str, ...] = DEFAULT_PASSWORD_LABELS,
    safe_mode: bool = True,
) -> list[PlannedSmbAttempt]:
    """
    Plan SMB authentication failure attempts across hosts.

    Caps: max 5 hosts, 50 attempts per host (default 10).
    Password labels are dummy evidence only — never used for live auth in safe mode.
    """
    if max_hosts < 1:
        raise SmbProtocolError("max_hosts must be positive")
    if attempts_per_host < 1:
        raise SmbProtocolError("attempts_per_host must be positive")
    if attempts_per_host > MAX_ATTEMPTS_PER_HOST:
        raise SmbProtocolError(f"attempts_per_host exceeds maximum ({MAX_ATTEMPTS_PER_HOST})")
    if port not in (SMB_PORT_DEFAULT, SMB_ALT_PORT):
        raise SmbProtocolError(f"unsupported SMB port: {port}")
    if not usernames:
        raise SmbProtocolError("at least one username is required")
    if not password_labels:
        raise SmbProtocolError("at least one password label is required")

    selected = [h.strip() for h in hosts if h.strip()][:max_hosts]
    if not selected:
        raise SmbProtocolError("at least one host is required")

    plans: list[PlannedSmbAttempt] = []
    for host in selected:
        username_index = 0
        password_index = 0
        for _ in range(attempts_per_host):
            plans.append(
                PlannedSmbAttempt(
                    host=host,
                    port=port,
                    username=usernames[username_index % len(usernames)],
                    password_label=password_labels[password_index % len(password_labels)],
                    safe_mode=safe_mode,
                )
            )
            username_index += 1
            password_index += 1

    return plans
