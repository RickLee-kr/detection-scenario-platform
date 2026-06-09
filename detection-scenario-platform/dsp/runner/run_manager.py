"""Run lifecycle and artifact management."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dsp import __version__ as DSP_VERSION
from dsp.detection.factory import (
    UnsupportedDetectionProviderError,
    UnsupportedStellarClientModeError,
    create_detection_adapter,
)
from dsp.detection.manager import DetectionManager
from dsp.detection.reporting import build_detection_confirmation_entries
from dsp.engine import RunConfig, RunContext, resolve_targets
from dsp.evidence import EvidenceExportRequest, EvidenceExporter
from dsp.execution import ExecutionContext, create_execution_provider
from dsp.execution.remote import RemoteEventCollectionRequest, RemoteEventCollector
from dsp.execution.remote.paths import resolve_remote_bundle_path
from dsp.execution.webshell_provider import WebshellExecutionProvider
from dsp.event_store import EventStore, Run, RunStatus, ValidationDecision
from dsp.manual_verification import (
    ManualVerificationPackageGenerator,
    ManualVerificationRequest,
)
from dsp.plugins import PluginLoader, PluginStatus
from dsp.reporting import ReportingEngine
from dsp.validation import ValidationEngine

SUPPORTED_EXECUTION_PROVIDERS = frozenset({"local", "webshell"})
SUPPORTED_WEBSHELL_FAMILIES = frozenset({"jsp", "php", "aspx"})
DEFAULT_REMOTE_WORK_DIR = "/tmp/dsp"


def default_runs_dir() -> Path:
    override = os.environ.get("DSP_RUNS_DIR")
    if override:
        return Path(override)
    return Path.home() / ".dsp" / "runs"


def generate_run_id() -> str:
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    slug = uuid.uuid4().hex[:6]
    return f"{date}_{slug}"


def compute_exit_code(results: list) -> int:
    """Exit code derived from ValidationResult only."""
    if not results:
        return 3
    decisions = [r.decision for r in results]
    if all(d == ValidationDecision.SUCCESS for d in decisions):
        return 0
    if any(d == ValidationDecision.CODE_FAILURE for d in decisions):
        return 2
    if any(d == ValidationDecision.FAILED for d in decisions):
        return 1
    if all(d == ValidationDecision.SKIPPED for d in decisions):
        return 3
    if any(d == ValidationDecision.PARTIAL for d in decisions):
        return 1
    return 1


class RunManager:
    def __init__(
        self,
        runs_dir: Path | None = None,
        scenarios_dir: Path | None = None,
    ) -> None:
        self.runs_dir = runs_dir or default_runs_dir()
        loader = PluginLoader(scenarios_dir=scenarios_dir)
        self.registry = loader.discover_and_load()

    def run(
        self,
        scenario_ids: list[str],
        target_net: str = "10.10.10.0/24",
        dry_run: bool = False,
        scenario_params: dict[str, dict] | None = None,
        confirm_detection: bool = False,
        detection_provider: str = "stellar",
        stellar_client: str = "manual",
        execution_provider: str = "local",
        webshell_family: str | None = None,
        webshell_url: str | None = None,
        remote_work_dir: str = DEFAULT_REMOTE_WORK_DIR,
        verify_tls: bool = False,
        export_evidence: bool = True,
    ) -> tuple[Run, Path, int]:
        if execution_provider not in SUPPORTED_EXECUTION_PROVIDERS:
            run = Run(
                run_id=generate_run_id(),
                status=RunStatus.CONFIG_ERROR,
                target_net=target_net,
                dry_run=dry_run,
                requested_scenarios=scenario_ids,
            )
            return run, self.runs_dir, 3

        if execution_provider == "webshell":
            missing = []
            if not webshell_family:
                missing.append("webshell_family")
            if not webshell_url:
                missing.append("webshell_url")
            if webshell_family and webshell_family not in SUPPORTED_WEBSHELL_FAMILIES:
                missing.append(f"unsupported webshell_family={webshell_family!r}")
            if missing:
                run = Run(
                    run_id=generate_run_id(),
                    status=RunStatus.CONFIG_ERROR,
                    target_net=target_net,
                    dry_run=dry_run,
                    requested_scenarios=scenario_ids,
                )
                return run, self.runs_dir, 3

        active = set(self.registry.active_ids())
        if not scenario_ids:
            scenario_ids = sorted(active)
        if not scenario_ids:
            run = Run(
                run_id=generate_run_id(),
                status=RunStatus.CONFIG_ERROR,
                target_net=target_net,
                dry_run=dry_run,
            )
            return run, self.runs_dir, 3

        for sid in scenario_ids:
            record = self.registry.get(sid)
            if record is None:
                run = Run(
                    run_id=generate_run_id(),
                    status=RunStatus.CONFIG_ERROR,
                    target_net=target_net,
                    dry_run=dry_run,
                    requested_scenarios=scenario_ids,
                )
                return run, self.runs_dir, 3
            if record.status == PluginStatus.DISABLED:
                run = Run(
                    run_id=generate_run_id(),
                    status=RunStatus.CONFIG_ERROR,
                    target_net=target_net,
                    dry_run=dry_run,
                    requested_scenarios=scenario_ids,
                )
                return run, self.runs_dir, 3
            if not record.is_runnable:
                run = Run(
                    run_id=generate_run_id(),
                    status=RunStatus.CONFIG_ERROR,
                    target_net=target_net,
                    dry_run=dry_run,
                    requested_scenarios=scenario_ids,
                )
                return run, self.runs_dir, 3

        if confirm_detection:
            try:
                create_detection_adapter(
                    detection_provider,
                    stellar_client=stellar_client,
                )
            except (UnsupportedDetectionProviderError, UnsupportedStellarClientModeError):
                run = Run(
                    run_id=generate_run_id(),
                    status=RunStatus.CONFIG_ERROR,
                    target_net=target_net,
                    dry_run=dry_run,
                    requested_scenarios=scenario_ids,
                )
                return run, self.runs_dir, 2

        run_id = generate_run_id()
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        config = RunConfig(
            target_net=target_net,
            dry_run=dry_run,
            scenario_params=scenario_params or {},
        )
        run = Run(
            run_id=run_id,
            target_net=target_net,
            started_at=datetime.now(timezone.utc),
            status=RunStatus.RUNNING,
            dry_run=dry_run,
            requested_scenarios=scenario_ids,
            config_snapshot={
                "target_net": target_net,
                "dry_run": dry_run,
                "execution_provider": execution_provider,
            },
            dsp_version=DSP_VERSION,
        )

        db_path = run_dir / "events.db"
        store = EventStore(db_path)
        store.open_run(run_id, metadata=run.to_dict())

        ctx = RunContext(
            run_id=run_id,
            target_net=target_net,
            event_store=store,
            config=config,
            dry_run=dry_run,
        )
        targets = resolve_targets(target_net)

        provider = self._create_execution_provider(
            execution_provider,
            webshell_family=webshell_family,
            webshell_url=webshell_url,
            verify_tls=verify_tls,
        )
        exec_ctx = ExecutionContext(
            run_id=run_id,
            target_net=target_net,
            dry_run=dry_run,
            provider_type=provider.provider_type,
        )
        if execution_provider == "webshell":
            exec_ctx.execution_metadata["remote_work_dir"] = remote_work_dir
            exec_ctx.execution_metadata["remote_bundle_path"] = resolve_remote_bundle_path(
                remote_work_dir,
                run_id,
            )

        provider.prepare(exec_ctx)
        collector = RemoteEventCollector() if execution_provider == "webshell" else None

        summaries: dict[str, dict] = {}
        try:
            for sid in scenario_ids:
                record = self.registry.get(sid)
                assert record is not None
                exec_ctx.scenario_id = sid
                summary = provider.execute(
                    exec_ctx,
                    record,
                    ctx,
                    targets,
                    snapshot_dir=run_dir,
                )
                if summary:
                    summaries[sid] = {
                        "scenario_id": summary.scenario_id,
                        "metrics": summary.metrics,
                        "event_count": summary.event_count,
                        "notes": summary.notes,
                    }

                if execution_provider == "webshell" and collector is not None:
                    assert isinstance(provider, WebshellExecutionProvider)
                    remote_execution_id = exec_ctx.execution_metadata.get(
                        "remote_execution_id",
                        run_id,
                    )
                    remote_bundle_path = exec_ctx.execution_metadata["remote_bundle_path"]
                    collection_result = collector.collect(
                        RemoteEventCollectionRequest(
                            remote_execution_id=str(remote_execution_id),
                            remote_bundle_path=str(remote_bundle_path),
                        ),
                        provider,
                        store,
                    )
                    exec_ctx.execution_metadata["events_imported"] = (
                        collection_result.events_imported
                    )
        finally:
            provider.cleanup(exec_ctx)

        validator = ValidationEngine(store, self.registry)
        results = validator.validate_run(run_id, scenario_ids)
        validator.write_validation_json(run_dir / "validation.json", results)

        detection_confirmation = None
        if confirm_detection:
            s3_results, adapter_vendor_id = self._run_detection_confirmation(
                store=store,
                run=run,
                results=results,
                run_dir=run_dir,
                detection_provider=detection_provider,
                stellar_client=stellar_client,
            )
            evidence_path = str(run_dir / "evidence" / run_id / adapter_vendor_id)
            detection_confirmation = build_detection_confirmation_entries(
                s3_results,
                evidence_path,
            )

        run.status = RunStatus.COMPLETED
        run.ended_at = datetime.now(timezone.utc)

        reporter = ReportingEngine(store, self.registry)
        report = reporter.generate(run_id, results, run=run, summaries=summaries)
        if detection_confirmation is not None:
            report.detection_confirmation = detection_confirmation
        reporter.write_report_md(run_dir / "report.md", report)
        reporter.write_report_json(run_dir / "report.json", report)

        store.export_jsonl(run_dir / "events.jsonl")
        store.close_run()
        self._write_run_json(run_dir / "run.json", run)

        if export_evidence:
            self._export_evidence(store, run_id=run_id, run_dir=run_dir)

        exit_code = compute_exit_code(results)
        store.close()
        return run, run_dir, exit_code

    @staticmethod
    def _create_execution_provider(
        execution_provider: str,
        *,
        webshell_family: str | None = None,
        webshell_url: str | None = None,
        verify_tls: bool = False,
    ):
        if execution_provider == "local":
            return create_execution_provider("local")
        return create_execution_provider(
            "webshell",
            webshell_family=webshell_family,
            webshell_url=webshell_url,
            verify_tls=verify_tls,
            enable_healthcheck_on_connect=True,
        )

    @staticmethod
    def _export_evidence(
        store: EventStore,
        *,
        run_id: str,
        run_dir: Path,
    ) -> dict[str, Any]:
        evidence_result = EvidenceExporter(store).export(
            EvidenceExportRequest(run_id=run_id, output_directory=run_dir)
        )
        manual_result = ManualVerificationPackageGenerator(store).generate(
            ManualVerificationRequest(run_id=run_id, output_directory=run_dir)
        )
        return {
            "evidence_export_metadata": dict(evidence_result.export_metadata),
            "manual_verification_metadata": dict(manual_result.package_metadata),
        }

    def _run_detection_confirmation(
        self,
        *,
        store: EventStore,
        run: Run,
        results: list,
        run_dir: Path,
        detection_provider: str,
        stellar_client: str = "manual",
    ) -> tuple[list, str]:
        adapter = create_detection_adapter(
            detection_provider,
            stellar_client=stellar_client,
        )
        manager = DetectionManager(store, [adapter])
        s3_results = manager.confirm_detection(
            run,
            results,
            vendor_id=adapter.vendor_id,
            output_dir=run_dir,
        )
        manager.write_s3_results(run_dir, s3_results, vendor_id=adapter.vendor_id)
        return s3_results, adapter.vendor_id

    def regenerate_report(self, run_id: str) -> Path:
        run_dir = self.runs_dir / run_id
        run_json = run_dir / "run.json"
        validation_json = run_dir / "validation.json"
        db_path = run_dir / "events.db"

        run = Run.from_dict(json.loads(run_json.read_text(encoding="utf-8")))
        results = ValidationEngine.load_validation_json(validation_json)
        store = EventStore.open_existing(db_path)

        reporter = ReportingEngine(store, self.registry)
        report = reporter.generate(run_id, results, run=run)
        reporter.write_report_md(run_dir / "report.md", report)
        reporter.write_report_json(run_dir / "report.json", report)
        store.close()
        return run_dir / "report.md"

    @staticmethod
    def _write_run_json(path: Path, run: Run) -> None:
        path.write_text(json.dumps(run.to_dict(), indent=2), encoding="utf-8")
