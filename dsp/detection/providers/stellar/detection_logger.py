"""Structured detection observability — never logs API tokens."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SECRET_SUBSTRINGS = frozenset({"token", "secret", "password", "authorization", "api_key", "apikey"})


def _redact_value(key: str, value: Any) -> Any:
    key_lower = key.lower()
    if any(part in key_lower for part in _SECRET_SUBSTRINGS):
        return "***REDACTED***"
    if isinstance(value, dict):
        return {k: _redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value]
    if isinstance(value, str) and any(part in value.lower() for part in _SECRET_SUBSTRINGS):
        return "***REDACTED***"
    return value


class DetectionLogger:
    """Append-only JSON-lines logger for S3 detection observability."""

    def __init__(self, log_path: Path | None = None) -> None:
        self._path = log_path
        self._entries: list[dict[str, Any]] = []

    @property
    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)

    def log(
        self,
        event: str,
        *,
        run_id: str | None = None,
        scenario_id: str | None = None,
        **fields: Any,
    ) -> None:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "event": event,
        }
        if run_id:
            payload["run_id"] = run_id
        if scenario_id:
            payload["scenario_id"] = scenario_id
        for key, value in fields.items():
            payload[key] = _redact_value(key, value)
        self._entries.append(payload)
        if self._path is not None:
            self._append_to_file(payload)

    def _append_to_file(self, payload: dict[str, Any]) -> None:
        assert self._path is not None
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, default=str) + "\n")

    def set_log_path(self, log_path: Path) -> None:
        self._path = log_path

    def flush(self) -> None:
        """Rewrite full log file from buffered entries (used when path set late)."""
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(entry, default=str) for entry in self._entries]
        self._path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
