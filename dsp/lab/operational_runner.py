"""DSP operational lab runner — host direct and webshell remote traffic execution.

Generates traffic, collects events, exports evidence, and produces manual
verification templates. Does not validate detections, alerts, or attack success.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from dsp.event_store import EventQuery, EventStore
from dsp.evidence import EvidenceExportRequest, EvidenceExporter
from dsp.execution import ExecutionContext, create_execution_provider
from dsp.execution.providers.runtime.command.command_models import CommandRequest
from dsp.execution.remote import RemoteEventCollectionRequest, RemoteEventCollector
from dsp.execution.remote.models import ScenarioExecutionRequest
from dsp.execution.remote.runner import RemoteScenarioRunner
from dsp.manual_verification import (
    ManualVerificationPackageGenerator,
    ManualVerificationRequest,
)
from dsp.runner.run_manager import RunManager
from dsp.runtime.traffic_profiles import (
    build_scenario_params,
    parse_traffic_profile,
    profile_for_scenario,
)

SUPPORTED_MODES = frozenset({"local", "webshell"})
SUPPORTED_WEBSHELL_FAMILIES = frozenset({"jsp", "php", "aspx"})
DEFAULT_HARMLESS_COMMANDS = ("whoami", "hostname", "pwd")
ALLOWED_HARMLESS_COMMANDS = frozenset(DEFAULT_HARMLESS_COMMANDS)
DEFAULT_TARGET_NET = "10.10.10.0/24"
DEFAULT_SCENARIO = "dummy"
DEFAULT_TRAFFIC_PROFILE = "balanced"
DEFAULT_REMOTE_WORK_DIR = "/tmp/dsp"


@dataclass
class LabRunResult:
    """Paths and metadata produced by an operational lab run."""

    mode: str
    scenario: str
    traffic_profile: str
    run_id: str
    output_dir: Path
    run_dir: Path
    event_count: int
    generated_files: list[Path] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


def _generate_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"dsp_lab_{stamp}"


def _parse_harmless_commands(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return DEFAULT_HARMLESS_COMMANDS
    commands = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not commands:
        raise ValueError("at least one webshell command is required")
    disallowed = [cmd for cmd in commands if cmd not in ALLOWED_HARMLESS_COMMANDS]
    if disallowed:
        allowed = ", ".join(sorted(ALLOWED_HARMLESS_COMMANDS))
        raise ValueError(
            f"disallowed webshell command(s): {', '.join(disallowed)} "
            f"(allowed: {allowed})"
        )
    return commands


def _ensure_output_dir(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def resolve_remote_bundle_path(remote_work_dir: str, run_id: str) -> str:
    """Derive the remote events.jsonl path from work directory and run ID."""
    base = remote_work_dir.rstrip("/")
    return f"{base}/{run_id}/events.jsonl"


def _collect_run_artifacts(run_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for candidate in sorted(run_dir.iterdir()):
        if candidate.is_file():
            paths.append(candidate.resolve())
    return paths


def _export_artifacts(
    store: EventStore,
    *,
    run_id: str,
    output_dir: Path,
) -> tuple[list[Path], dict[str, object]]:
    evidence_result = EvidenceExporter(store).export(
        EvidenceExportRequest(run_id=run_id, output_directory=output_dir)
    )
    manual_result = ManualVerificationPackageGenerator(store).generate(
        ManualVerificationRequest(run_id=run_id, output_directory=output_dir)
    )

    generated = [
        Path(path)
        for path in (*evidence_result.exported_files, *manual_result.generated_files)
    ]
    metadata = {
        "evidence_export_metadata": dict(evidence_result.export_metadata),
        "manual_verification_metadata": dict(manual_result.package_metadata),
    }
    return generated, metadata


def run_local_lab(
    *,
    scenario_id: str,
    output_dir: Path,
    target_net: str,
    traffic_profile: str,
    dry_run: bool = False,
) -> LabRunResult:
    """Execute a scenario on the DSP host in live (or dry-run) mode."""
    profile = profile_for_scenario(scenario_id, traffic_profile)
    scenario_params = build_scenario_params(scenario_id, traffic_profile)

    os.environ["DSP_RUNS_DIR"] = str(output_dir)
    manager = RunManager(runs_dir=output_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=[scenario_id],
        target_net=target_net,
        dry_run=dry_run,
        scenario_params=scenario_params,
    )
    if exit_code == 3:
        raise ValueError(
            f"scenario run failed with config error (exit_code={exit_code}, "
            f"status={run.status.value})"
        )

    run_id = run.run_id
    event_store_path = run_dir / "events.db"
    store = EventStore.open_existing(event_store_path)
    generated = _collect_run_artifacts(run_dir)

    try:
        event_count = store.count(EventQuery(run_id=run_id))
        artifact_paths, artifact_metadata = _export_artifacts(
            store,
            run_id=run_id,
            output_dir=run_dir,
        )
        for path in artifact_paths:
            resolved = path.resolve()
            if resolved not in generated:
                generated.append(resolved)

        return LabRunResult(
            mode="local",
            scenario=scenario_id,
            traffic_profile=profile.name,
            run_id=run_id,
            output_dir=output_dir,
            run_dir=run_dir,
            event_count=event_count,
            generated_files=generated,
            metadata={
                "dry_run": dry_run,
                "target_net": target_net,
                "traffic_profile_description": profile.description,
                "scenario_params": scenario_params.get(scenario_id, {}),
                "dsp_exit_code": exit_code,
                "run_status": run.status.value,
                **artifact_metadata,
            },
        )
    finally:
        store.close()


def run_webshell_lab(
    *,
    scenario_id: str,
    output_dir: Path,
    run_id: str,
    target_net: str,
    traffic_profile: str,
    webshell_family: str,
    webshell_url: str,
    remote_work_dir: str,
    verify_tls: bool,
    harmless_commands: Sequence[str],
    remote_bundle_path: str | None = None,
) -> LabRunResult:
    """Execute a scenario remotely via webshell and collect remote events."""
    profile = profile_for_scenario(scenario_id, traffic_profile)
    scenario_params = profile.scenario_params
    bundle_path = remote_bundle_path or resolve_remote_bundle_path(
        remote_work_dir, run_id
    )

    run_dir = _ensure_output_dir(output_dir)
    store = EventStore(run_dir / "events.db")
    store.open_run(run_id)
    generated: list[Path] = [run_dir / "events.db"]
    command_results: list[dict[str, object]] = []

    provider = create_execution_provider(
        "webshell",
        webshell_family=webshell_family,
        webshell_url=webshell_url,
        verify_tls=verify_tls,
        enable_healthcheck_on_connect=True,
    )
    exec_ctx = ExecutionContext(
        run_id=run_id,
        target_net=target_net,
        dry_run=False,
        provider_type="webshell",
        scenario_id=scenario_id,
    )

    try:
        provider.prepare(exec_ctx)

        for command in harmless_commands:
            result = provider.execute_command(CommandRequest.new(command))
            command_results.append(
                {
                    "command": command,
                    "status": str(result.status),
                    "command_id": result.command_id,
                }
            )

        scenario_request = ScenarioExecutionRequest(
            scenario_id=scenario_id,
            scenario_params=dict(scenario_params),
            execution_metadata={
                "remote_work_dir": remote_work_dir,
                "remote_bundle_path": bundle_path,
                "traffic_profile": profile.name,
            },
            run_id=run_id,
            target_net=target_net,
            dry_run=False,
        )
        remote_result = RemoteScenarioRunner().run(scenario_request, provider)
        command_results.append(
            {
                "command": "dsp-remote-scenario",
                "status": remote_result.command_metadata.get("command_status"),
                "remote_execution_id": remote_result.remote_execution_id,
            }
        )

        collection_result = RemoteEventCollector().collect(
            RemoteEventCollectionRequest(
                remote_execution_id=run_id,
                remote_bundle_path=bundle_path,
            ),
            provider,
            store,
        )
        if collection_result.local_bundle_path:
            generated.append(Path(collection_result.local_bundle_path).resolve())

        event_count = store.count(EventQuery(run_id=run_id))
        artifact_paths, artifact_metadata = _export_artifacts(
            store,
            run_id=run_id,
            output_dir=run_dir,
        )
        generated.extend(artifact_paths)

        return LabRunResult(
            mode="webshell",
            scenario=scenario_id,
            traffic_profile=profile.name,
            run_id=run_id,
            output_dir=run_dir,
            run_dir=run_dir,
            event_count=event_count,
            generated_files=generated,
            metadata={
                "webshell_family": webshell_family,
                "webshell_url": webshell_url,
                "remote_work_dir": remote_work_dir,
                "remote_bundle_path": bundle_path,
                "harmless_commands": list(harmless_commands),
                "command_results": command_results,
                "events_imported": collection_result.events_imported,
                "collection_metadata": dict(collection_result.collection_metadata),
                "scenario_params": scenario_params,
                **artifact_metadata,
            },
        )
    finally:
        provider.cleanup(exec_ctx)
        store.close()


MANUAL_NEXT_STEPS = (
    "1. Check Stellar Sensor traffic visibility.",
    "2. Check Stellar UI manually.",
    "3. Review generated evidence files.",
    "4. Fill in manual verification notes.",
)


def _print_result(result: LabRunResult) -> None:
    print("DSP operational lab run completed")
    print(f"mode={result.mode}")
    print(f"scenario={result.scenario}")
    print(f"traffic_profile={result.traffic_profile}")
    print(f"run_id={result.run_id}")
    print(f"output_dir={result.output_dir}")
    print(f"run_dir={result.run_dir}")
    print(f"event_count={result.event_count}")
    print("generated_files:")
    for path in result.generated_files:
        print(f"  {path}")
    print("manual_next_steps:")
    for step in MANUAL_NEXT_STEPS:
        print(f"  {step}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run DSP operational lab tests — host direct or webshell remote "
            "traffic execution, event collection, evidence export."
        ),
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=sorted(SUPPORTED_MODES),
        help="Execution mode: local (host direct) or webshell (remote).",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Artifact directory (DSP_RUNS_DIR for local mode).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Stable run identifier (default: auto-generated UTC timestamp).",
    )
    parser.add_argument(
        "--scenario",
        default=DEFAULT_SCENARIO,
        help=f"Scenario plugin ID (default: {DEFAULT_SCENARIO}).",
    )
    parser.add_argument(
        "--traffic-profile",
        default=DEFAULT_TRAFFIC_PROFILE,
        help=(
            "Operational traffic profile: low, balanced, or burst "
            f"(default: {DEFAULT_TRAFFIC_PROFILE})."
        ),
    )
    parser.add_argument(
        "--target-net",
        default=DEFAULT_TARGET_NET,
        help=f"Target network CIDR (default: {DEFAULT_TARGET_NET}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Local mode only: mock traffic without network I/O (tests).",
    )
    parser.add_argument(
        "--webshell-family",
        "--webshell-type",
        dest="webshell_family",
        choices=sorted(SUPPORTED_WEBSHELL_FAMILIES),
        help="Webshell family for webshell mode (jsp, php, or aspx).",
    )
    parser.add_argument(
        "--webshell-url",
        help="Webshell endpoint URL for webshell mode.",
    )
    parser.add_argument(
        "--remote-work-dir",
        default=DEFAULT_REMOTE_WORK_DIR,
        help=(
            "Remote working directory on target host "
            f"(default: {DEFAULT_REMOTE_WORK_DIR})."
        ),
    )
    parser.add_argument(
        "--remote-bundle-path",
        help=(
            "Override remote events.jsonl path "
            "(default: <remote-work-dir>/<run_id>/events.jsonl)."
        ),
    )
    parser.add_argument(
        "--verify-tls",
        action="store_true",
        help="Verify TLS certificates for webshell HTTP transport (default: disabled).",
    )
    parser.add_argument(
        "--webshell-commands",
        default=",".join(DEFAULT_HARMLESS_COMMANDS),
        help=(
            "Comma-separated harmless webshell preflight commands "
            f"(allowed: {', '.join(DEFAULT_HARMLESS_COMMANDS)})."
        ),
    )
    return parser


def validate_args(args: argparse.Namespace) -> tuple[str, str, bool, tuple[str, ...], str | None]:
    run_id = args.run_id or _generate_run_id()
    traffic_profile = parse_traffic_profile(args.traffic_profile)
    dry_run = bool(args.dry_run)
    remote_bundle_override = args.remote_bundle_path

    if args.mode == "webshell":
        missing = []
        if not args.webshell_family:
            missing.append("--webshell-family")
        if not args.webshell_url:
            missing.append("--webshell-url")
        if missing:
            raise ValueError(f"webshell mode requires: {', '.join(missing)}")
        harmless_commands = _parse_harmless_commands(args.webshell_commands)
        return run_id, traffic_profile, dry_run, harmless_commands, remote_bundle_override

    harmless_commands = ()
    return run_id, traffic_profile, dry_run, harmless_commands, remote_bundle_override


def run_from_args(args: argparse.Namespace) -> LabRunResult:
    output_dir = _ensure_output_dir(args.output_dir)
    run_id, traffic_profile, dry_run, harmless_commands, remote_bundle_override = (
        validate_args(args)
    )

    if args.mode == "local":
        return run_local_lab(
            scenario_id=args.scenario,
            output_dir=output_dir,
            target_net=args.target_net,
            traffic_profile=traffic_profile,
            dry_run=dry_run,
        )

    return run_webshell_lab(
        scenario_id=args.scenario,
        output_dir=output_dir,
        run_id=run_id,
        target_net=args.target_net,
        traffic_profile=traffic_profile,
        webshell_family=args.webshell_family,
        webshell_url=args.webshell_url,
        remote_work_dir=args.remote_work_dir,
        verify_tls=args.verify_tls,
        harmless_commands=harmless_commands,
        remote_bundle_path=remote_bundle_override,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        result = run_from_args(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"lab run failed: {exc}", file=sys.stderr)
        return 1

    _print_result(result)
    return 0
