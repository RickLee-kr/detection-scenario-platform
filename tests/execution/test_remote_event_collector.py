"""RemoteEventCollector tests — mocked providers only, no live network."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dsp import EVENT_SCHEMA_VERSION
from dsp.event_store import EventQuery, EventStore
from dsp.execution import LocalExecutionProvider, WebshellExecutionProvider
from dsp.execution.providers.runtime.command import CommandTransportError
from dsp.execution.providers.runtime.runtime_models import RuntimeArtifact
from dsp.execution.remote import (
    RemoteEventCollectionRequest,
    RemoteEventCollectionResult,
    RemoteEventCollector,
    UnsupportedRemoteProviderError,
)
from dsp.execution.webshell.event_sync import (
    BundleNotFoundError,
    BundleValidationError,
    EventSyncBridge,
    EventSyncResult,
)
from dsp.execution.webshell.event_sync.models import EventBundleMetadata
from dsp.execution.webshell_config import WebshellExecutionConfig
from tests.execution.webshell.event_sync.conftest import (
    RUN_ID,
    SCENARIO_ID,
    event_record,
    metadata_record,
    write_bundle,
)

FORBIDDEN_INFERENCE_TOKENS = (
    "execution_success",
    "attack_success",
    "detection",
    "alert",
    "correlation",
)


def _collection_request(
    *,
    remote_execution_id: str = "exec01",
    remote_bundle_path: str = "/tmp/dsp/exec01/events.jsonl",
    local_bundle_path: str | Path | None = None,
) -> RemoteEventCollectionRequest:
    return RemoteEventCollectionRequest(
        remote_execution_id=remote_execution_id,
        remote_bundle_path=remote_bundle_path,
        local_bundle_path=local_bundle_path,
    )


def _open_store(run_id: str = RUN_ID) -> EventStore:
    store = EventStore(":memory:")
    store.open_run(run_id)
    return store


def _mock_webshell_provider(
    *,
    download_return: RuntimeArtifact | None = None,
    download_side_effect=None,
) -> MagicMock:
    provider = MagicMock(spec=WebshellExecutionProvider)
    provider.provider_type = "webshell"
    if download_side_effect is not None:
        provider.download_file.side_effect = download_side_effect
    else:
        provider.download_file.return_value = download_return
    return provider


def _artifact_for_path(
    remote_path: str,
    local_path: Path,
    *,
    transfer_status: str = "downloaded",
) -> RuntimeArtifact:
    return RuntimeArtifact.new(
        remote_path=remote_path,
        local_path=str(local_path),
        transfer_status=transfer_status,
        transfer_metadata={"transport_status": 200, "delivery_only": True},
    )


# --- Request / result models ---


def test_collection_request_round_trip():
    request = _collection_request(local_bundle_path="/tmp/events.jsonl")
    restored = RemoteEventCollectionRequest.from_dict(request.to_dict())
    assert restored.remote_execution_id == "exec01"
    assert restored.remote_bundle_path == "/tmp/dsp/exec01/events.jsonl"
    assert restored.local_bundle_path == "/tmp/events.jsonl"


def test_collection_result_round_trip():
    result = RemoteEventCollectionResult(
        remote_execution_id="exec01",
        remote_bundle_path="/tmp/dsp/exec01/events.jsonl",
        local_bundle_path="/tmp/local/events.jsonl",
        events_imported=3,
        collection_metadata={"skipped_count": 0},
        import_duration_ms=12.5,
    )
    restored = RemoteEventCollectionResult.from_dict(result.to_dict())
    assert restored.events_imported == 3
    assert restored.import_duration_ms == 12.5


def test_collection_result_to_dict_has_required_fields():
    result = RemoteEventCollectionResult(
        remote_execution_id="exec01",
        remote_bundle_path="/remote/events.jsonl",
        local_bundle_path="/local/events.jsonl",
        events_imported=1,
    )
    payload = result.to_dict()
    assert payload["remote_execution_id"] == "exec01"
    assert payload["remote_bundle_path"] == "/remote/events.jsonl"
    assert payload["local_bundle_path"] == "/local/events.jsonl"
    assert payload["events_imported"] == 1


# --- Unsupported provider ---


def test_unsupported_provider_rejected():
    collector = RemoteEventCollector()
    with pytest.raises(UnsupportedRemoteProviderError, match="local"):
        collector.collect(
            _collection_request(),
            LocalExecutionProvider(),  # type: ignore[arg-type]
            _open_store(),
        )


def test_unsupported_mock_provider_rejected():
    collector = RemoteEventCollector()
    provider = MagicMock()
    provider.provider_type = "agent"
    with pytest.raises(UnsupportedRemoteProviderError, match="agent"):
        collector.collect(_collection_request(), provider, _open_store())


# --- Download invocation ---


def test_download_file_invoked_with_remote_bundle_path(tmp_path: Path):
    local = tmp_path / "events.jsonl"
    write_bundle(local, [event_record()])
    provider = _mock_webshell_provider(
        download_return=_artifact_for_path("/tmp/dsp/exec01/events.jsonl", local),
    )
    collector = RemoteEventCollector(event_sync_bridge=MagicMock())
    collector.collect(
        _collection_request(remote_bundle_path="/tmp/dsp/exec01/events.jsonl"),
        provider,
        _open_store(),
    )
    provider.download_file.assert_called_once_with("/tmp/dsp/exec01/events.jsonl")


def test_remote_execution_id_propagated_to_result(tmp_path: Path):
    local = tmp_path / "exec99.jsonl"
    write_bundle(local, [event_record()])
    provider = _mock_webshell_provider(
        download_return=_artifact_for_path("/remote/events.jsonl", local),
    )
    bridge = MagicMock()
    bridge.sync_bundle.return_value = EventSyncResult(
        imported_count=0,
        skipped_count=0,
        bundle_metadata=_bundle_metadata(),
    )
    result = RemoteEventCollector(event_sync_bridge=bridge).collect(
        _collection_request(remote_execution_id="exec99"),
        provider,
        _open_store(),
    )
    assert result.remote_execution_id == "exec99"


def test_remote_bundle_path_propagated_to_result(tmp_path: Path):
    local = tmp_path / "bundle.jsonl"
    write_bundle(local, [event_record()])
    provider = _mock_webshell_provider(
        download_return=_artifact_for_path("/remote/custom/events.jsonl", local),
    )
    bridge = MagicMock()
    bridge.sync_bundle.return_value = EventSyncResult(
        imported_count=0,
        skipped_count=0,
        bundle_metadata=_bundle_metadata(),
    )
    result = RemoteEventCollector(event_sync_bridge=bridge).collect(
        _collection_request(remote_bundle_path="/remote/custom/events.jsonl"),
        provider,
        _open_store(),
    )
    assert result.remote_bundle_path == "/remote/custom/events.jsonl"


def test_local_bundle_path_from_request(tmp_path: Path):
    bundle_path = tmp_path / "request-path.jsonl"
    write_bundle(bundle_path, [event_record()])
    provider = _mock_webshell_provider(
        download_return=_artifact_for_path("/remote/events.jsonl", Path("/unused")),
    )
    result = RemoteEventCollector().collect(
        _collection_request(local_bundle_path=bundle_path),
        provider,
        _open_store(),
    )
    assert result.local_bundle_path == str(bundle_path)


def test_local_bundle_path_from_artifact_when_request_unset(tmp_path: Path):
    bundle_path = tmp_path / "artifact-path.jsonl"
    write_bundle(bundle_path, [event_record()])
    provider = _mock_webshell_provider(
        download_return=_artifact_for_path("/remote/events.jsonl", bundle_path),
    )
    result = RemoteEventCollector().collect(
        _collection_request(),
        provider,
        _open_store(),
    )
    assert result.local_bundle_path == str(bundle_path)


# --- Missing bundle ---


def test_missing_bundle_raises_bundle_not_found(tmp_path: Path):
    provider = _mock_webshell_provider(
        download_return=_artifact_for_path(
            "/remote/events.jsonl",
            tmp_path / "does-not-exist" / "events.jsonl",
        ),
    )
    with pytest.raises(BundleNotFoundError, match="downloaded bundle not found"):
        RemoteEventCollector(event_sync_bridge=MagicMock()).collect(
            _collection_request(),
            provider,
            _open_store(),
        )


def test_missing_local_bundle_path_after_download_raises():
    provider = _mock_webshell_provider(
        download_return=RuntimeArtifact.new(
            remote_path="/remote/events.jsonl",
            transfer_status="downloaded",
        ),
    )
    from dsp.execution.remote.exceptions import RemoteEventCollectionError

    with pytest.raises(RemoteEventCollectionError, match="local bundle path could not be resolved"):
        RemoteEventCollector(event_sync_bridge=MagicMock()).collect(
            _collection_request(),
            provider,
            _open_store(),
        )


# --- EventSyncBridge invocation ---


def _bundle_metadata(*, event_count: int = 1) -> EventBundleMetadata:
    from datetime import datetime, timezone

    return EventBundleMetadata(
        run_id=RUN_ID,
        scenario_id=SCENARIO_ID,
        scenario_version="1.0.0",
        generated_at=datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc),
        event_count=event_count,
        schema_version=EVENT_SCHEMA_VERSION,
    )


def test_event_sync_bridge_invoked_with_local_bundle_path(tmp_path: Path):
    bundle_path = tmp_path / "events.jsonl"
    write_bundle(bundle_path, [event_record()])
    provider = _mock_webshell_provider(
        download_return=_artifact_for_path("/remote/events.jsonl", bundle_path),
    )
    bridge = MagicMock()
    bridge.sync_bundle.return_value = EventSyncResult(
        imported_count=1,
        skipped_count=0,
        bundle_metadata=_bundle_metadata(),
    )
    RemoteEventCollector(event_sync_bridge=bridge).collect(
        _collection_request(),
        provider,
        _open_store(),
    )
    bridge.sync_bundle.assert_called_once()
    called_path, called_store = bridge.sync_bundle.call_args.args
    assert str(called_path) == str(bundle_path)
    assert called_store.run_id == RUN_ID


def test_event_store_import_path_reuses_sync_bridge(tmp_path: Path):
    bundle_path = tmp_path / "events.jsonl"
    events = [event_record(), event_record(event="dns_tunnel_query_sent", status="sent")]
    write_bundle(bundle_path, events)
    provider = _mock_webshell_provider(
        download_return=_artifact_for_path("/remote/events.jsonl", bundle_path),
    )
    store = _open_store()
    result = RemoteEventCollector().collect(
        _collection_request(),
        provider,
        store,
    )
    assert result.events_imported == 2
    assert store.count(EventQuery(run_id=RUN_ID, scenario_id=SCENARIO_ID)) == 2


def test_imported_event_count_propagated(tmp_path: Path):
    bundle_path = tmp_path / "events.jsonl"
    write_bundle(bundle_path, [event_record(), event_record(event="step_two")])
    provider = _mock_webshell_provider(
        download_return=_artifact_for_path("/remote/events.jsonl", bundle_path),
    )
    result = RemoteEventCollector().collect(
        _collection_request(),
        provider,
        _open_store(),
    )
    assert result.events_imported == 2
    assert result.collection_metadata["skipped_count"] == 0


def test_collection_metadata_includes_transfer_metadata(tmp_path: Path):
    bundle_path = tmp_path / "events.jsonl"
    write_bundle(bundle_path, [event_record()])
    artifact = _artifact_for_path("/remote/events.jsonl", bundle_path)
    artifact.transfer_metadata["transport_method"] = "download"
    provider = _mock_webshell_provider(download_return=artifact)
    result = RemoteEventCollector().collect(
        _collection_request(),
        provider,
        _open_store(),
    )
    assert result.collection_metadata["transfer_status"] == "downloaded"
    assert result.collection_metadata["transfer_metadata"]["transport_status"] == 200


def test_collection_metadata_includes_bundle_metadata(tmp_path: Path):
    bundle_path = tmp_path / "events.jsonl"
    write_bundle(bundle_path, [event_record()])
    provider = _mock_webshell_provider(
        download_return=_artifact_for_path("/remote/events.jsonl", bundle_path),
    )
    result = RemoteEventCollector().collect(
        _collection_request(),
        provider,
        _open_store(),
    )
    bundle_meta = result.collection_metadata["bundle_metadata"]
    assert bundle_meta["run_id"] == RUN_ID
    assert bundle_meta["scenario_id"] == SCENARIO_ID


def test_import_duration_ms_recorded(tmp_path: Path):
    bundle_path = tmp_path / "events.jsonl"
    write_bundle(bundle_path, [event_record()])
    provider = _mock_webshell_provider(
        download_return=_artifact_for_path("/remote/events.jsonl", bundle_path),
    )
    result = RemoteEventCollector().collect(
        _collection_request(),
        provider,
        _open_store(),
    )
    assert result.import_duration_ms is not None
    assert result.import_duration_ms >= 0


# --- Error handling ---


def test_download_error_propagates():
    provider = _mock_webshell_provider(
        download_side_effect=CommandTransportError(
            "download_file transport failed",
            command_id="dl01",
        ),
    )
    with pytest.raises(CommandTransportError, match="transport failed"):
        RemoteEventCollector(event_sync_bridge=MagicMock()).collect(
            _collection_request(),
            provider,
            _open_store(),
        )


def test_sync_validation_error_propagates(tmp_path: Path):
    bundle_path = tmp_path / "bad.jsonl"
    bundle_path.write_text("{not-json}\n", encoding="utf-8")
    provider = _mock_webshell_provider(
        download_return=_artifact_for_path("/remote/events.jsonl", bundle_path),
    )
    with pytest.raises(BundleValidationError):
        RemoteEventCollector().collect(
            _collection_request(),
            provider,
            _open_store(),
        )


def test_sync_run_id_mismatch_propagates(tmp_path: Path):
    bundle_path = tmp_path / "events.jsonl"
    lines = [
        json.dumps(
            {
                "_bundle_metadata": True,
                "run_id": "other_run",
                "scenario_id": SCENARIO_ID,
                "scenario_version": "1.0.0",
                "generated_at": "2026-06-06T12:00:00Z",
                "event_count": 1,
                "schema_version": EVENT_SCHEMA_VERSION,
            }
        ),
        json.dumps(event_record()),
    ]
    bundle_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    provider = _mock_webshell_provider(
        download_return=_artifact_for_path("/remote/events.jsonl", bundle_path),
    )
    with pytest.raises(BundleValidationError, match="run_id"):
        RemoteEventCollector().collect(
            _collection_request(),
            provider,
            _open_store(),
        )


# --- No inference / grep guards ---


def test_collector_source_has_no_stdout_stderr_grep():
    source = inspect.getsource(RemoteEventCollector.collect)
    for token in ("grep", "stdout", "stderr", "parsed_output"):
        assert token not in source


def test_collector_source_has_no_success_inference():
    source = inspect.getsource(RemoteEventCollector).lower()
    for token in FORBIDDEN_INFERENCE_TOKENS:
        assert token not in source


def test_result_model_has_no_forbidden_outcome_fields():
    source = inspect.getsource(RemoteEventCollectionResult)
    for field_name in ("success", "failed", "detected", "attack_success", "alert_created"):
        assert f"{field_name}:" not in source


def test_collector_does_not_reference_validation_or_reporting():
    source = inspect.getsource(RemoteEventCollector.collect)
    assert "ValidationEngine" not in source
    assert "ReportingEngine" not in source


# --- End-to-end with mocked bridge + provider ---


@pytest.mark.parametrize("family", ["jsp", "php", "aspx"])
def test_family_agnostic_collection_with_mock_provider(family: str, tmp_path: Path):
    bundle_path = tmp_path / f"{family}_events.jsonl"
    write_bundle(bundle_path, [event_record(source="remote")])
    provider = _mock_webshell_provider(
        download_return=_artifact_for_path(
            f"/tmp/dsp/{family}/events.jsonl",
            bundle_path,
        ),
    )
    result = RemoteEventCollector().collect(
        _collection_request(
            remote_execution_id=f"{family}_exec",
            remote_bundle_path=f"/tmp/dsp/{family}/events.jsonl",
        ),
        provider,
        _open_store(),
    )
    assert result.events_imported == 1
    assert result.remote_execution_id == f"{family}_exec"


def test_empty_bundle_imports_zero_events(tmp_path: Path):
    bundle_path = tmp_path / "empty.jsonl"
    write_bundle(bundle_path, [])
    provider = _mock_webshell_provider(
        download_return=_artifact_for_path("/remote/empty.jsonl", bundle_path),
    )
    result = RemoteEventCollector().collect(
        _collection_request(),
        provider,
        _open_store(),
    )
    assert result.events_imported == 0


def test_collector_uses_injected_event_sync_bridge(tmp_path: Path):
    bundle_path = tmp_path / "events.jsonl"
    write_bundle(bundle_path, [event_record()])
    provider = _mock_webshell_provider(
        download_return=_artifact_for_path("/remote/events.jsonl", bundle_path),
    )
    bridge = MagicMock()
    bridge.sync_bundle.return_value = EventSyncResult(
        imported_count=5,
        skipped_count=2,
        bundle_metadata=_bundle_metadata(event_count=5),
    )
    result = RemoteEventCollector(event_sync_bridge=bridge).collect(
        _collection_request(),
        provider,
        _open_store(),
    )
    assert result.events_imported == 5
    assert result.collection_metadata["skipped_count"] == 2


def test_default_collector_uses_event_sync_bridge_implementation(tmp_path: Path):
    bundle_path = tmp_path / "events.jsonl"
    write_bundle(bundle_path, [event_record()])
    provider = _mock_webshell_provider(
        download_return=_artifact_for_path("/remote/events.jsonl", bundle_path),
    )
    collector = RemoteEventCollector()
    assert isinstance(collector._event_sync_bridge, EventSyncBridge)
    result = collector.collect(_collection_request(), provider, _open_store())
    assert result.events_imported == 1


def test_webshell_provider_config_unchanged_for_collection():
    config = WebshellExecutionConfig(
        provider_type="jsp",
        webshell_url="https://lab.example/shell.jsp",
    )
    provider = WebshellExecutionProvider(config)
    assert provider.webshell_family == "jsp"


def test_remote_scenario_runner_still_independent():
    from dsp.execution.remote import RemoteScenarioRunner, ScenarioExecutionRequest

    source = inspect.getsource(RemoteScenarioRunner.run)
    assert "RemoteEventCollector" not in source
    assert "EventSyncBridge" not in source


def test_collection_request_requires_remote_execution_id():
    with pytest.raises(TypeError):
        RemoteEventCollectionRequest(remote_bundle_path="/x/events.jsonl")  # type: ignore[call-arg]


def test_duplicate_events_skipped_count_in_metadata(tmp_path: Path):
    duplicate = event_record()
    bundle_path = tmp_path / "dup.jsonl"
    write_bundle(bundle_path, [duplicate, duplicate.copy()])
    provider = _mock_webshell_provider(
        download_return=_artifact_for_path("/remote/dup.jsonl", bundle_path),
    )
    result = RemoteEventCollector().collect(
        _collection_request(),
        provider,
        _open_store(),
    )
    assert result.events_imported == 1
    assert result.collection_metadata["skipped_count"] == 1
