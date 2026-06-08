"""LDAP protocol client — safe anonymous bind and search attempts only."""

from __future__ import annotations

import socket
import ssl
import subprocess
import uuid
from typing import Any

from dsp.protocols.base import LdapProtocolError
from dsp.protocols.ldap.attempts import PlannedLdapAction
from dsp.protocols.types import LdapAction, LdapActionResult

DEFAULT_TIMEOUT_SEC = 5.0

# LDAPv3 anonymous Simple Bind (message ID 1)
_LDAP_BIND_ANON = bytes(
    [0x30, 0x0C, 0x02, 0x01, 0x01, 0x60, 0x07, 0x02, 0x01, 0x03, 0x04, 0x00, 0x80, 0x00]
)


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


def _open_ldap_socket(host: str, port: int, *, timeout: float) -> socket.socket:
    sock = socket.create_connection((host, port), timeout=timeout)
    if port == 636:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx.wrap_socket(sock, server_hostname=host)
    return sock


def _send_anonymous_bind(sock: socket.socket, *, timeout: float) -> str:
    sock.settimeout(timeout)
    sock.sendall(_LDAP_BIND_ANON)
    response = sock.recv(4096)
    if not response:
        return "error"
    if len(response) >= 7 and response[5:7] == b"\x0a\x01\x00":
        return "bind_success"
    return "auth_failed"


def _run_ldapsearch(action: LdapAction, *, timeout: float) -> LdapActionResult:
    action_id = uuid.uuid4().hex[:8]
    scheme = "ldaps" if action.port == 636 else "ldap"
    cmd = [
        "ldapsearch",
        "-x",
        "-H",
        f"{scheme}://{action.host}:{action.port}",
        "-b",
        action.base_dn,
        "-s",
        "base" if action.base_dn == "" else "sub",
        "-LLL",
        "-l",
        str(max(1, min(int(timeout), 10))),
        action.search_filter,
        "dn",
    ]
    evidence: dict[str, Any] = {
        "host": action.host,
        "port": action.port,
        "filter": action.search_filter,
        "base_dn": action.base_dn,
        "safe_mode": action.safe_mode,
    }
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        stderr = (completed.stderr or "").lower()
        if completed.returncode == 0:
            return LdapActionResult(
                host=action.host,
                port=action.port,
                action_type=action.action_type,
                outcome="search_success",
                action_id=action_id,
                dry_run=False,
                evidence={**evidence, "returncode": completed.returncode},
            )
        if "invalid credentials" in stderr or "authentication" in stderr:
            outcome = "auth_failed"
        elif "connection refused" in stderr or "can't connect" in stderr:
            outcome = "connection_refused"
        elif "timed out" in stderr or "timeout" in stderr:
            outcome = "timeout"
        else:
            outcome = "error"
        return LdapActionResult(
            host=action.host,
            port=action.port,
            action_type=action.action_type,
            outcome=outcome,
            action_id=action_id,
            dry_run=False,
            evidence={
                **evidence,
                "returncode": completed.returncode,
                "stderr_excerpt": (completed.stderr or "")[:200],
            },
        )
    except subprocess.TimeoutExpired:
        return LdapActionResult(
            host=action.host,
            port=action.port,
            action_type=action.action_type,
            outcome="timeout",
            action_id=action_id,
            dry_run=False,
            evidence=evidence,
        )
    except FileNotFoundError as exc:
        raise LdapProtocolError("ldapsearch not found on PATH") from exc


def _execute_action(action: LdapAction, *, timeout: float, dry_run: bool) -> LdapActionResult:
    action_id = uuid.uuid4().hex[:8]
    evidence: dict[str, Any] = {
        "host": action.host,
        "port": action.port,
        "action_type": action.action_type,
        "safe_mode": action.safe_mode,
    }
    if action.search_filter:
        evidence["filter"] = action.search_filter
    if action.base_dn:
        evidence["base_dn"] = action.base_dn

    if dry_run:
        return LdapActionResult(
            host=action.host,
            port=action.port,
            action_type=action.action_type,
            outcome=_mock_outcome(action.action_type),
            action_id=action_id,
            dry_run=True,
            connection_opened=action.action_type != "connection",
            evidence={**evidence, "mock": True},
        )

    if not action.safe_mode:
        raise LdapProtocolError("safe_mode must remain enabled for LDAP enumeration scenario")

    if action.action_type == "connection":
        try:
            with _open_ldap_socket(action.host, action.port, timeout=timeout):
                return LdapActionResult(
                    host=action.host,
                    port=action.port,
                    action_type=action.action_type,
                    outcome="connection_opened",
                    action_id=action_id,
                    dry_run=False,
                    connection_opened=True,
                    evidence={**evidence, "note": "tcp_connect_only"},
                )
        except OSError as exc:
            return LdapActionResult(
                host=action.host,
                port=action.port,
                action_type=action.action_type,
                outcome=_classify_socket_error(exc),
                action_id=action_id,
                dry_run=False,
                connection_opened=False,
                evidence={**evidence, "message": str(exc)},
            )

    if action.action_type == "bind":
        try:
            with _open_ldap_socket(action.host, action.port, timeout=timeout) as sock:
                bind_outcome = _send_anonymous_bind(sock, timeout=timeout)
                return LdapActionResult(
                    host=action.host,
                    port=action.port,
                    action_type=action.action_type,
                    outcome=bind_outcome,
                    action_id=action_id,
                    dry_run=False,
                    connection_opened=True,
                    evidence={**evidence, "bind_type": "anonymous"},
                )
        except OSError as exc:
            return LdapActionResult(
                host=action.host,
                port=action.port,
                action_type=action.action_type,
                outcome=_classify_socket_error(exc),
                action_id=action_id,
                dry_run=False,
                connection_opened=False,
                evidence={**evidence, "message": str(exc)},
            )

    if action.action_type == "search":
        try:
            return _run_ldapsearch(action, timeout=timeout)
        except LdapProtocolError:
            try:
                with _open_ldap_socket(action.host, action.port, timeout=timeout) as sock:
                    _send_anonymous_bind(sock, timeout=timeout)
                    return LdapActionResult(
                        host=action.host,
                        port=action.port,
                        action_type=action.action_type,
                        outcome="error",
                        action_id=action_id,
                        dry_run=False,
                        connection_opened=True,
                        evidence={
                            **evidence,
                            "note": "search_attempt_no_ldapsearch",
                        },
                    )
            except OSError as exc:
                return LdapActionResult(
                    host=action.host,
                    port=action.port,
                    action_type=action.action_type,
                    outcome=_classify_socket_error(exc),
                    action_id=action_id,
                    dry_run=False,
                    connection_opened=False,
                    evidence={**evidence, "message": str(exc)},
                )

    raise LdapProtocolError(f"unknown action_type: {action.action_type}")


def _mock_outcome(action_type: str) -> str:
    if action_type == "connection":
        return "connection_opened"
    if action_type == "bind":
        return "auth_failed"
    return "error"


class LdapClient:
    """LDAP protocol client with mock and live modes."""

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
            raise LdapProtocolError(f"Invalid LDAP client mode: {resolved!r}")
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

    def execute(
        self,
        planned: PlannedLdapAction,
        *,
        mock_outcome: str | None = None,
    ) -> LdapActionResult:
        action = self.make_action(planned)
        if self.mode == "live":
            if mock_outcome is not None:
                raise LdapProtocolError("mock_outcome is not supported in live mode")
            return _execute_action(action, timeout=self.timeout, dry_run=False)
        return self._mock_action(action, mock_outcome=mock_outcome)

    def _mock_action(
        self,
        action: LdapAction,
        *,
        mock_outcome: str | None = None,
    ) -> LdapActionResult:
        action_id = uuid.uuid4().hex[:8]
        outcome = mock_outcome or _mock_outcome(action.action_type)
        connection_opened = action.action_type == "connection" and outcome == "connection_opened"
        if action.action_type in ("bind", "search"):
            connection_opened = outcome not in ("connection_refused", "timeout", "error")
        return LdapActionResult(
            host=action.host,
            port=action.port,
            action_type=action.action_type,
            outcome=outcome,
            action_id=action_id,
            dry_run=True,
            connection_opened=connection_opened,
            evidence={
                "host": action.host,
                "port": action.port,
                "action_type": action.action_type,
                "mock": True,
                "safe_mode": action.safe_mode,
            },
        )

    def make_action(self, planned: PlannedLdapAction) -> LdapAction:
        if not isinstance(planned, PlannedLdapAction):
            raise LdapProtocolError("planned action must be PlannedLdapAction")
        return LdapAction(
            host=planned.host,
            port=planned.port,
            action_type=planned.action_type,
            base_dn=planned.base_dn,
            search_filter=planned.search_filter,
            safe_mode=planned.safe_mode,
        )
