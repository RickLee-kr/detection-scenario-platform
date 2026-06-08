"""DNS Tunnel encoder and chunk generator — idx-pattern FQDNs."""

from __future__ import annotations

import base64
import os
import re
from typing import Iterator

from dsp.protocols.base import DnsProtocolError

CHUNK_SIZE_DEFAULT = 30
PAYLOAD_MB_DEFAULT = 2.0
TUNNEL_DOMAIN_DEFAULT = "dns-tunnel.com"
IDX_FQDN_PATTERN = re.compile(r"^idx-\d{6}-[a-z2-7]+\.", re.IGNORECASE)


def chunk_to_b32_label(chunk: bytes) -> str:
    """Encode raw chunk bytes as lowercase unpadded Base32 label."""
    return base64.b32encode(chunk).decode("ascii").lower().rstrip("=")


def plan_chunk_count(payload_mb: float, chunk_size: int = CHUNK_SIZE_DEFAULT) -> int:
    """Return number of fixed-size chunks for a payload volume."""
    if payload_mb <= 0:
        raise DnsProtocolError("payload_mb must be positive")
    if chunk_size <= 0:
        raise DnsProtocolError("chunk_size must be positive")
    total_bytes = int(payload_mb * 1024 * 1024)
    return max(1, (total_bytes + chunk_size - 1) // chunk_size)


def iter_payload_chunks(
    payload_mb: float,
    chunk_size: int = CHUNK_SIZE_DEFAULT,
) -> Iterator[bytes]:
    """Yield fixed-size random payload chunks up to payload_mb."""
    total_bytes = int(payload_mb * 1024 * 1024)
    if total_bytes < chunk_size:
        total_bytes = chunk_size
    produced = 0
    while produced < total_bytes:
        need = min(chunk_size, total_bytes - produced)
        yield os.urandom(need)
        produced += need


def build_tunnel_fqdn(seq: int, payload_b32: str, domain: str) -> str:
    """Build idx-{seq:06d}-{payload}.{domain} FQDN."""
    if seq < 1:
        raise DnsProtocolError("chunk sequence must be >= 1")
    domain = domain.strip().rstrip(".")
    if not domain:
        raise DnsProtocolError("tunnel domain is required")
    if not payload_b32:
        raise DnsProtocolError("payload label is required")
    label = f"idx-{seq:06d}-{payload_b32}"
    if len(label) > 63:
        raise DnsProtocolError(f"DNS label exceeds 63 bytes: {len(label)}")
    fqdn = f"{label}.{domain}"
    if not is_valid_tunnel_fqdn(fqdn):
        raise DnsProtocolError(f"invalid tunnel FQDN: {fqdn}")
    return fqdn


def is_valid_tunnel_fqdn(fqdn: str) -> bool:
    """Return True when FQDN matches idx-000001-{payload}.{domain}."""
    return bool(IDX_FQDN_PATTERN.match(fqdn))
