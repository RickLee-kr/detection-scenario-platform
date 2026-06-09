"""Tests for target-net safety guardrails."""

from __future__ import annotations

import pytest

from dsp.runtime.target_net_guard import (
    LARGE_TARGET_ERROR,
    is_larger_than_slash24,
    validate_target_net_scope,
)


def test_slash24_is_not_large() -> None:
    assert is_larger_than_slash24("10.10.10.0/24") is False
    assert is_larger_than_slash24("221.139.249.0/24") is False


def test_slash16_is_large() -> None:
    assert is_larger_than_slash24("10.0.0.0/16") is True


def test_large_target_blocked_without_opts() -> None:
    with pytest.raises(ValueError, match=LARGE_TARGET_ERROR):
        validate_target_net_scope(
            "10.0.0.0/16",
            allow_large_target=False,
            max_hosts=None,
        )


def test_large_target_requires_max_hosts_even_with_allow() -> None:
    with pytest.raises(ValueError, match=LARGE_TARGET_ERROR):
        validate_target_net_scope(
            "10.0.0.0/16",
            allow_large_target=True,
            max_hosts=None,
        )


def test_large_target_allowed_with_both_opts() -> None:
    validate_target_net_scope(
        "10.0.0.0/16",
        allow_large_target=True,
        max_hosts=5,
    )
