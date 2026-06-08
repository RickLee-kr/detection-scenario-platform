"""DGA domain generator — xdr.ooo NXDOMAIN and live.xdr.ooo resolvable phases."""

from __future__ import annotations

import random
import re
import string

from dsp.protocols.base import DnsProtocolError

EFFECTIVE_TLD_DEFAULT = "xdr.ooo"
PHASE1_COUNT_DEFAULT = 500
PHASE2_COUNT_DEFAULT = 30
LABEL_MIN_LEN = 10
LABEL_MAX_LEN = 16
LABEL_ALPHABET = string.ascii_lowercase + string.digits

NXDOMAIN_FQDN_PATTERN = re.compile(
    r"^[a-z0-9]{10,16}\.xdr\.ooo$",
    re.IGNORECASE,
)
RESOLVABLE_FQDN_PATTERN = re.compile(
    r"^[a-z0-9]{10,16}\.live\.xdr\.ooo$",
    re.IGNORECASE,
)


def random_label(
    *,
    min_len: int = LABEL_MIN_LEN,
    max_len: int = LABEL_MAX_LEN,
    rng: random.Random | None = None,
) -> str:
    """Generate a randomized DGA-like subdomain label."""
    if min_len < 1 or max_len < min_len:
        raise DnsProtocolError("invalid label length bounds")
    source = rng or random
    length = source.randint(min_len, max_len)
    return "".join(source.choice(LABEL_ALPHABET) for _ in range(length))


def generate_nxdomain_fqdn(
    effective_tld: str = EFFECTIVE_TLD_DEFAULT,
    *,
    rng: random.Random | None = None,
) -> str:
    """Generate Phase 1 FQDN: {random}.xdr.ooo"""
    tld = effective_tld.strip().rstrip(".")
    if not tld:
        raise DnsProtocolError("effective_tld is required")
    fqdn = f"{random_label(rng=rng)}.{tld}"
    if not is_nxdomain_fqdn(fqdn, effective_tld=tld):
        raise DnsProtocolError(f"invalid nxdomain FQDN: {fqdn}")
    return fqdn


def generate_resolvable_fqdn(
    effective_tld: str = EFFECTIVE_TLD_DEFAULT,
    *,
    rng: random.Random | None = None,
) -> str:
    """Generate Phase 2 FQDN: {random}.live.xdr.ooo"""
    tld = effective_tld.strip().rstrip(".")
    if not tld:
        raise DnsProtocolError("effective_tld is required")
    fqdn = f"{random_label(rng=rng)}.live.{tld}"
    if not is_resolvable_fqdn(fqdn, effective_tld=tld):
        raise DnsProtocolError(f"invalid resolvable FQDN: {fqdn}")
    return fqdn


def is_nxdomain_fqdn(fqdn: str, effective_tld: str = EFFECTIVE_TLD_DEFAULT) -> bool:
    """Return True for Phase 1 pattern {random}.{effective_tld} excluding live subdomain."""
    tld = effective_tld.strip().rstrip(".")
    if fqdn.lower().endswith(f".live.{tld}"):
        return False
    if not fqdn.lower().endswith(f".{tld}"):
        return False
    return bool(NXDOMAIN_FQDN_PATTERN.match(fqdn.lower()))


def is_resolvable_fqdn(fqdn: str, effective_tld: str = EFFECTIVE_TLD_DEFAULT) -> bool:
    """Return True for Phase 2 pattern {random}.live.{effective_tld}."""
    tld = effective_tld.strip().rstrip(".")
    if not fqdn.lower().endswith(f".live.{tld}"):
        return False
    return bool(RESOLVABLE_FQDN_PATTERN.match(fqdn.lower()))
