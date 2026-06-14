"""RemoteEventCollector — download remote JSONL bundles and import via EventSyncBridge."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dsp.event_store import EventStore
from dsp.execution.webshell.event_sync.bundle_content import (
    JsonlContentValidation,
    validate_jsonl_content,
)
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

_DIAG_REMOTE_RAW = "downloaded_events.remote_path.raw"
_DIAG_CAT_RAW = "downloaded_events.cat.raw"
_DIAG_ERROR = "collection_error.txt"


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

        remote_raw = local_path.read_bytes()
        remote_validation = validate_jsonl_content(remote_raw)
        cat_raw: bytes | None = None
        cat_validation: JsonlContentValidation | None = None
        collection_source = "remote_path"
        bundle_bytes: bytes | None = None

        if remote_validation.valid:
            bundle_bytes = remote_raw
        else:
            cat_raw = provider.fetch_remote_file_via_cat(request.remote_bundle_path)
            cat_validation = validate_jsonl_content(cat_raw)
            if cat_validation.valid:
                bundle_bytes = cat_raw
                collection_source = "cat"
                local_path.write_bytes(cat_raw)

        if bundle_bytes is None:
            diagnostics_dir = self._write_collection_diagnostics(
                request,
                local_path,
                remote_raw=remote_raw,
                cat_raw=cat_raw,
                remote_validation=remote_validation,
                cat_validation=cat_validation,
            )
            raise RemoteEventCollectionError(
                self._format_collection_failure(
                    remote_validation,
                    cat_validation,
                ),
                diagnostics_dir=str(diagnostics_dir),
                remote_validation=remote_validation,
                cat_validation=cat_validation,
            )

        sync_result = self._event_sync_bridge.sync_bundle(local_path, event_store)
        import_duration_ms = (time.monotonic() - started) * 1000.0
        collection_metadata: dict[str, Any] = {
            "skipped_count": sync_result.skipped_count,
            "bundle_metadata": sync_result.bundle_metadata.to_dict(),
            "transfer_status": artifact.transfer_status,
            "transfer_metadata": dict(artifact.transfer_metadata),
            "collection_source": collection_source,
        }
        if not remote_validation.valid:
            collection_metadata["remote_path_validation"] = remote_validation.reason
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

    @staticmethod
    def _resolve_diagnostics_dir(
        request: RemoteEventCollectionRequest,
        local_path: Path,
    ) -> Path:
        if request.diagnostics_dir is not None:
            return Path(request.diagnostics_dir)
        return local_path.parent

    @classmethod
    def _write_collection_diagnostics(
        cls,
        request: RemoteEventCollectionRequest,
        local_path: Path,
        *,
        remote_raw: bytes,
        cat_raw: bytes | None,
        remote_validation: JsonlContentValidation,
        cat_validation: JsonlContentValidation | None,
    ) -> Path:
        diagnostics_dir = cls._resolve_diagnostics_dir(request, local_path)
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        (diagnostics_dir / _DIAG_REMOTE_RAW).write_bytes(remote_raw)
        if cat_raw is not None:
            (diagnostics_dir / _DIAG_CAT_RAW).write_bytes(cat_raw)
        error_text = cls._format_collection_failure(remote_validation, cat_validation)
        (diagnostics_dir / _DIAG_ERROR).write_text(error_text, encoding="utf-8")
        return diagnostics_dir

    @staticmethod
    def _format_collection_failure(
        remote_validation: JsonlContentValidation,
        cat_validation: JsonlContentValidation | None,
    ) -> str:
        lines = [
            "remote event bundle collection failed",
            f"remote_path: {remote_validation.reason}",
        ]
        if remote_validation.content_preview:
            lines.append(f"remote_path preview: {remote_validation.content_preview}")
        if cat_validation is None:
            lines.append("cat fallback: not attempted")
        else:
            lines.append(f"cat fallback: {cat_validation.reason}")
            if cat_validation.content_preview:
                lines.append(f"cat preview: {cat_validation.content_preview}")
        return "\n".join(lines)
