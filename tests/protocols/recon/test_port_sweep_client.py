"""Port sweep client unit tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from dsp.protocols.base import ReconProtocolError
from dsp.protocols.recon.attempts import PlannedPortProbe, plan_port_sweep
from dsp.protocols.recon.client import PortSweepClient


def test_mock_probe_returns_connection_refused():
    client = PortSweepClient(mode="mock")
    plan = PlannedPortProbe(host="10.10.10.30", port=22)
    result = client.probe(plan)
    assert result.outcome == "connection_refused"
    assert result.dry_run is True
    assert result.connection_opened is False


def test_plan_port_sweep_default_ports():
    plans = plan_port_sweep(["10.10.10.30"], max_ports=5)
    assert len(plans) == 5
    assert plans[0].port == 22
    assert plans[4].port == 80


def test_plan_port_sweep_rejects_unsafe_port():
    with pytest.raises(ReconProtocolError, match="not allowed in safe mode"):
        plan_port_sweep(["10.10.10.30"], ports=[8080], safe_mode=True)


def test_live_safe_mode_requires_enabled():
    client = PortSweepClient(mode="live", safe_mode=True)
    plan = PlannedPortProbe(host="127.0.0.1", port=22, safe_mode=False)
    with pytest.raises(ReconProtocolError, match="safe_mode must remain enabled"):
        client.probe(plan)


def test_live_probe_uses_socket_connect_only():
    client = PortSweepClient(mode="live", safe_mode=True, timeout=1.0)
    plan = PlannedPortProbe(host="127.0.0.1", port=22)

    with patch("socket.create_connection") as connect_mock:
        connect_mock.return_value.__enter__.return_value = object()
        result = client.probe(plan)

    assert result.outcome == "connection_opened"
    assert result.connection_opened is True
    assert result.evidence.get("note") == "tcp_connect_only_no_payload"
    connect_mock.assert_called_once()
