"""SMB attempt planning unit tests."""

from __future__ import annotations

import pytest

from dsp.protocols.base import SmbProtocolError
from dsp.protocols.smb.attempts import (
    ATTEMPTS_PER_HOST_DEFAULT,
    DEFAULT_PASSWORD_LABELS,
    DEFAULT_USERNAMES,
    MAX_ATTEMPTS_PER_HOST,
    MAX_HOSTS_DEFAULT,
    plan_smb_attempts,
)


def test_default_usernames_fixed_list():
    assert DEFAULT_USERNAMES == ("administrator", "admin", "guest", "test", "user")


def test_default_password_labels_dummy_values_only():
    assert DEFAULT_PASSWORD_LABELS == ("InvalidPass1", "InvalidPass2", "InvalidPass3")


def test_plan_smb_attempts_single_host_default_caps():
    plans = plan_smb_attempts(["10.10.10.30"])
    assert len(plans) == ATTEMPTS_PER_HOST_DEFAULT
    assert all(p.host == "10.10.10.30" for p in plans)
    assert all(p.port == 445 for p in plans)
    assert all(p.safe_mode is True for p in plans)


def test_plan_smb_attempts_multiple_hosts():
    hosts = [f"10.10.10.{i}" for i in range(30, 33)]
    plans = plan_smb_attempts(hosts, max_hosts=MAX_HOSTS_DEFAULT, attempts_per_host=10)
    assert len(plans) == 30
    assert len({p.host for p in plans}) == 3


def test_plan_smb_attempts_respects_max_attempts_per_host():
    with pytest.raises(SmbProtocolError, match="exceeds maximum"):
        plan_smb_attempts(["10.10.10.30"], attempts_per_host=MAX_ATTEMPTS_PER_HOST + 1)


def test_plan_smb_attempts_cycles_usernames():
    plans = plan_smb_attempts(["10.10.10.30"], attempts_per_host=10)
    usernames = [p.username for p in plans]
    assert usernames[:5] == list(DEFAULT_USERNAMES)
    assert usernames[5:10] == list(DEFAULT_USERNAMES)


def test_plan_smb_attempts_requires_host():
    with pytest.raises(SmbProtocolError, match="at least one host"):
        plan_smb_attempts([])
