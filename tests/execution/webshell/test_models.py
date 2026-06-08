"""Webshell model serialization tests."""

from __future__ import annotations

from datetime import datetime, timezone

from dsp.execution.webshell import (
    WebshellCapabilities,
    WebshellCommand,
    WebshellCommandResult,
    WebshellHealthResult,
    WebshellSession,
    WebshellTransferResult,
)


def test_webshell_command_roundtrip():
    original = WebshellCommand(
        command="python3 -V",
        timeout_seconds=15.0,
        working_directory="/tmp/dsp_stub/run01",
        environment={"DSP_RUN_ID": "run01"},
    )
    restored = WebshellCommand.from_dict(original.to_dict())
    assert restored.command == original.command
    assert restored.timeout_seconds == original.timeout_seconds
    assert restored.working_directory == original.working_directory
    assert restored.environment == original.environment


def test_webshell_command_result_roundtrip():
    original = WebshellCommandResult(
        success=True,
        exit_code=0,
        stdout="out",
        stderr="err",
        duration_ms=12.5,
        metadata={"transport": "POST"},
    )
    restored = WebshellCommandResult.from_dict(original.to_dict())
    assert restored == original


def test_webshell_session_roundtrip():
    now = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)
    caps = WebshellCapabilities(
        supports_execute=True,
        supports_upload=True,
        family="php",
    )
    original = WebshellSession(
        session_id="sess-01",
        provider_type="webshell",
        webshell_url="http://lab.example/shell.php",
        created_at=now,
        last_activity=now,
        capabilities=caps,
        metadata={"auth_mode": "cookie"},
    )
    restored = WebshellSession.from_dict(original.to_dict())
    assert restored.session_id == original.session_id
    assert restored.webshell_url == original.webshell_url
    assert restored.capabilities.family == "php"
    assert restored.metadata == original.metadata


def test_webshell_health_result_roundtrip():
    original = WebshellHealthResult(
        reachable=False,
        latency_ms=0.0,
        error="connection refused",
    )
    restored = WebshellHealthResult.from_dict(original.to_dict())
    assert restored.reachable is False
    assert restored.error == "connection refused"


def test_webshell_transfer_result_roundtrip():
    original = WebshellTransferResult(
        success=True,
        remote_path="/tmp/dsp_stub/run01/events.jsonl",
        bytes_transferred=1024,
        metadata={"sha256": "abc"},
    )
    restored = WebshellTransferResult.from_dict(original.to_dict())
    assert restored.remote_path == original.remote_path
    assert restored.bytes_transferred == 1024
