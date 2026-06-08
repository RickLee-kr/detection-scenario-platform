"""DGA domain generator and format unit tests."""

from __future__ import annotations

import random

import pytest

from dsp.protocols.dns.dga import (
    EFFECTIVE_TLD_DEFAULT,
    PHASE1_COUNT_DEFAULT,
    PHASE2_COUNT_DEFAULT,
    generate_nxdomain_fqdn,
    generate_resolvable_fqdn,
    is_nxdomain_fqdn,
    is_resolvable_fqdn,
    random_label,
)


def test_random_label_length_bounds():
    rng = random.Random(42)
    label = random_label(rng=rng)
    assert 10 <= len(label) <= 16
    assert label.isalnum()
    assert label == label.lower()


def test_generate_nxdomain_fqdn_format():
    rng = random.Random(1)
    fqdn = generate_nxdomain_fqdn(rng=rng)
    assert fqdn.endswith(f".{EFFECTIVE_TLD_DEFAULT}")
    assert ".live." not in fqdn
    assert is_nxdomain_fqdn(fqdn)
    assert not is_resolvable_fqdn(fqdn)


def test_generate_resolvable_fqdn_format():
    rng = random.Random(2)
    fqdn = generate_resolvable_fqdn(rng=rng)
    assert fqdn.endswith(f".live.{EFFECTIVE_TLD_DEFAULT}")
    assert is_resolvable_fqdn(fqdn)
    assert not is_nxdomain_fqdn(fqdn)


def test_phase_defaults():
    assert PHASE1_COUNT_DEFAULT == 500
    assert PHASE2_COUNT_DEFAULT == 30


def test_example_domain_patterns():
    assert is_nxdomain_fqdn("rf2xh8lxoxv.xdr.ooo")
    assert is_resolvable_fqdn("a8fj3kq9xy.live.xdr.ooo")


def test_nxdomain_rejects_live_subdomain():
    assert not is_nxdomain_fqdn("abc.live.xdr.ooo")
