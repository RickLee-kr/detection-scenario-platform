"""Port sweep client — safe controlled TCP connection attempts only."""

from __future__ import annotations

import socket
import uuid
from typing import Any

from dsp.protocols.base import ReconProtocolError
from dsp.protocols.recon.attempts import PlannedPortProbe
from dsp.protocols.types import PortProbe, PortProbeResult

DEFAULT_TIMEOUT_SEC = 3.0


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


def _execute_probe(probe: PortProbe, *, timeout: float, dry_run: bool) -> PortProbeResult:
    probe_id = uuid.uuid4().hex[:8]
    evidence: dict[str, Any] = {
        "host": probe.host,
        "port": probe.port,
        "safe_mode": probe.safe_mode,
    }

    if dry_run:
        return PortProbeResult(
            host=probe.host,
            port=probe.port,
            outcome="connection_refused",
            probe_id=probe_id,
            dry_run=True,
            connection_opened=False,
            evidence={**evidence, "mock": True},
        )

    if not probe.safe_mode:
        raise ReconProtocolError("safe_mode must remain enabled for port sweep scenario")

    try:
        with socket.create_connection((probe.host, probe.port), timeout=timeout):
            return PortProbeResult(
                host=probe.host,
                port=probe.port,
                outcome="connection_opened",
                probe_id=probe_id,
                dry_run=False,
                connection_opened=True,
                evidence={
                    **evidence,
                    "note": "tcp_connect_only_no_payload",
                },
            )
    except OSError as exc:
        outcome = _classify_socket_error(exc)
        return PortProbeResult(
            host=probe.host,
            port=probe.port,
            outcome=outcome,
            probe_id=probe_id,
            dry_run=False,
            connection_opened=False,
            evidence={**evidence, "message": str(exc)},
        )


class PortSweepClient:
    """Port sweep client with mock and live modes."""

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
            raise ReconProtocolError(f"Invalid port sweep client mode: {resolved!r}")
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

    def probe(
        self,
        planned: PlannedPortProbe,
        *,
        mock_outcome: str | None = None,
    ) -> PortProbeResult:
        probe = self.make_probe(planned)
        if self.mode == "live":
            if mock_outcome is not None:
                raise ReconProtocolError("mock_outcome is not supported in live mode")
            return _execute_probe(probe, timeout=self.timeout, dry_run=False)
        return self._mock_probe(probe, mock_outcome=mock_outcome)

    def _mock_probe(
        self,
        probe: PortProbe,
        *,
        mock_outcome: str | None = None,
    ) -> PortProbeResult:
        probe_id = uuid.uuid4().hex[:8]
        outcome = mock_outcome or "connection_refused"
        connection_opened = outcome == "connection_opened"
        return PortProbeResult(
            host=probe.host,
            port=probe.port,
            outcome=outcome,
            probe_id=probe_id,
            dry_run=True,
            connection_opened=connection_opened,
            evidence={
                "host": probe.host,
                "port": probe.port,
                "mock": True,
                "safe_mode": probe.safe_mode,
            },
        )

    def make_probe(self, planned: PlannedPortProbe) -> PortProbe:
        if not isinstance(planned, PlannedPortProbe):
            raise ReconProtocolError("planned probe must be PlannedPortProbe")
        return PortProbe(
            host=planned.host,
            port=planned.port,
            safe_mode=planned.safe_mode,
        )
