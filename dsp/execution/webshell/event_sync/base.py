"""EventSyncBridge interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from dsp.event_store import EventStore
from dsp.execution.webshell.event_sync.models import EventSyncResult


class EventSyncBridgeBase(ABC):
    """Contract for importing remote event bundles into Event Store."""

    @abstractmethod
    def sync_bundle(
        self,
        bundle_path: str | Path,
        event_store: EventStore,
    ) -> EventSyncResult:
        """Load, validate, and append bundle events into Event Store."""
