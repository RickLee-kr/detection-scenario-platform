"""Manual verification package generator."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from dsp.event_store.store import EventStore
from dsp.manual_verification.checklist import (
    CHECKLIST_FILENAME,
    generate_verification_checklist,
)
from dsp.manual_verification.evidence_templates import (
    EVIDENCE_SUMMARY_FILENAME,
    generate_evidence_summary_template,
)
from dsp.manual_verification.investigation_notes import (
    INVESTIGATION_NOTES_FILENAME,
    generate_investigation_notes,
)
from dsp.manual_verification.models import ManualVerificationRequest, ManualVerificationResult


class EvidenceExportFilesMissingError(FileNotFoundError):
    """Raised when required evidence export files are not present."""


class ManualVerificationPackageGenerator:
    """Generate human-review templates from existing evidence export outputs."""

    def __init__(self, store: EventStore) -> None:
        self.store = store

    def _evidence_export_paths(self, run_id: str, output_directory: Path) -> list[Path]:
        return [
            output_directory / f"run_{run_id}.json",
            output_directory / f"run_{run_id}.md",
        ]

    def _verify_evidence_export_files(self, run_id: str, output_directory: Path) -> list[Path]:
        evidence_paths = self._evidence_export_paths(run_id, output_directory)
        missing = [str(path) for path in evidence_paths if not path.is_file()]
        if missing:
            raise EvidenceExportFilesMissingError(
                f"Evidence export files missing for run {run_id!r}: {', '.join(missing)}"
            )
        return evidence_paths

    def generate(self, request: ManualVerificationRequest) -> ManualVerificationResult:
        start = time.perf_counter()
        output_dir = Path(request.output_directory)
        generated_at = datetime.now(timezone.utc)

        evidence_paths = self._verify_evidence_export_files(request.run_id, output_dir)
        events = self.store.list_events(request.run_id)
        evidence_files = [str(path) for path in evidence_paths]

        checklist_path = generate_verification_checklist(request.run_id, output_dir)
        notes_path = generate_investigation_notes(request.run_id, output_dir)
        summary_path = generate_evidence_summary_template(
            request.run_id,
            output_dir,
            event_count=len(events),
            evidence_files=evidence_files,
            generated_time=generated_at,
        )

        duration_ms = (time.perf_counter() - start) * 1000.0
        generated_files = [
            str(checklist_path),
            str(notes_path),
            str(summary_path),
        ]
        package_metadata = {
            "event_count": len(events),
            "evidence_files": evidence_files,
            "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
            "checklist": str(checklist_path),
            "investigation_notes": str(notes_path),
            "evidence_summary_template": str(summary_path),
            "template_files": [
                CHECKLIST_FILENAME,
                INVESTIGATION_NOTES_FILENAME,
                EVIDENCE_SUMMARY_FILENAME,
            ],
        }

        return ManualVerificationResult(
            run_id=request.run_id,
            generated_files=generated_files,
            package_metadata=package_metadata,
            generation_duration_ms=duration_ms,
        )
