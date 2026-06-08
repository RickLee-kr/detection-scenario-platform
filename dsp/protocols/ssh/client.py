"""SSH protocol client — safe auth-failure attempts via subprocess ssh."""

from __future__ import annotations

import socket
import subprocess
import uuid
from typing import Any

from dsp.protocols.base import SshProtocolError
from dsp.protocols.ssh.attempts import PlannedSshAttempt
from dsp.protocols.types import SshAttempt, SshAttemptResult

DEFAULT_TIMEOUT_SEC = 10.0

SSH_SAFE_OPTIONS: tuple[str, ...] = (
    "BatchMode=yes",
    "ConnectTimeout=2",
    "StrictHostKeyChecking=no",
    "UserKnownHostsFile=/dev/null",
    "GlobalKnownHostsFile=/dev/null",
    "LogLevel=ERROR",
    "NumberOfPasswordPrompts=0",
    "PreferredAuthentications=publickey",
    "PubkeyAuthentication=yes",
    "PasswordAuthentication=no",
    "IdentitiesOnly=yes",
    "IdentityFile=/dev/null",
)


def _build_ssh_command(attempt: SshAttempt, *, timeout: float) -> list[str]:
    connect_timeout = max(1, min(int(timeout), 10))
    options = list(SSH_SAFE_OPTIONS)
    options = [
        opt if not opt.startswith("ConnectTimeout=") else f"ConnectTimeout={connect_timeout}"
        for opt in options
    ]
    cmd = ["ssh", *(_expand_option(opt) for opt in options), f"{attempt.username}@{attempt.host}", "exit"]
    return cmd


def _expand_option(option: str) -> str:
    return f"-o{option}"


def _classify_ssh_failure(stderr: str, returncode: int) -> str:
    text = stderr.lower()
    if "connection refused" in text or "connection reset" in text:
        return "connection_refused"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if (
        "permission denied" in text
        or "authentication failed" in text
        or "no supported authentication methods" in text
        or returncode != 0
    ):
        return "auth_failed"
    return "error"


def attempt_auth_failure(
    host: str,
    *,
    port: int = 22,
    username: str = "admin",
    timeout: float = DEFAULT_TIMEOUT_SEC,
) -> SshAttemptResult:
    """Attempt a safe SSH login that is expected to fail (no password/key auth)."""
    attempt = SshAttempt(host=host, port=port, username=username)
    return _execute_attempt(attempt, timeout=timeout, dry_run=False)


def _execute_attempt(attempt: SshAttempt, *, timeout: float, dry_run: bool) -> SshAttemptResult:
    attempt_id = uuid.uuid4().hex[:8]
    evidence: dict[str, Any] = {
        "host": attempt.host,
        "port": attempt.port,
        "username": attempt.username,
    }

    if dry_run:
        return SshAttemptResult(
            target=attempt.target,
            port=attempt.port,
            username=attempt.username,
            outcome="auth_failed",
            attempt_id=attempt_id,
            dry_run=True,
            evidence={**evidence, "mock": True},
        )

    cmd = _build_ssh_command(attempt, timeout=timeout)
    if attempt.port != 22:
        cmd = ["ssh", "-p", str(attempt.port), *cmd[1:]]

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        stderr = completed.stderr or ""
        outcome = _classify_ssh_failure(stderr, completed.returncode)
        return SshAttemptResult(
            target=attempt.target,
            port=attempt.port,
            username=attempt.username,
            outcome=outcome,
            attempt_id=attempt_id,
            dry_run=False,
            evidence={
                **evidence,
                "returncode": completed.returncode,
                "stderr_excerpt": stderr[:200],
            },
        )
    except subprocess.TimeoutExpired:
        return SshAttemptResult(
            target=attempt.target,
            port=attempt.port,
            username=attempt.username,
            outcome="timeout",
            attempt_id=attempt_id,
            dry_run=False,
            evidence=evidence,
        )
    except FileNotFoundError as exc:
        raise SshProtocolError("ssh client not found on PATH") from exc
    except OSError as exc:
        if isinstance(exc, ConnectionRefusedError):
            outcome = "connection_refused"
        elif isinstance(getattr(exc, "__cause__", None), socket.timeout):
            outcome = "timeout"
        else:
            outcome = "error"
        return SshAttemptResult(
            target=attempt.target,
            port=attempt.port,
            username=attempt.username,
            outcome=outcome,
            attempt_id=attempt_id,
            dry_run=False,
            evidence={**evidence, "message": str(exc)},
        )


class SshClient:
    """SSH protocol client with mock and live modes."""

    def __init__(
        self,
        *,
        mode: str | None = None,
        dry_run: bool = True,
        mock: bool = True,
        timeout: float = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        resolved = self._resolve_mode(mode=mode, dry_run=dry_run, mock=mock)
        if resolved not in ("mock", "live"):
            raise SshProtocolError(f"Invalid SSH client mode: {resolved!r}")
        self.mode = resolved
        self.dry_run = resolved == "mock"
        self.mock = resolved == "mock"
        self.timeout = timeout

    @staticmethod
    def _resolve_mode(*, mode: str | None, dry_run: bool, mock: bool) -> str:
        if mode is not None:
            return mode
        return "mock" if (dry_run or mock) else "live"

    def attempt(
        self,
        planned: PlannedSshAttempt,
        *,
        mock_outcome: str | None = None,
    ) -> SshAttemptResult:
        """Execute a planned SSH auth-failure attempt."""
        attempt = self.make_attempt(planned)
        if self.mode == "live":
            if mock_outcome is not None:
                raise SshProtocolError("mock_outcome is not supported in live mode")
            return _execute_attempt(attempt, timeout=self.timeout, dry_run=False)
        return self._mock_attempt(attempt, mock_outcome=mock_outcome)

    def _mock_attempt(
        self,
        attempt: SshAttempt,
        *,
        mock_outcome: str | None = None,
    ) -> SshAttemptResult:
        attempt_id = uuid.uuid4().hex[:8]
        outcome = mock_outcome or "auth_failed"
        return SshAttemptResult(
            target=attempt.target,
            port=attempt.port,
            username=attempt.username,
            outcome=outcome,
            attempt_id=attempt_id,
            dry_run=True,
            evidence={
                "host": attempt.host,
                "port": attempt.port,
                "username": attempt.username,
                "mock": True,
            },
        )

    def make_attempt(self, planned: PlannedSshAttempt) -> SshAttempt:
        if not isinstance(planned, PlannedSshAttempt):
            raise SshProtocolError("planned attempt must be PlannedSshAttempt")
        return SshAttempt(
            host=planned.host,
            port=planned.port,
            username=planned.username,
            password_label=planned.password_label,
        )
