"""Evidence exporter — packages Event Store data for human review."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from dsp.event_store.store import EventStore
from dsp.evidence.json_exporter import export_run_json
from dsp.evidence.markdown_exporter import export_run_markdown
from dsp.evidence.models import EvidenceExportRequest, EvidenceExportResult


class EvidenceExporter:
    """Read Event Store events and write JSON + Markdown evidence files."""

    def __init__(self, store: EventStore) -> None:
        self.store = store

    def export(self, request: EvidenceExportRequest) -> EvidenceExportResult:
        start = time.perf_counter()
        output_dir = Path(request.output_directory)
        events = self.store.list_events(request.run_id)

        json_path = export_run_json(events, request.run_id, output_dir)
        markdown_path = export_run_markdown(events, request.run_id, output_dir)

        duration_ms = (time.perf_counter() - start) * 1000.0
        exported_files = [str(json_path), str(markdown_path)]
        export_metadata = {
            "event_count": len(events),
            "json_export": str(json_path),
            "markdown_export": str(markdown_path),
            "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        return EvidenceExportResult(
            run_id=request.run_id,
            exported_files=exported_files,
            export_metadata=export_metadata,
            export_duration_ms=duration_ms,
        )
