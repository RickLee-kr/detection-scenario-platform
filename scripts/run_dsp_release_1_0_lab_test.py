#!/usr/bin/env python3
"""DSP Release 1.0 operational lab runner — no detection validation.

Operational harness only:
  - traffic/scenario execution (local mode via RunManager / DSP_RUNS_DIR)
  - webshell connectivity + remote bundle collection (webshell mode)
  - event collection
  - evidence export
  - manual verification package generation

Does not validate detections, alerts, cases, attack success, or detection success.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

_DSP_ROOT = Path(__file__).resolve().parent.parent
if str(_DSP_ROOT) not in sys.path:
    sys.path.insert(0, str(_DSP_ROOT))

from dsp.event_store import EventQuery, EventStore
from dsp.evidence import EvidenceExportRequest, EvidenceExporter
from dsp.execution import ExecutionContext, create_execution_provider
from dsp.execution.providers.runtime.command.command_models import CommandRequest
from dsp.execution.remote import RemoteEventCollectionRequest, RemoteEventCollector
from dsp.manual_verification import (
    ManualVerificationPackageGenerator,
    ManualVerificationRequest,
)
from dsp.runner.run_manager import RunManager

SUPPORTED_MODES = frozenset({"local", "webshell"})
SUPPORTED_WEBSHELL_TYPES = frozenset({"jsp", "php", "aspx"})
DEFAULT_HARMLESS_COMMANDS = ("whoami", "pwd", "hostname")
ALLOWED_HARMLESS_COMMANDS = frozenset(DEFAULT_HARMLESS_COMMANDS)
DEFAULT_TARGET_NET = "10.10.10.0/24"
DEFAULT_SCENARIO = "dummy"


@dataclass
class LabRunResult:
    """Paths and metadata produced by a lab run."""

    mode: str
    run_id: str
    output_dir: Path
    run_dir: Path
    event_store_path: Path
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
        "event_count": evidence_result.export_metadata.get("event_count"),
        "evidence_export_metadata": dict(evidence_result.export_metadata),
        "manual_verification_metadata": dict(manual_result.package_metadata),
    }
    return generated, metadata


def run_local_lab(
    *,
    scenario_id: str,
    output_dir: Path,
    target_net: str,
    dry_run: bool,
) -> LabRunResult:
    os.environ["DSP_RUNS_DIR"] = str(output_dir)

    manager = RunManager(runs_dir=output_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=[scenario_id],
        target_net=target_net,
        dry_run=dry_run,
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
            run_id=run_id,
            output_dir=output_dir,
            run_dir=run_dir,
            event_store_path=event_store_path,
            generated_files=generated,
            metadata={
                "scenario_id": scenario_id,
                "dry_run": dry_run,
                "target_net": target_net,
                "dsp_exit_code": exit_code,
                "run_status": run.status.value,
                "event_count": event_count,
                **artifact_metadata,
            },
        )
    finally:
        store.close()


def run_webshell_lab(
    *,
    output_dir: Path,
    run_id: str,
    target_net: str,
    webshell_type: str,
    webshell_url: str,
    remote_bundle_path: str,
    verify_tls: bool,
    harmless_commands: Sequence[str],
) -> LabRunResult:
    run_dir = _ensure_output_dir(output_dir)
    store = EventStore(run_dir / "events.db")
    store.open_run(run_id)
    generated: list[Path] = [run_dir / "events.db"]
    command_results: list[dict[str, object]] = []

    provider = create_execution_provider(
        "webshell",
        webshell_family=webshell_type,
        webshell_url=webshell_url,
        verify_tls=verify_tls,
        enable_healthcheck_on_connect=True,
    )
    exec_ctx = ExecutionContext(
        run_id=run_id,
        target_net=target_net,
        dry_run=False,
        provider_type="webshell",
        scenario_id="webshell_lab",
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

        collection_result = RemoteEventCollector().collect(
            RemoteEventCollectionRequest(
                remote_execution_id=run_id,
                remote_bundle_path=remote_bundle_path,
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
            run_id=run_id,
            output_dir=run_dir,
            run_dir=run_dir,
            event_store_path=run_dir / "events.db",
            generated_files=generated,
            metadata={
                "webshell_type": webshell_type,
                "webshell_url": webshell_url,
                "remote_bundle_path": remote_bundle_path,
                "harmless_commands": list(harmless_commands),
                "command_results": command_results,
                "events_imported": collection_result.events_imported,
                "event_count": event_count,
                "collection_metadata": dict(collection_result.collection_metadata),
                **artifact_metadata,
            },
        )
    finally:
        provider.cleanup(exec_ctx)
        store.close()


def _print_result(result: LabRunResult) -> None:
    print("DSP Release 1.0 lab run completed")
    print(f"mode={result.mode}")
    print(f"run_id={result.run_id}")
    print(f"output_dir={result.output_dir}")
    print(f"run_dir={result.run_dir}")
    print("generated_files:")
    for path in result.generated_files:
        print(f"  {path}")
    for key, value in result.metadata.items():
        print(f"{key}={value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run DSP Release 1.0 operational lab tests "
            "(scenario execution, event collection, evidence export)."
        ),
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=sorted(SUPPORTED_MODES),
        help="Execution mode: local scenario run or webshell bundle collection.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="DSP_RUNS_DIR for local mode; artifact directory for webshell mode.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Stable run identifier for webshell mode (default: auto-generated UTC timestamp).",
    )
    parser.add_argument(
        "--scenario",
        default=DEFAULT_SCENARIO,
        help=f"Scenario plugin ID for local mode (default: {DEFAULT_SCENARIO}).",
    )
    parser.add_argument(
        "--target-net",
        default=DEFAULT_TARGET_NET,
        help=f"Target network CIDR (default: {DEFAULT_TARGET_NET}).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Local mode: allow live traffic execution (default: dry-run, no network I/O).",
    )
    parser.add_argument(
        "--webshell-type",
        choices=sorted(SUPPORTED_WEBSHELL_TYPES),
        help="Webshell family for webshell mode (jsp, php, or aspx).",
    )
    parser.add_argument(
        "--webshell-url",
        help="Webshell endpoint URL for webshell mode.",
    )
    parser.add_argument(
        "--remote-bundle-path",
        help="Remote events.jsonl path to download in webshell mode.",
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
            "Comma-separated harmless webshell commands "
            f"(allowed: {', '.join(DEFAULT_HARMLESS_COMMANDS)})."
        ),
    )
    return parser


def validate_args(args: argparse.Namespace) -> tuple[str, bool, tuple[str, ...]]:
    run_id = args.run_id or _generate_run_id()
    dry_run = not args.live

    if args.mode == "webshell":
        missing = []
        if not args.webshell_type:
            missing.append("--webshell-type")
        if not args.webshell_url:
            missing.append("--webshell-url")
        if not args.remote_bundle_path:
            missing.append("--remote-bundle-path")
        if missing:
            raise ValueError(
                f"webshell mode requires: {', '.join(missing)}"
            )
        harmless_commands = _parse_harmless_commands(args.webshell_commands)
        return run_id, dry_run, harmless_commands

    harmless_commands = ()
    return run_id, dry_run, harmless_commands


def run_from_args(args: argparse.Namespace) -> LabRunResult:
    output_dir = _ensure_output_dir(args.output_dir)
    run_id, dry_run, harmless_commands = validate_args(args)

    if args.mode == "local":
        return run_local_lab(
            scenario_id=args.scenario,
            output_dir=output_dir,
            target_net=args.target_net,
            dry_run=dry_run,
        )

    return run_webshell_lab(
        output_dir=output_dir,
        run_id=run_id,
        target_net=args.target_net,
        webshell_type=args.webshell_type,
        webshell_url=args.webshell_url,
        remote_bundle_path=args.remote_bundle_path,
        verify_tls=args.verify_tls,
        harmless_commands=harmless_commands,
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


if __name__ == "__main__":
    raise SystemExit(main())
