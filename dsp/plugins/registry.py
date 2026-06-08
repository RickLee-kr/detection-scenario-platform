"""In-memory plugin registry."""

from __future__ import annotations

from dsp.plugins.models import PluginRecord, PluginStatus


class PluginRegistry:
    def __init__(self) -> None:
        self._by_id: dict[str, PluginRecord] = {}
        self._ordered_ids: list[str] = []

    def register(self, record: PluginRecord) -> None:
        existing = self._by_id.get(record.id)
        if existing is not None:
            record.status = PluginStatus.CONFLICT
            record.status_reason = "duplicate_id"
            return
        self._by_id[record.id] = record
        self._ordered_ids.append(record.id)
        self._ordered_ids.sort()

    def get(self, plugin_id: str) -> PluginRecord | None:
        return self._by_id.get(plugin_id)

    def all(self) -> list[PluginRecord]:
        return [self._by_id[i] for i in self._ordered_ids if i in self._by_id]

    def active_ids(self) -> list[str]:
        return [r.id for r in self.all() if r.status == PluginStatus.ACTIVE]

    def reload(self) -> None:
        self._by_id.clear()
        self._ordered_ids.clear()
