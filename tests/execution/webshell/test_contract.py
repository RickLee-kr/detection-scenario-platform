"""WebshellContract interface tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from dsp.execution.webshell import (
    WebshellCommand,
    WebshellCommandResult,
    WebshellContract,
    WebshellHealthResult,
    WebshellTransferResult,
)


class _StubWebshell(WebshellContract):
    def healthcheck(self) -> WebshellHealthResult:
        return WebshellHealthResult(reachable=True, latency_ms=1.0, family_detected="jsp")

    def execute(self, command: str | WebshellCommand) -> WebshellCommandResult:
        cmd = command if isinstance(command, str) else command.command
        return WebshellCommandResult(
            success=True,
            exit_code=0,
            stdout=f"ok:{cmd}",
            stderr="",
            duration_ms=2.0,
        )

    def upload(self, local_file: Path, remote_path: str) -> WebshellTransferResult:
        return WebshellTransferResult(
            success=True,
            remote_path=remote_path,
            bytes_transferred=local_file.stat().st_size,
        )

    def download(self, remote_path: str) -> WebshellTransferResult:
        return WebshellTransferResult(
            success=True,
            remote_path=remote_path,
            bytes_transferred=4,
            metadata={"content": b"data"},
        )

    def cleanup(self) -> None:
        pass

    def capture_stdout(self, result: WebshellCommandResult) -> str:
        return result.stdout.strip()

    def capture_stderr(self, result: WebshellCommandResult) -> str:
        return result.stderr.strip()


def test_webshell_contract_is_abstract():
    with pytest.raises(TypeError):
        WebshellContract()  # type: ignore[abstract]


def test_stub_implements_contract():
    stub = _StubWebshell()
    assert isinstance(stub, WebshellContract)

    health = stub.healthcheck()
    assert health.reachable is True
    assert health.family_detected == "jsp"

    result = stub.execute("echo test")
    assert result.success is True
    assert stub.capture_stdout(result) == "ok:echo test"

    cmd = WebshellCommand(command="id", timeout_seconds=10.0)
    result2 = stub.execute(cmd)
    assert "ok:id" in result2.stdout


def test_contract_methods_exist():
    stub = _StubWebshell()
    for name in (
        "healthcheck",
        "execute",
        "upload",
        "download",
        "cleanup",
        "capture_stdout",
        "capture_stderr",
    ):
        assert hasattr(stub, name)
        assert callable(getattr(stub, name))
