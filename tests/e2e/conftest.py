"""Shared fixtures and helpers for Release 1.0 E2E tests."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from dsp.event_store import EventQuery, EventStore
from dsp.evidence import EvidenceExportRequest, EvidenceExporter
from dsp.manual_verification import (
    ManualVerificationPackageGenerator,
    ManualVerificationRequest,
)
from tests.e2e.fixtures.webshell_test_server import WebshellTestServer

FORBIDDEN_RUNTIME_IMPORT_PREFIXES = (
    "dsp.validation",
    "dsp.detection",
    "dsp.reporting",
)

FORBIDDEN_RUNTIME_SYMBOLS = (
    "ValidationEngine",
    "ReportingEngine",
    "validate_run",
    "generate_report",
)


@pytest.fixture
def e2e_output_dir(tmp_path: Path) -> Path:
    output = tmp_path / "artifacts"
    output.mkdir()
    return output


@pytest.fixture
def e2e_event_store(tmp_path: Path) -> EventStore:
    db_path = tmp_path / "events.db"
    store = EventStore(db_path)
    store.open_run("release_1_0_e2e_run")
    return store


@pytest.fixture
def webshell_test_server(tmp_path: Path):
    server = WebshellTestServer(storage_dir=tmp_path / "remote-storage")
    server.start()
    try:
        yield server
    finally:
        server.stop()


def export_evidence(store: EventStore, run_id: str, output_dir: Path):
    return EvidenceExporter(store).export(
        EvidenceExportRequest(run_id=run_id, output_directory=output_dir)
    )


def generate_manual_verification(store: EventStore, run_id: str, output_dir: Path):
    return ManualVerificationPackageGenerator(store).generate(
        ManualVerificationRequest(run_id=run_id, output_directory=output_dir)
    )


def assert_event_store_has_events(store: EventStore, run_id: str, *, minimum: int = 1) -> int:
    count = store.count(EventQuery(run_id=run_id))
    assert count >= minimum, f"expected at least {minimum} events, found {count}"
    return count


def assert_evidence_exports_exist(output_dir: Path, run_id: str) -> None:
    json_path = output_dir / f"run_{run_id}.json"
    markdown_path = output_dir / f"run_{run_id}.md"
    assert json_path.is_file(), f"missing JSON evidence export: {json_path}"
    assert markdown_path.is_file(), f"missing Markdown evidence export: {markdown_path}"
    assert json_path.stat().st_size > 0
    assert markdown_path.stat().st_size > 0


def assert_manual_verification_package_exists(output_dir: Path) -> None:
    checklist = output_dir / "verification_checklist.md"
    notes = output_dir / "investigation_notes.md"
    summary = output_dir / "evidence_summary_template.md"
    for path in (checklist, notes, summary):
        assert path.is_file(), f"missing manual verification file: {path}"
        assert path.stat().st_size > 0


def assert_harness_excludes_validation_runtime(module_path: Path) -> None:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for prefix in FORBIDDEN_RUNTIME_IMPORT_PREFIXES:
                    assert not alias.name.startswith(prefix), (
                        f"forbidden import {alias.name!r} in {module_path.name}"
                    )
        elif isinstance(node, ast.ImportFrom) and node.module:
            for prefix in FORBIDDEN_RUNTIME_IMPORT_PREFIXES:
                assert not node.module.startswith(prefix), (
                    f"forbidden import from {node.module!r} in {module_path.name}"
                )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in FORBIDDEN_RUNTIME_SYMBOLS, (
                f"forbidden runtime call {node.func.id!r} in {module_path.name}"
            )


def assert_no_inference_logic_in_callable(callable_obj: object) -> None:
    source = inspect.getsource(callable_obj).lower()
    for token in ("execution_success", "attack_success", "alert_created"):
        assert token not in source
