"""JSONL bundle loader — parse only, no Event Store writes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dsp.execution.webshell.event_sync.bundle_content import content_preview
from dsp.execution.webshell.event_sync.exceptions import (
    BundleNotFoundError,
    BundleValidationError,
)
from dsp.execution.webshell.event_sync.models import EventBundle, EventBundleMetadata

BUNDLE_METADATA_MARKER = "_bundle_metadata"
REQUIRED_METADATA_FIELDS = frozenset(
    {
        "run_id",
        "scenario_id",
        "scenario_version",
        "generated_at",
        "event_count",
        "schema_version",
    }
)


def load_jsonl_bundle(bundle_path: str | Path) -> EventBundle:
    """Open a JSONL bundle, parse lines, and construct an EventBundle.

    Format:
        Line 1 — metadata record with ``_bundle_metadata: true``
        Lines 2+ — one Event JSON object per line

    Does not write to Event Store or modify event payloads.
    """
    path = Path(bundle_path)
    if not path.is_file():
        raise BundleNotFoundError(f"bundle not found: {path}", path=str(path))

    metadata: EventBundleMetadata | None = None
    events: list[dict[str, Any]] = []

    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                preview = content_preview(raw_line.encode("utf-8"))
                raise BundleValidationError(
                    f"malformed JSON at line {line_number}: {exc.msg}; "
                    f"content preview: {preview}",
                    rule="malformed_json",
                    line_number=line_number,
                ) from exc
            if not isinstance(record, dict):
                raise BundleValidationError(
                    f"expected JSON object at line {line_number}",
                    rule="invalid_record_type",
                    line_number=line_number,
                )
            if record.get(BUNDLE_METADATA_MARKER) is True:
                if metadata is not None:
                    raise BundleValidationError(
                        "duplicate bundle metadata record",
                        rule="duplicate_metadata",
                        line_number=line_number,
                    )
                metadata = _parse_metadata_record(record, line_number=line_number)
                continue
            events.append(record)

    if metadata is None:
        raise BundleValidationError("bundle metadata missing", rule="missing_metadata")

    return EventBundle(metadata=metadata, events=events)


def _parse_metadata_record(
    record: dict[str, Any],
    *,
    line_number: int,
) -> EventBundleMetadata:
    missing = REQUIRED_METADATA_FIELDS - set(record.keys())
    if missing:
        raise BundleValidationError(
            f"metadata missing fields: {sorted(missing)}",
            rule="missing_metadata_fields",
            line_number=line_number,
        )
    try:
        return EventBundleMetadata.from_dict(record)
    except (KeyError, TypeError, ValueError) as exc:
        raise BundleValidationError(
            f"invalid metadata at line {line_number}: {exc}",
            rule="invalid_metadata",
            line_number=line_number,
        ) from exc
