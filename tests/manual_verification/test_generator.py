"""Manual verification package unit tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from dsp.event_store import Event, EventStore
from dsp.evidence import EvidenceExportRequest, EvidenceExporter
from dsp.manual_verification import (
    ManualVerificationPackageGenerator,
    ManualVerificationRequest,
)


def _event(**kwargs) -> Event:
    defaults = {
        "run_id": "verify_run",
        "scenario_id": "dummy",
        "timestamp": datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc),
        "stage": "executor",
        "event": "synthetic_action",
        "status": "sent",
        "source": "dry_run",
    }
    defaults.update(kwargs)
    return Event(**defaults)


def _prepare_run(tmp_path: Path, run_id: str = "verify_run", count: int = 3) -> EventStore:
    store = EventStore(":memory:")
    store.open_run(run_id)
    for index in range(count):
        store.append(
            _event(
                timestamp=datetime(2026, 6, 6, 12, index, 0, tzinfo=timezone.utc),
                event=f"event_{index}",
            )
        )
    EvidenceExporter(store).export(
        EvidenceExportRequest(run_id=run_id, output_directory=tmp_path)
    )
    return store


def test_checklist_generated(tmp_path: Path) -> None:
    store = _prepare_run(tmp_path)
    result = ManualVerificationPackageGenerator(store).generate(
        ManualVerificationRequest(run_id="verify_run", output_directory=tmp_path)
    )

    checklist_path = tmp_path / "verification_checklist.md"
    assert checklist_path.exists()
    text = checklist_path.read_text(encoding="utf-8")
    assert "# Verification Checklist" in text
    assert "Run ID: verify_run" in text
    assert "[ ] Evidence files reviewed" in text
    assert str(checklist_path) in result.generated_files


def test_notes_template_generated(tmp_path: Path) -> None:
    store = _prepare_run(tmp_path)
    result = ManualVerificationPackageGenerator(store).generate(
        ManualVerificationRequest(run_id="verify_run", output_directory=tmp_path)
    )

    notes_path = tmp_path / "investigation_notes.md"
    assert notes_path.exists()
    text = notes_path.read_text(encoding="utf-8")
    assert "# Investigation Notes" in text
    assert "Run ID: verify_run" in text
    assert "Reviewer:" in text
    assert "## Observations" in text
    assert str(notes_path) in result.generated_files


def test_summary_template_generated(tmp_path: Path) -> None:
    store = _prepare_run(tmp_path, count=2)
    result = ManualVerificationPackageGenerator(store).generate(
        ManualVerificationRequest(run_id="verify_run", output_directory=tmp_path)
    )

    summary_path = tmp_path / "evidence_summary_template.md"
    assert summary_path.exists()
    text = summary_path.read_text(encoding="utf-8")
    assert "# Evidence Summary" in text
    assert "Run ID: verify_run" in text
    assert "Event Count: 2" in text
    assert "run_verify_run.json" in text
    assert "run_verify_run.md" in text
    assert "Generated Time:" in text
    assert "## Reviewer Notes" in text
    assert str(summary_path) in result.generated_files


def test_generated_files_populated(tmp_path: Path) -> None:
    store = _prepare_run(tmp_path)
    result = ManualVerificationPackageGenerator(store).generate(
        ManualVerificationRequest(run_id="verify_run", output_directory=tmp_path)
    )

    assert result.run_id == "verify_run"
    assert len(result.generated_files) == 3
    assert (tmp_path / "verification_checklist.md").exists()
    assert (tmp_path / "investigation_notes.md").exists()
    assert (tmp_path / "evidence_summary_template.md").exists()


def test_metadata_populated(tmp_path: Path) -> None:
    store = _prepare_run(tmp_path, count=4)
    result = ManualVerificationPackageGenerator(store).generate(
        ManualVerificationRequest(run_id="verify_run", output_directory=tmp_path)
    )

    assert result.package_metadata["event_count"] == 4
    assert len(result.package_metadata["evidence_files"]) == 2
    assert "generated_at" in result.package_metadata
    assert "checklist" in result.package_metadata
    assert "investigation_notes" in result.package_metadata
    assert "evidence_summary_template" in result.package_metadata
    assert result.generation_duration_ms >= 0.0


def test_output_paths_valid(tmp_path: Path) -> None:
    store = _prepare_run(tmp_path)
    result = ManualVerificationPackageGenerator(store).generate(
        ManualVerificationRequest(run_id="verify_run", output_directory=tmp_path)
    )

    for generated_path in result.generated_files:
        path = Path(generated_path)
        assert path.exists()
        assert path.is_file()
        assert path.stat().st_size > 0


def test_empty_event_store_supported(tmp_path: Path) -> None:
    run_id = "empty_run"
    store = EventStore(":memory:")
    store.open_run(run_id)
    EvidenceExporter(store).export(
        EvidenceExportRequest(run_id=run_id, output_directory=tmp_path)
    )

    result = ManualVerificationPackageGenerator(store).generate(
        ManualVerificationRequest(run_id=run_id, output_directory=tmp_path)
    )

    summary_text = (tmp_path / "evidence_summary_template.md").read_text(encoding="utf-8")
    assert "Event Count: 0" in summary_text
    assert result.package_metadata["event_count"] == 0
    assert len(result.generated_files) == 3
