"""Tests for scripts/run_dsp_release_1_0_lab_test.py."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from tests.e2e.fixtures.bundle_helpers import event_record, write_bundle
from tests.e2e.fixtures.webshell_test_server import WebshellTestServer

DSP_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = DSP_ROOT / "scripts" / "run_dsp_release_1_0_lab_test.py"
RUN_ID = "release_1_0_lab_script_test"


def _run_script(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SCRIPT_PATH), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _parse_run_id(stdout: str) -> str:
    match = re.search(r"^run_id=(\S+)", stdout, re.MULTILINE)
    assert match is not None, f"run_id not found in output:\n{stdout}"
    return match.group(1)


def test_help_works() -> None:
    result = _run_script("--help")
    assert result.returncode == 0
    assert "--mode" in result.stdout
    assert "local" in result.stdout
    assert "webshell" in result.stdout


def test_invalid_mode_fails_clearly() -> None:
    result = _run_script(
        "--mode",
        "invalid",
        "--output-dir",
        "/tmp/dsp-invalid-mode",
    )
    assert result.returncode != 0
    combined = f"{result.stdout}\n{result.stderr}"
    assert "invalid choice" in combined.lower() or "error" in combined.lower()


def test_local_mode_creates_expected_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "dsp-local-test"
    result = _run_script(
        "--mode",
        "local",
        "--scenario",
        "dummy",
        "--output-dir",
        str(output_dir),
        check=True,
    )

    assert result.returncode == 0
    assert "generated_files:" in result.stdout

    run_id = _parse_run_id(result.stdout)
    run_dir = output_dir / run_id
    assert run_dir.is_dir(), f"missing run directory: {run_dir}"

    expected = [
        run_dir / "events.db",
        run_dir / f"run_{run_id}.json",
        run_dir / f"run_{run_id}.md",
        run_dir / "verification_checklist.md",
        run_dir / "investigation_notes.md",
        run_dir / "evidence_summary_template.md",
    ]
    for path in expected:
        assert path.is_file(), f"missing expected artifact: {path}"
        assert path.stat().st_size > 0


def test_webshell_mode_creates_expected_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "dsp-webshell-test"
    storage_dir = tmp_path / "remote-storage"
    remote_bundle_path = f"/tmp/dsp/{RUN_ID}/events.jsonl"

    server = WebshellTestServer(storage_dir=storage_dir)
    server.start()
    try:
        bundle_path = storage_dir / "remote" / RUN_ID / "events.jsonl"
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        write_bundle(
            bundle_path,
            run_id=RUN_ID,
            scenario_id="dummy",
            events=[
                event_record(
                    run_id=RUN_ID,
                    scenario_id="dummy",
                    event="synthetic_action",
                    status="sent",
                    timestamp="2026-06-06T12:00:02Z",
                ),
            ],
        )
        server._files[remote_bundle_path] = bundle_path.read_bytes()

        result = _run_script(
            "--mode",
            "webshell",
            "--webshell-type",
            "jsp",
            "--webshell-url",
            server.webshell_url,
            "--remote-bundle-path",
            remote_bundle_path,
            "--output-dir",
            str(output_dir),
            "--run-id",
            RUN_ID,
            check=True,
        )
    finally:
        server.stop()

    assert result.returncode == 0
    assert "events_imported=1" in result.stdout or "events_imported" in result.stdout

    expected = [
        output_dir / "events.db",
        output_dir / f"run_{RUN_ID}.json",
        output_dir / f"run_{RUN_ID}.md",
        output_dir / "verification_checklist.md",
        output_dir / "investigation_notes.md",
        output_dir / "evidence_summary_template.md",
    ]
    for path in expected:
        assert path.is_file(), f"missing expected artifact: {path}"
        assert path.stat().st_size > 0

    assert server.command_calls[:3] == ["whoami", "pwd", "hostname"]


def test_webshell_mode_rejects_disallowed_command(tmp_path: Path) -> None:
    result = _run_script(
        "--mode",
        "webshell",
        "--webshell-type",
        "jsp",
        "--webshell-url",
        "http://127.0.0.1/shell.jsp",
        "--remote-bundle-path",
        "/tmp/dsp/events.jsonl",
        "--output-dir",
        str(tmp_path / "out"),
        "--webshell-commands",
        "rm,-rf,/",
    )
    assert result.returncode == 2
    assert "disallowed webshell command" in result.stderr
