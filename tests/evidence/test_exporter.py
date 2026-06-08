"""Evidence export unit tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from dsp.event_store import Event, EventStore
from dsp.evidence import EvidenceExportRequest, EvidenceExporter


def _event(**kwargs) -> Event:
    defaults = {
        "run_id": "export_run",
        "scenario_id": "dummy",
        "timestamp": datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc),
        "stage": "executor",
        "event": "synthetic_action",
        "status": "sent",
        "source": "dry_run",
    }
    defaults.update(kwargs)
    return Event(**defaults)


def _store_with_events(run_id: str = "export_run", count: int = 3) -> EventStore:
    store = EventStore(":memory:")
    store.open_run(run_id)
    for index in range(count):
        store.append(
            _event(
                timestamp=datetime(2026, 6, 6, 12, index, 0, tzinfo=timezone.utc),
                event=f"event_{index}",
                source="local" if index % 2 == 0 else "remote",
            )
        )
    return store


def test_json_export_created(tmp_path: Path) -> None:
    store = _store_with_events()
    exporter = EvidenceExporter(store)
    result = exporter.export(
        EvidenceExportRequest(run_id="export_run", output_directory=tmp_path)
    )

    json_path = tmp_path / "run_export_run.json"
    assert json_path.exists()
    assert str(json_path) in result.exported_files


def test_markdown_export_created(tmp_path: Path) -> None:
    store = _store_with_events()
    exporter = EvidenceExporter(store)
    result = exporter.export(
        EvidenceExportRequest(run_id="export_run", output_directory=tmp_path)
    )

    markdown_path = tmp_path / "run_export_run.md"
    assert markdown_path.exists()
    assert str(markdown_path) in result.exported_files


def test_empty_event_set_export(tmp_path: Path) -> None:
    store = EventStore(":memory:")
    store.open_run("empty_run")
    exporter = EvidenceExporter(store)
    result = exporter.export(
        EvidenceExportRequest(run_id="empty_run", output_directory=tmp_path)
    )

    json_path = tmp_path / "run_empty_run.json"
    markdown_path = tmp_path / "run_empty_run.md"
    assert json_path.exists()
    assert markdown_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "empty_run"
    assert payload["event_count"] == 0
    assert payload["events"] == []

    markdown_text = markdown_path.read_text(encoding="utf-8")
    assert "Total Events: 0" in markdown_text
    assert result.export_metadata["event_count"] == 0


def test_export_metadata_populated(tmp_path: Path) -> None:
    store = _store_with_events(count=2)
    exporter = EvidenceExporter(store)
    result = exporter.export(
        EvidenceExportRequest(run_id="export_run", output_directory=tmp_path)
    )

    assert result.run_id == "export_run"
    assert result.export_metadata["event_count"] == 2
    assert "json_export" in result.export_metadata
    assert "markdown_export" in result.export_metadata
    assert "exported_at" in result.export_metadata
    assert result.export_duration_ms >= 0.0


def test_event_count_matches_event_store(tmp_path: Path) -> None:
    store = _store_with_events(count=5)
    exporter = EvidenceExporter(store)
    result = exporter.export(
        EvidenceExportRequest(run_id="export_run", output_directory=tmp_path)
    )

    store_events = store.list_events("export_run")
    payload = json.loads((tmp_path / "run_export_run.json").read_text(encoding="utf-8"))

    assert len(store_events) == 5
    assert payload["event_count"] == 5
    assert len(payload["events"]) == 5
    assert result.export_metadata["event_count"] == 5


def test_output_paths_valid(tmp_path: Path) -> None:
    store = _store_with_events()
    exporter = EvidenceExporter(store)
    result = exporter.export(
        EvidenceExportRequest(run_id="export_run", output_directory=tmp_path)
    )

    for exported_path in result.exported_files:
        path = Path(exported_path)
        assert path.is_absolute() or path == tmp_path / path.name
        assert path.exists()
        assert path.is_file()
        assert path.stat().st_size > 0

    assert result.export_metadata["json_export"] == str(tmp_path / "run_export_run.json")
    assert result.export_metadata["markdown_export"] == str(tmp_path / "run_export_run.md")
