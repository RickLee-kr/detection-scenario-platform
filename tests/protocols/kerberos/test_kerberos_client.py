"""Kerberos client unit tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dsp.protocols.base import KerberosProtocolError
from dsp.protocols.kerberos.attempts import PlannedKerberosAttempt
from dsp.protocols.kerberos.client import KerberosClient, _build_as_req_probe


def test_build_as_req_probe_returns_bytes():
    probe = _build_as_req_probe("administrator", "LOCAL.REALM")
    assert isinstance(probe, bytes)
    assert len(probe) > 10


def test_mock_attempt_returns_auth_failed():
    client = KerberosClient(mode="mock")
    plan = PlannedKerberosAttempt(
        host="10.10.10.30",
        port=88,
        username="administrator",
        realm="LOCAL.REALM",
    )
    result = client.attempt(plan)
    assert result.outcome == "auth_failed"
    assert result.dry_run is True
    assert result.connection_opened is True


def test_live_safe_mode_requires_enabled():
    client = KerberosClient(mode="live", safe_mode=True)
    plan = PlannedKerberosAttempt(
        host="127.0.0.1",
        port=88,
        username="guest",
        realm="LOCAL.REALM",
        safe_mode=False,
    )
    with pytest.raises(KerberosProtocolError, match="safe_mode must remain enabled"):
        client.attempt(plan)


def test_live_attempt_uses_udp_as_req():
    client = KerberosClient(mode="live", safe_mode=True, timeout=1.0)
    plan = PlannedKerberosAttempt(
        host="127.0.0.1",
        port=88,
        username="admin",
        realm="LOCAL.REALM",
    )

    mock_sock = MagicMock()
    mock_sock.recvfrom.return_value = (b"\x7e\x00", ("127.0.0.1", 88))

    with patch("socket.socket", return_value=mock_sock):
        result = client.attempt(plan)

    assert result.outcome == "auth_failed"
    assert result.connection_opened is True
    assert result.evidence.get("note") == "as_req_invalid_preauth"
    mock_sock.sendto.assert_called_once()
