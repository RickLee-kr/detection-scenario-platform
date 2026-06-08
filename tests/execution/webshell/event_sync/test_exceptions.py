"""Event sync exception hierarchy tests."""

from __future__ import annotations

from dsp.execution.webshell.event_sync import (
    BundleNotFoundError,
    BundleSchemaError,
    BundleValidationError,
    EventImportError,
    EventSyncError,
)


def test_exception_hierarchy():
    assert issubclass(BundleNotFoundError, EventSyncError)
    assert issubclass(BundleValidationError, EventSyncError)
    assert issubclass(BundleSchemaError, EventSyncError)
    assert issubclass(EventImportError, EventSyncError)


def test_exception_context_attributes():
    not_found = BundleNotFoundError("missing", path="/tmp/x.jsonl")
    assert not_found.path == "/tmp/x.jsonl"

    validation = BundleValidationError("bad", rule="event_count", line_number=3)
    assert validation.rule == "event_count"
    assert validation.line_number == 3

    schema = BundleSchemaError("mismatch", schema_version="0.1", expected="1.0.0")
    assert schema.schema_version == "0.1"
    assert schema.expected == "1.0.0"

    import_err = EventImportError("failed", line_number=5, event_name="dns_tunnel_started")
    assert import_err.event_name == "dns_tunnel_started"
