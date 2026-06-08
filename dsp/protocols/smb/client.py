"""SMB protocol client — safe failed authentication simulation (no credential use)."""

from __future__ import annotations

import socket
import uuid
from typing import Any

from dsp.protocols.base import SmbProtocolError
from dsp.protocols.smb.attempts import PlannedSmbAttempt
from dsp.protocols.types import SmbAttempt, SmbAttemptResult

DEFAULT_TIMEOUT_SEC = 10.0


def _classify_socket_error(exc: OSError) -> str:
    if isinstance(exc, ConnectionRefusedError):
        return "connection_refused"
    if isinstance(exc, TimeoutError):
        return "timeout"
    message = str(exc).lower()
    if "timed out" in message:
        return "timeout"
    if "refused" in message:
        return "connection_refused"
    return "error"


def _execute_attempt(attempt: SmbAttempt, *, timeout: float, dry_run: bool) -> SmbAttemptResult:
    attempt_id = uuid.uuid4().hex[:8]
    evidence: dict[str, Any] = {
        "host": attempt.host,
        "port": attempt.port,
        "username": attempt.username,
        "safe_mode": attempt.safe_mode,
    }

    if dry_run:
        return SmbAttemptResult(
            target=attempt.target,
            port=attempt.port,
            username=attempt.username,
            outcome="auth_failed",
            attempt_id=attempt_id,
            dry_run=True,
            connection_opened=True,
            evidence={**evidence, "mock": True},
        )

    if not attempt.safe_mode:
        raise SmbProtocolError("safe_mode must remain enabled for SMB login failure scenario")

    try:
        with socket.create_connection((attempt.host, attempt.port), timeout=timeout):
            return SmbAttemptResult(
                target=attempt.target,
                port=attempt.port,
                username=attempt.username,
                outcome="auth_failed",
                attempt_id=attempt_id,
                dry_run=False,
                connection_opened=True,
                evidence={
                    **evidence,
                    "note": "tcp_connect_only_no_credentials",
                },
            )
    except OSError as exc:
        outcome = _classify_socket_error(exc)
        return SmbAttemptResult(
            target=attempt.target,
            port=attempt.port,
            username=attempt.username,
            outcome=outcome,
            attempt_id=attempt_id,
            dry_run=False,
            connection_opened=False,
            evidence={**evidence, "message": str(exc)},
        )


class SmbClient:
    """SMB protocol client with mock and live modes."""

    def __init__(
        self,
        *,
        mode: str | None = None,
        dry_run: bool = True,
        mock: bool = True,
        timeout: float = DEFAULT_TIMEOUT_SEC,
        safe_mode: bool = True,
    ) -> None:
        resolved = self._resolve_mode(mode=mode, dry_run=dry_run, mock=mock)
        if resolved not in ("mock", "live"):
            raise SmbProtocolError(f"Invalid SMB client mode: {resolved!r}")
        self.mode = resolved
        self.dry_run = resolved == "mock"
        self.mock = resolved == "mock"
        self.timeout = timeout
        self.safe_mode = safe_mode

    @staticmethod
    def _resolve_mode(*, mode: str | None, dry_run: bool, mock: bool) -> str:
        if mode is not None:
            return mode
        return "mock" if (dry_run or mock) else "live"

    def attempt(
        self,
        planned: PlannedSmbAttempt,
        *,
        mock_outcome: str | None = None,
    ) -> SmbAttemptResult:
        attempt = self.make_attempt(planned)
        if self.mode == "live":
            if mock_outcome is not None:
                raise SmbProtocolError("mock_outcome is not supported in live mode")
            return _execute_attempt(attempt, timeout=self.timeout, dry_run=False)
        return self._mock_attempt(attempt, mock_outcome=mock_outcome)

    def _mock_attempt(
        self,
        attempt: SmbAttempt,
        *,
        mock_outcome: str | None = None,
    ) -> SmbAttemptResult:
        attempt_id = uuid.uuid4().hex[:8]
        outcome = mock_outcome or "auth_failed"
        connection_opened = outcome == "auth_failed"
        return SmbAttemptResult(
            target=attempt.target,
            port=attempt.port,
            username=attempt.username,
            outcome=outcome,
            attempt_id=attempt_id,
            dry_run=True,
            connection_opened=connection_opened,
            evidence={
                "host": attempt.host,
                "port": attempt.port,
                "username": attempt.username,
                "mock": True,
                "safe_mode": attempt.safe_mode,
            },
        )

    def make_attempt(self, planned: PlannedSmbAttempt) -> SmbAttempt:
        if not isinstance(planned, PlannedSmbAttempt):
            raise SmbProtocolError("planned attempt must be PlannedSmbAttempt")
        return SmbAttempt(
            host=planned.host,
            port=planned.port,
            username=planned.username,
            password_label=planned.password_label,
            safe_mode=planned.safe_mode,
        )
