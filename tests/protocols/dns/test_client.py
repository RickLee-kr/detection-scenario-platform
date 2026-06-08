"""DNS protocol client unit tests."""

from __future__ import annotations

import socket
import struct
from unittest.mock import MagicMock, patch

import pytest

from dsp.protocols.base import DnsProtocolError
from dsp.protocols.dns import DnsClient, build_query, encode_qname, parse_response, send_udp_query


def test_encode_qname():
    assert encode_qname("example.com") == b"\x07example\x03com\x00"


def test_build_query_returns_packet():
    txn_id, packet = build_query("test.example.com", 1)
    assert isinstance(txn_id, int)
    assert len(packet) > 12
    assert packet[2:4] == b"\x01\x00"


def test_parse_response_noerror():
    packet = struct.pack("!HHHHHH", 1, 0x8180, 1, 2, 0, 0)
    rcode, summary = parse_response(packet)
    assert rcode == 0
    assert summary["answers"] == 2


def test_parse_response_nxdomain():
    packet = struct.pack("!HHHHHH", 1, 0x8183, 1, 0, 0, 0)
    rcode, summary = parse_response(packet)
    assert rcode == 3
    assert summary["answers"] == 0


def test_mock_query_response():
    client = DnsClient(mode="mock")
    result = client.query("10.10.10.20", "host.lab.example")
    assert result.outcome == "response"
    assert result.dry_run is True
    assert result.rcode == 0


def test_mock_query_timeout_prefix():
    client = DnsClient(mode="mock")
    result = client.query("10.10.10.20", "timeout.lab.example")
    assert result.outcome == "timeout"


def test_mock_query_nxdomain_prefix():
    client = DnsClient(mode="mock")
    result = client.query("10.10.10.20", "nx.missing.example")
    assert result.outcome == "nxdomain"
    assert result.rcode == 3


def test_legacy_mock_kwargs():
    client = DnsClient(dry_run=True, mock=True)
    assert client.mode == "mock"


def test_live_mode_available():
    client = DnsClient(mode="live")
    assert client.mode == "live"
    assert client.dry_run is False


def test_live_mode_rejects_mock_outcome():
    client = DnsClient(mode="live")
    with pytest.raises(DnsProtocolError, match="mock_outcome"):
        client.query("10.10.10.20", "host.lab.example", mock_outcome="response")


def test_mock_mode_no_socket_usage(monkeypatch):
    def fail_socket(*args, **kwargs):
        raise AssertionError("socket should not be used in mock mode")

    monkeypatch.setattr(socket, "socket", fail_socket)
    client = DnsClient(mode="mock")
    result = client.query("10.10.10.20", "host.lab.example")
    assert result.outcome == "response"


def _build_dns_response(txn_id: int, *, rcode: int = 0, ancount: int = 1) -> bytes:
    flags = 0x8180 | rcode
    header = struct.pack("!HHHHHH", txn_id, flags, 1, ancount, 0, 0)
    question = encode_qname("transport.lab.example") + struct.pack("!HH", 1, 1)
    answer = b""
    if ancount:
        answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 300, 4) + bytes([10, 10, 10, 1])
    return header + question + answer


def test_live_query_sends_udp_and_parses_response():
    txn_id, packet = build_query("transport.lab.example", 1)
    response = _build_dns_response(txn_id)

    mock_sock = MagicMock()
    mock_sock.recvfrom.return_value = (response, ("10.10.10.20", 53))

    with patch("dsp.protocols.dns.client.build_query", return_value=(txn_id, packet)):
        with patch("socket.socket", return_value=mock_sock):
            result = send_udp_query("10.10.10.20", "transport.lab.example", timeout=1.0)

    mock_sock.sendto.assert_called_once_with(packet, ("10.10.10.20", 53))
    assert result.outcome == "response"
    assert result.dry_run is False
    assert result.rcode == 0
    assert result.evidence["bytes_sent"] == len(packet)
    assert result.evidence["bytes_recv"] == len(response)


def test_live_query_timeout():
    mock_sock = MagicMock()
    mock_sock.recvfrom.side_effect = socket.timeout("timed out")

    with patch("socket.socket", return_value=mock_sock):
        result = send_udp_query("10.10.10.20", "transport.lab.example", timeout=0.1)

    assert result.outcome == "timeout"
    assert result.dry_run is False


def test_live_query_nxdomain():
    txn_id, packet = build_query("nx.transport.lab.example", 1)
    response = _build_dns_response(txn_id, rcode=3, ancount=0)

    mock_sock = MagicMock()
    mock_sock.recvfrom.return_value = (response, ("10.10.10.20", 53))

    with patch("dsp.protocols.dns.client.build_query", return_value=(txn_id, packet)):
        with patch("socket.socket", return_value=mock_sock):
            result = send_udp_query("10.10.10.20", "nx.transport.lab.example", timeout=1.0)

    assert result.outcome == "nxdomain"
    assert result.rcode == 3
