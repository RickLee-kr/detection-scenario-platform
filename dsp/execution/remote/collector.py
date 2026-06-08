"""RemoteEventCollector — download remote JSONL bundles and import via EventSyncBridge."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dsp.event_store import EventStore
from dsp.execution.remote.collection_models import (
    RemoteEventCollectionRequest,
    RemoteEventCollectionResult,
)
from dsp.execution.remote.exceptions import (
    RemoteEventCollectionError,
    UnsupportedRemoteProviderError,
)
from dsp.execution.webshell.event_sync.base import EventSyncBridgeBase
from dsp.execution.webshell.event_sync.bridge import EventSyncBridge
from dsp.execution.webshell.event_sync.exceptions import BundleNotFoundError

if TYPE_CHECKING:
    from dsp.execution.webshell_provider import WebshellExecutionProvider


class RemoteEventCollector:
    """Download a remote event bundle and import it into Event Store.

    Uses WebshellExecutionProvider.download_file() for transport delivery and
    EventSyncBridge.sync_bundle() for append-only Event Store import.
    """

    def __init__(
        self,
        *,
        event_sync_bridge: EventSyncBridgeBase | None = None,
    ) -> None:
        self._event_sync_bridge = event_sync_bridge or EventSyncBridge()

    def collect(
        self,
        request: RemoteEventCollectionRequest,
        provider: WebshellExecutionProvider,
        event_store: EventStore,
    ) -> RemoteEventCollectionResult:
        """Download a remote bundle and import its events into Event Store."""
        self._validate_provider(provider)
        started = time.monotonic()
        artifact = provider.download_file(request.remote_bundle_path)
        local_path = self._resolve_local_bundle_path(request, artifact.local_path)
        if not local_path.is_file():
            raise BundleNotFoundError(
                f"downloaded bundle not found at {local_path}",
                path=str(local_path),
            )
        sync_result = self._event_sync_bridge.sync_bundle(local_path, event_store)
        import_duration_ms = (time.monotonic() - started) * 1000.0
        collection_metadata: dict[str, Any] = {
            "skipped_count": sync_result.skipped_count,
            "bundle_metadata": sync_result.bundle_metadata.to_dict(),
            "transfer_status": artifact.transfer_status,
            "transfer_metadata": dict(artifact.transfer_metadata),
        }
        return RemoteEventCollectionResult(
            remote_execution_id=request.remote_execution_id,
            remote_bundle_path=request.remote_bundle_path,
            local_bundle_path=str(local_path),
            events_imported=sync_result.imported_count,
            collection_metadata=collection_metadata,
            import_duration_ms=import_duration_ms,
        )

    @staticmethod
    def _validate_provider(provider: object) -> None:
        from dsp.execution.webshell_provider import WebshellExecutionProvider

        if not isinstance(provider, WebshellExecutionProvider):
            provider_type = getattr(provider, "provider_type", type(provider).__name__)
            raise UnsupportedRemoteProviderError(str(provider_type))

    @staticmethod
    def _resolve_local_bundle_path(
        request: RemoteEventCollectionRequest,
        artifact_local_path: str,
    ) -> Path:
        if request.local_bundle_path is not None:
            return Path(request.local_bundle_path)
        if artifact_local_path:
            return Path(artifact_local_path)
        raise RemoteEventCollectionError(
            "local bundle path could not be resolved after download"
        )
