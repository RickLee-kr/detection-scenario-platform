"""DNS protocol client — mock and live UDP/53 transport."""

from __future__ import annotations

import socket
import struct
import uuid
from typing import Any

from dsp.protocols.base import DnsProtocolError
from dsp.protocols.types import DnsQuery, DnsQueryResult

QTYPE_MAP = {"A": 1, "AAAA": 28, "TXT": 16, "MX": 15}
RCODE_NOERROR = 0
RCODE_NXDOMAIN = 3
DEFAULT_TIMEOUT_SEC = 2.0


def encode_qname(fqdn: str) -> bytes:
    """Encode domain name to DNS QNAME wire format."""
    if not fqdn or fqdn.endswith("."):
        fqdn = fqdn.rstrip(".")
    parts = fqdn.split(".")
    encoded = b""
    for label in parts:
        if not label or len(label) > 63:
            raise DnsProtocolError(f"Invalid DNS label: {label!r}")
        encoded += struct.pack("B", len(label)) + label.encode("ascii")
    return encoded + b"\x00"


def build_query(fqdn: str, qtype: int = 1) -> tuple[int, bytes]:
    """Build DNS query packet (transaction_id, wire_bytes)."""
    txn_id = struct.unpack("!H", uuid.uuid4().bytes[:2])[0]
    header = struct.pack("!HHHHHH", txn_id, 0x0100, 1, 0, 0, 0)
    question = encode_qname(fqdn) + struct.pack("!HH", qtype, 1)
    return txn_id, header + question


def parse_response(packet: bytes) -> tuple[int, dict[str, Any]]:
    """Parse DNS response header and return (rcode, summary)."""
    if len(packet) < 12:
        raise DnsProtocolError("DNS response too short")
    flags = struct.unpack("!H", packet[2:4])[0]
    rcode = flags & 0x0F
    ancount = struct.unpack("!H", packet[6:8])[0]
    return rcode, {"answers": ancount, "flags": flags}


def send_udp_query(
    resolver: str,
    fqdn: str,
    *,
    qtype: str = "A",
    port: int = 53,
    timeout: float = DEFAULT_TIMEOUT_SEC,
) -> DnsQueryResult:
    """Send a single DNS query over UDP/53 and return the protocol result."""
    qtype_id = QTYPE_MAP.get(qtype.upper(), 1)
    txn_id, packet = build_query(fqdn, qtype_id)
    query_id = f"{txn_id:04x}"
    evidence: dict[str, Any] = {"txn_id": txn_id, "port": port, "bytes_sent": len(packet)}

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(packet, (resolver, port))
        try:
            data, peer = sock.recvfrom(4096)
        except socket.timeout:
            return DnsQueryResult(
                fqdn=fqdn,
                qtype=qtype.upper(),
                outcome="timeout",
                resolver=resolver,
                query_id=query_id,
                dry_run=False,
                evidence=evidence,
            )
        except OSError as exc:
            return DnsQueryResult(
                fqdn=fqdn,
                qtype=qtype.upper(),
                outcome="error",
                resolver=resolver,
                query_id=query_id,
                dry_run=False,
                response_summary={"message": str(exc)},
                evidence=evidence,
            )

        evidence["bytes_recv"] = len(data)
        evidence["peer"] = f"{peer[0]}:{peer[1]}"

        if len(data) < 2:
            return DnsQueryResult(
                fqdn=fqdn,
                qtype=qtype.upper(),
                outcome="error",
                resolver=resolver,
                query_id=query_id,
                dry_run=False,
                response_summary={"message": "empty DNS response"},
                evidence=evidence,
            )

        resp_txn = struct.unpack("!H", data[:2])[0]
        if resp_txn != txn_id:
            return DnsQueryResult(
                fqdn=fqdn,
                qtype=qtype.upper(),
                outcome="error",
                resolver=resolver,
                query_id=query_id,
                dry_run=False,
                response_summary={"message": "transaction ID mismatch"},
                evidence={**evidence, "resp_txn_id": resp_txn},
            )

        try:
            rcode, summary = parse_response(data)
        except DnsProtocolError as exc:
            return DnsQueryResult(
                fqdn=fqdn,
                qtype=qtype.upper(),
                outcome="error",
                resolver=resolver,
                query_id=query_id,
                dry_run=False,
                response_summary={"message": str(exc)},
                evidence=evidence,
            )

        if rcode == RCODE_NXDOMAIN:
            outcome = "nxdomain"
        elif rcode == RCODE_NOERROR:
            outcome = "response"
        else:
            return DnsQueryResult(
                fqdn=fqdn,
                qtype=qtype.upper(),
                outcome="error",
                resolver=resolver,
                rcode=rcode,
                query_id=query_id,
                dry_run=False,
                response_summary={"message": f"unexpected rcode {rcode}"},
                evidence=evidence,
            )

        return DnsQueryResult(
            fqdn=fqdn,
            qtype=qtype.upper(),
            outcome=outcome,
            resolver=resolver,
            rcode=rcode,
            response_summary={**summary, "mock": False},
            query_id=query_id,
            dry_run=False,
            evidence=evidence,
        )
    except OSError as exc:
        return DnsQueryResult(
            fqdn=fqdn,
            qtype=qtype.upper(),
            outcome="error",
            resolver=resolver,
            query_id=query_id,
            dry_run=False,
            response_summary={"message": str(exc)},
            evidence=evidence,
        )
    finally:
        sock.close()


class DnsClient:
    """
    DNS protocol client.

    Supports mode=mock (no network I/O) and mode=live (UDP/53 transport).
    """

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
            raise DnsProtocolError(f"Invalid DNS client mode: {resolved!r}")
        self.mode = resolved
        self.dry_run = resolved == "mock"
        self.mock = resolved == "mock"
        self.timeout = timeout

    @staticmethod
    def _resolve_mode(*, mode: str | None, dry_run: bool, mock: bool) -> str:
        if mode is not None:
            return mode
        return "mock" if (dry_run or mock) else "live"

    def query(
        self,
        resolver: str,
        fqdn: str,
        *,
        qtype: str = "A",
        port: int = 53,
        mock_outcome: str | None = None,
    ) -> DnsQueryResult:
        """Execute a DNS query in mock or live mode."""
        if self.mode == "live":
            if mock_outcome is not None:
                raise DnsProtocolError("mock_outcome is not supported in live mode")
            return send_udp_query(
                resolver,
                fqdn,
                qtype=qtype,
                port=port,
                timeout=self.timeout,
            )
        return self._mock_query(resolver, fqdn, qtype=qtype, port=port, mock_outcome=mock_outcome)

    def _mock_query(
        self,
        resolver: str,
        fqdn: str,
        *,
        qtype: str = "A",
        port: int = 53,
        mock_outcome: str | None = None,
    ) -> DnsQueryResult:
        qtype_id = QTYPE_MAP.get(qtype.upper(), 1)
        txn_id, _packet = build_query(fqdn, qtype_id)
        query_id = f"{txn_id:04x}"

        outcome = mock_outcome or self._default_mock_outcome(fqdn)
        rcode: int | None = None
        response_summary: dict[str, Any] | None = None

        if outcome == "response":
            rcode = RCODE_NOERROR
            response_summary = {"answers": 1, "mock": True}
        elif outcome == "nxdomain":
            rcode = RCODE_NXDOMAIN
            response_summary = {"answers": 0, "mock": True}
        elif outcome == "timeout":
            rcode = None
        elif outcome == "error":
            rcode = None
            response_summary = {"message": "mock protocol error"}

        return DnsQueryResult(
            fqdn=fqdn,
            qtype=qtype.upper(),
            outcome=outcome,
            resolver=resolver,
            rcode=rcode,
            response_summary=response_summary,
            query_id=query_id,
            dry_run=True,
            evidence={"txn_id": txn_id, "port": port},
        )

    @staticmethod
    def _default_mock_outcome(fqdn: str) -> str:
        lower = fqdn.lower()
        if lower.startswith("timeout."):
            return "timeout"
        if lower.startswith("error."):
            return "error"
        if lower.startswith("nx."):
            return "nxdomain"
        return "response"

    def make_query(self, resolver: str, fqdn: str, qtype: str = "A", port: int = 53) -> DnsQuery:
        return DnsQuery(fqdn=fqdn, qtype=qtype, resolver=resolver, port=port)
