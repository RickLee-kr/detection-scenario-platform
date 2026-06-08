"""Timeout profile tests."""

from __future__ import annotations

import pytest

from dsp.execution.webshell.transport import (
    TIMEOUT_PROFILE_FAST,
    TIMEOUT_PROFILE_NORMAL,
    get_timeout_profile,
    validate_timeout_profile_name,
    validate_timeout_seconds,
)


def test_timeout_profiles_documented_values():
    fast = get_timeout_profile(TIMEOUT_PROFILE_FAST)
    normal = get_timeout_profile(TIMEOUT_PROFILE_NORMAL)
    assert fast.total_seconds == 15.0
    assert normal.total_seconds == 30.0
    assert fast.connect_seconds < normal.connect_seconds


def test_validate_timeout_profile_name_rejects_unknown():
    with pytest.raises(ValueError, match="unknown timeout profile"):
        validate_timeout_profile_name("invalid")


def test_validate_timeout_seconds_positive():
    with pytest.raises(ValueError, match="must be positive"):
        validate_timeout_seconds(0)


def test_validate_timeout_seconds_within_profile():
    validate_timeout_seconds(10.0, profile=TIMEOUT_PROFILE_FAST)
    with pytest.raises(ValueError, match="exceeds profile"):
        validate_timeout_seconds(100.0, profile=TIMEOUT_PROFILE_FAST)
