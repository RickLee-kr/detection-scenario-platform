"""Tests for raw JSONL bundle content validation."""

from __future__ import annotations

import json

import pytest

from dsp import EVENT_SCHEMA_VERSION
from dsp.execution.webshell.event_sync.bundle_content import validate_jsonl_content
from tests.execution.webshell.event_sync.conftest import (
    RUN_ID,
    SCENARIO_ID,
    event_record,
    metadata_record,
)


def _valid_jsonl(*, events: list[dict] | None = None) -> bytes:
    event_rows = events if events is not None else [event_record()]
    lines = [json.dumps(metadata_record(event_count=len(event_rows)))]
    lines.extend(json.dumps(event) for event in event_rows)
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_validate_accepts_valid_jsonl():
    result = validate_jsonl_content(_valid_jsonl())
    assert result.valid is True
    assert result.reason is None


@pytest.mark.parametrize(
    ("content", "reason_fragment"),
    [
        (b"", "empty response"),
        (b"   \n", "empty response"),
        (b"<html><body>jsp shell</body></html>", "HTML response"),
        (b"ready", "webshell banner"),
        (b"cat: /tmp/x/events.jsonl: No such file or directory", "cat: file not found"),
        (b'{"not": "closed"\n', "malformed JSON"),
        (b"42\n", "first non-empty line"),
    ],
)
def test_validate_rejects_invalid_content(content: bytes, reason_fragment: str):
    result = validate_jsonl_content(content)
    assert result.valid is False
    assert result.reason is not None
    assert reason_fragment in result.reason
    assert result.content_preview is not None


def test_validate_rejects_flask_wrapper():
    content = b"<!doctype html><title>werkzeug.debughelpers</title>"
    result = validate_jsonl_content(content)
    assert result.valid is False
    assert result.reason in {"HTML response", "Flask debug wrapper"}
    assert "werkzeug" in (result.content_preview or "")


def test_validate_includes_content_preview_on_malformed_json():
    result = validate_jsonl_content(b"{broken")
    assert result.valid is False
    assert result.content_preview is not None
    assert "{broken" in result.content_preview
