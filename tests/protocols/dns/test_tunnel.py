"""DNS Tunnel encoder and FQDN format unit tests."""

from __future__ import annotations

import base64

import pytest

from dsp.protocols.base import DnsProtocolError
from dsp.protocols.dns.tunnel import (
    CHUNK_SIZE_DEFAULT,
    build_tunnel_fqdn,
    chunk_to_b32_label,
    is_valid_tunnel_fqdn,
    iter_payload_chunks,
    plan_chunk_count,
)


def test_chunk_to_b32_label():
    chunk = b"hello-world-payload-30bytes!!"
    label = chunk_to_b32_label(chunk[:30])
    assert label == base64.b32encode(chunk[:30]).decode("ascii").lower().rstrip("=")
    assert "=" not in label


def test_plan_chunk_count_2mb():
    count = plan_chunk_count(2.0, CHUNK_SIZE_DEFAULT)
    assert count == (2 * 1024 * 1024 + CHUNK_SIZE_DEFAULT - 1) // CHUNK_SIZE_DEFAULT


def test_iter_payload_chunks_sizes():
    chunks = list(iter_payload_chunks(0.0001, chunk_size=30))
    assert len(chunks) >= 1
    assert all(len(c) <= 30 for c in chunks)
    assert sum(len(c) for c in chunks) >= 30


def test_build_tunnel_fqdn_format():
    fqdn = build_tunnel_fqdn(1, "mfrggzdfmy", "dns-tunnel.com")
    assert fqdn == "idx-000001-mfrggzdfmy.dns-tunnel.com"
    assert is_valid_tunnel_fqdn(fqdn)


def test_build_tunnel_fqdn_sequence_padding():
    fqdn = build_tunnel_fqdn(42, "abc", "lab.example")
    assert fqdn.startswith("idx-000042-")


def test_invalid_tunnel_fqdn_rejected():
    assert not is_valid_tunnel_fqdn("strt-session.dns-tunnel.com")
    assert not is_valid_tunnel_fqdn("idx-1-abc.dns-tunnel.com")


def test_build_tunnel_fqdn_label_too_long():
    with pytest.raises(DnsProtocolError, match="exceeds 63"):
        build_tunnel_fqdn(1, "a" * 60, "dns-tunnel.com")
