"""LDAP client unit tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from dsp.protocols.base import LdapProtocolError
from dsp.protocols.ldap.attempts import PlannedLdapAction, plan_ldap_enumeration
from dsp.protocols.ldap.client import LdapClient


def test_mock_bind_returns_auth_failed():
    client = LdapClient(mode="mock")
    plan = PlannedLdapAction(host="10.10.10.30", port=389, action_type="bind")
    result = client.execute(plan)
    assert result.outcome == "auth_failed"
    assert result.dry_run is True


def test_mock_search_returns_error():
    client = LdapClient(mode="mock")
    plan = PlannedLdapAction(
        host="10.10.10.30",
        port=389,
        action_type="search",
        search_filter="(objectClass=user)",
    )
    result = client.execute(plan)
    assert result.outcome == "error"
    assert result.dry_run is True


def test_plan_rejects_unsafe_filter():
    with pytest.raises(LdapProtocolError, match="filter not allowed"):
        plan_ldap_enumeration(
            ["10.10.10.30"],
            filters=["(uid=admin)"],
            max_queries_per_host=1,
        )


def test_live_safe_mode_requires_enabled():
    client = LdapClient(mode="live", safe_mode=True)
    plan = PlannedLdapAction(
        host="127.0.0.1",
        port=389,
        action_type="connection",
        safe_mode=False,
    )
    with pytest.raises(LdapProtocolError, match="safe_mode must remain enabled"):
        client.execute(plan)


def test_live_connection_uses_socket():
    client = LdapClient(mode="live", safe_mode=True, timeout=1.0)
    plan = PlannedLdapAction(host="127.0.0.1", port=389, action_type="connection")

    with patch("socket.create_connection") as connect_mock:
        connect_mock.return_value.__enter__.return_value = object()
        result = client.execute(plan)

    assert result.outcome == "connection_opened"
    assert result.connection_opened is True
    connect_mock.assert_called_once()
