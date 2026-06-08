"""ExecutionContext and ProviderCapabilities model tests."""

from __future__ import annotations

from dsp.execution.models import ExecutionContext, ProviderCapabilities


def test_execution_context_fields():
    ctx = ExecutionContext(
        run_id="20260606_abc123",
        target_net="10.10.10.0/24",
        dry_run=True,
        provider_type="local",
        provider_config={"timeout": 30},
        scenario_id="dns_tunnel",
        execution_metadata={"traffic_origin_host": "local"},
    )
    assert ctx.run_id == "20260606_abc123"
    assert ctx.target_net == "10.10.10.0/24"
    assert ctx.dry_run is True
    assert ctx.provider_type == "local"
    assert ctx.scenario_id == "dns_tunnel"


def test_execution_context_roundtrip():
    original = ExecutionContext(
        run_id="run01",
        target_net="10.10.10.0/24",
        dry_run=False,
        provider_type="local",
        provider_config={"webshell_url": "http://example/ws.php"},
        scenario_id="http_followup",
        execution_metadata={"agent_id": "lab-victim-01", "ssh_target": "10.10.10.50"},
    )
    restored = ExecutionContext.from_dict(original.to_dict())
    assert restored.run_id == original.run_id
    assert restored.target_net == original.target_net
    assert restored.dry_run == original.dry_run
    assert restored.provider_type == original.provider_type
    assert restored.provider_config == original.provider_config
    assert restored.scenario_id == original.scenario_id
    assert restored.execution_metadata == original.execution_metadata


def test_provider_capabilities_to_dict():
    caps = ProviderCapabilities(
        provider_type="local",
        execution_mode="local",
        traffic_origin="dsp_host",
    )
    data = caps.to_dict()
    assert data["provider_type"] == "local"
    assert data["execution_mode"] == "local"
    assert data["traffic_origin"] == "dsp_host"
    assert data["supports_udp"] is True
    assert data["supports_tcp"] is True
    assert data["supports_http_client"] is True
