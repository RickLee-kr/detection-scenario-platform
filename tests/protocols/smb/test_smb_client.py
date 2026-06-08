"""SMB client unit tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from dsp.protocols.base import SmbProtocolError
from dsp.protocols.smb.attempts import PlannedSmbAttempt
from dsp.protocols.smb.client import SmbClient


def test_mock_attempt_returns_auth_failed():
    client = SmbClient(mode="mock")
    plan = PlannedSmbAttempt(
        host="10.10.10.30",
        port=445,
        username="administrator",
        password_label="InvalidPass1",
    )
    result = client.attempt(plan)
    assert result.outcome == "auth_failed"
    assert result.dry_run is True
    assert result.connection_opened is True


def test_live_safe_mode_requires_enabled():
    client = SmbClient(mode="live", safe_mode=True)
    plan = PlannedSmbAttempt(
        host="127.0.0.1",
        port=445,
        username="guest",
        password_label="InvalidPass1",
        safe_mode=False,
    )
    with pytest.raises(SmbProtocolError, match="safe_mode must remain enabled"):
        client.attempt(plan)


def test_live_attempt_uses_socket_connect_only():
    client = SmbClient(mode="live", safe_mode=True, timeout=1.0)
    plan = PlannedSmbAttempt(
        host="127.0.0.1",
        port=445,
        username="admin",
        password_label="InvalidPass1",
    )

    with patch("socket.create_connection") as connect_mock:
        connect_mock.return_value.__enter__.return_value = object()
        result = client.attempt(plan)

    assert result.outcome == "auth_failed"
    assert result.connection_opened is True
    assert result.evidence.get("note") == "tcp_connect_only_no_credentials"
    connect_mock.assert_called_once()
