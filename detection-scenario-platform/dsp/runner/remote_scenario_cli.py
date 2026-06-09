"""Remote scenario execution CLI — runs on the webshell target host."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from dsp.engine import RunConfig, RunContext, resolve_targets
from dsp.engine.orchestrator import run_scenario
from dsp.event_store import EventStore
from dsp.execution.remote.models import ScenarioExecutionRequest
from dsp.execution.remote.payload import decode_scenario_payload
from dsp.execution.remote.paths import resolve_remote_bundle_path
from dsp.execution.webshell.event_sync.bundle_export import write_jsonl_bundle
from dsp.plugins import PluginLoader, PluginStatus


def resolve_bundle_output_path(request: ScenarioExecutionRequest) -> Path:
    metadata = request.execution_metadata
    explicit = metadata.get("remote_bundle_path")
    if explicit:
        return Path(str(explicit))
    work_dir = metadata.get("remote_work_dir")
    if not work_dir:
        raise ValueError(
            "execution_metadata must include remote_bundle_path or remote_work_dir"
        )
    if not request.run_id:
        raise ValueError("run_id is required to derive remote bundle path")
    return Path(resolve_remote_bundle_path(str(work_dir), request.run_id))


def execute_remote_scenario(request: ScenarioExecutionRequest) -> dict[str, Any]:
    """Run one scenario locally on the remote host and write an event bundle."""
    if not request.run_id:
        raise ValueError("run_id is required")
    if not request.target_net:
        raise ValueError("target_net is required")

    bundle_path = resolve_bundle_output_path(request)
    loader = PluginLoader()
    registry = loader.discover_and_load()
    record = registry.get(request.scenario_id)
    if record is None or record.status == PluginStatus.DISABLED or not record.is_runnable:
        raise ValueError(f"scenario not runnable: {request.scenario_id!r}")

    temp_dir = Path(tempfile.mkdtemp(prefix="dsp-remote-"))
    db_path = temp_dir / "events.db"
    store = EventStore(db_path)
    store.open_run(request.run_id)

    scenario_params = {request.scenario_id: dict(request.scenario_params)}
    config = RunConfig(
        target_net=request.target_net,
        dry_run=request.dry_run,
        scenario_params=scenario_params,
    )
    ctx = RunContext(
        run_id=request.run_id,
        target_net=request.target_net,
        event_store=store,
        config=config,
        dry_run=request.dry_run,
    )
    targets = resolve_targets(request.target_net)

    try:
        summary = run_scenario(record, ctx, targets)
        write_jsonl_bundle(
            store,
            bundle_path,
            run_id=request.run_id,
            scenario_id=request.scenario_id,
            scenario_version=record.manifest.version,
        )
    finally:
        store.close()

    result: dict[str, Any] = {
        "scenario_id": request.scenario_id,
        "run_id": request.run_id,
        "bundle_path": str(bundle_path),
        "exit_code": 0,
    }
    if summary is not None:
        result["summary"] = {
            "scenario_id": summary.scenario_id,
            "metrics": dict(summary.metrics),
            "event_count": summary.event_count,
            "notes": list(summary.notes),
        }
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(
            "usage: dsp-remote-scenario '<json-payload>'",
            file=sys.stderr,
        )
        return 2

    try:
        payload = decode_scenario_payload(args[0])
        request = ScenarioExecutionRequest.from_dict(payload)
        result = execute_remote_scenario(request)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "exit_code": 1}), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"error": str(exc), "exit_code": 1}), file=sys.stderr)
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
