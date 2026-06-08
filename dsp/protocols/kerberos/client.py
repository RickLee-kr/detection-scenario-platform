"""Kerberos protocol client — safe failed authentication simulation (no credential use)."""

from __future__ import annotations

import socket
import uuid
from typing import Any

from dsp.protocols.base import KerberosProtocolError
from dsp.protocols.kerberos.attempts import PlannedKerberosAttempt
from dsp.protocols.types import KerberosAttempt, KerberosAttemptResult

DEFAULT_TIMEOUT_SEC = 10.0


def _der_length(length: int) -> bytes:
    if length < 128:
        return bytes([length])
    encoded = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(encoded)]) + encoded


def _der_tag(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + _der_length(len(content)) + content


def _der_general_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return _der_tag(0x1B, encoded)


def _der_integer(value: int) -> bytes:
    if value == 0:
        payload = b"\x00"
    else:
        payload = value.to_bytes((value.bit_length() + 7) // 8, "big")
        if payload[0] & 0x80:
            payload = b"\x00" + payload
    return _der_tag(0x02, payload)


def _build_as_req_probe(username: str, realm: str) -> bytes:
    """Build minimal krb5 AS-REQ bytes — invalid preauth, no valid credentials."""
    name_string = _der_general_string(username)
    name_type = _der_integer(1)
    principal_name = _der_tag(0x30, name_type + name_string)
    realm_string = _der_general_string(realm.upper())
    req_body = _der_tag(
        0x30,
        _der_integer(5)  # pvno
        + _der_integer(10)  # msg-type AS-REQ
        + _der_tag(0xA3, principal_name)
        + _der_tag(0xA5, realm_string),
    )
    return _der_tag(0x6A, req_body)


def _classify_socket_error(exc: OSError) -> str:
    if isinstance(exc, ConnectionRefusedError):
        return "connection_refused"
    if isinstance(exc, TimeoutError):
        return "timeout"
    message = str(exc).lower()
    if "timed out" in message or "timeout" in message:
        return "timeout"
    if "refused" in message or "unreachable" in message:
        return "connection_refused"
    return "error"


def _execute_attempt(
    attempt: KerberosAttempt,
    *,
    timeout: float,
    dry_run: bool,
) -> KerberosAttemptResult:
    attempt_id = uuid.uuid4().hex[:8]
    evidence: dict[str, Any] = {
        "host": attempt.host,
        "port": attempt.port,
        "username": attempt.username,
        "realm": attempt.realm,
        "safe_mode": attempt.safe_mode,
    }

    if dry_run:
        return KerberosAttemptResult(
            target=attempt.target,
            port=attempt.port,
            username=attempt.username,
            realm=attempt.realm,
            outcome="auth_failed",
            attempt_id=attempt_id,
            dry_run=True,
            connection_opened=True,
            evidence={**evidence, "mock": True},
        )

    if not attempt.safe_mode:
        raise KerberosProtocolError(
            "safe_mode must remain enabled for Kerberos failure scenario"
        )

    probe = _build_as_req_probe(attempt.username, attempt.realm)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(probe, (attempt.host, attempt.port))
        try:
            response, _ = sock.recvfrom(4096)
            return KerberosAttemptResult(
                target=attempt.target,
                port=attempt.port,
                username=attempt.username,
                realm=attempt.realm,
                outcome="auth_failed",
                attempt_id=attempt_id,
                dry_run=False,
                connection_opened=True,
                evidence={
                    **evidence,
                    "note": "as_req_invalid_preauth",
                    "kdc_response_bytes": len(response),
                },
            )
        except TimeoutError:
            return KerberosAttemptResult(
                target=attempt.target,
                port=attempt.port,
                username=attempt.username,
                realm=attempt.realm,
                outcome="auth_failed",
                attempt_id=attempt_id,
                dry_run=False,
                connection_opened=True,
                evidence={
                    **evidence,
                    "note": "as_req_sent_no_kdc_response",
                },
            )
    except OSError as exc:
        outcome = _classify_socket_error(exc)
        return KerberosAttemptResult(
            target=attempt.target,
            port=attempt.port,
            username=attempt.username,
            realm=attempt.realm,
            outcome=outcome,
            attempt_id=attempt_id,
            dry_run=False,
            connection_opened=False,
            evidence={**evidence, "message": str(exc)},
        )
    finally:
        sock.close()


class KerberosClient:
    """Kerberos protocol client with mock and live modes."""

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
            raise KerberosProtocolError(f"Invalid Kerberos client mode: {resolved!r}")
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
        planned: PlannedKerberosAttempt,
        *,
        mock_outcome: str | None = None,
    ) -> KerberosAttemptResult:
        attempt = self.make_attempt(planned)
        if self.mode == "live":
            if mock_outcome is not None:
                raise KerberosProtocolError("mock_outcome is not supported in live mode")
            return _execute_attempt(attempt, timeout=self.timeout, dry_run=False)
        return self._mock_attempt(attempt, mock_outcome=mock_outcome)

    def _mock_attempt(
        self,
        attempt: KerberosAttempt,
        *,
        mock_outcome: str | None = None,
    ) -> KerberosAttemptResult:
        attempt_id = uuid.uuid4().hex[:8]
        outcome = mock_outcome or "auth_failed"
        connection_opened = outcome == "auth_failed"
        return KerberosAttemptResult(
            target=attempt.target,
            port=attempt.port,
            username=attempt.username,
            realm=attempt.realm,
            outcome=outcome,
            attempt_id=attempt_id,
            dry_run=True,
            connection_opened=connection_opened,
            evidence={
                "host": attempt.host,
                "port": attempt.port,
                "username": attempt.username,
                "realm": attempt.realm,
                "mock": True,
                "safe_mode": attempt.safe_mode,
            },
        )

    def make_attempt(self, planned: PlannedKerberosAttempt) -> KerberosAttempt:
        if not isinstance(planned, PlannedKerberosAttempt):
            raise KerberosProtocolError("planned attempt must be PlannedKerberosAttempt")
        return KerberosAttempt(
            host=planned.host,
            port=planned.port,
            username=planned.username,
            realm=planned.realm,
            safe_mode=planned.safe_mode,
        )
