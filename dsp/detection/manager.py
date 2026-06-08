"""Detection Manager — orchestrates adapters after S2 validation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dsp.detection.base import DetectionAdapter
from dsp.detection.correlation import build_correlation_context, correlate
from dsp.detection.models import CorrelationContext, EvidencePack, S3Result, S3Status
from dsp.event_store import EventStore, Run, ValidationDecision, ValidationResult


class DetectionManager:
    """Consumer orchestrator — never modifies ValidationResult or scenario exit code."""

    def __init__(
        self,
        store: EventStore,
        adapters: list[DetectionAdapter] | None = None,
    ) -> None:
        self.store = store
        self._adapters: dict[str, DetectionAdapter] = {}
        for adapter in adapters or []:
            self.register_adapter(adapter)

    def register_adapter(self, adapter: DetectionAdapter) -> None:
        self._adapters[adapter.vendor_id] = adapter

    def get_adapter(self, vendor_id: str) -> DetectionAdapter | None:
        return self._adapters.get(vendor_id)

    @property
    def vendor_ids(self) -> list[str]:
        return sorted(self._adapters.keys())

    def confirm_detection(
        self,
        run: Run,
        validation_results: list[ValidationResult],
        *,
        vendor_id: str = "stellar",
        output_dir: Path | None = None,
        scenario_types: dict[str, str] | None = None,
    ) -> list[S3Result]:
        """Run S3 confirmation for each validation result via the named adapter."""
        adapter = self._adapters.get(vendor_id)
        if adapter is None:
            raise ValueError(f"unknown detection adapter: {vendor_id}")

        results: list[S3Result] = []
        for vr in validation_results:
            context = build_correlation_context(
                run=run,
                validation_result=vr,
                store=self.store,
                scenario_type=(scenario_types or {}).get(vr.scenario_id),
            )
            s3_result = self._confirm_scenario(adapter, context, output_dir)
            results.append(s3_result)
        return results

    def _confirm_scenario(
        self,
        adapter: DetectionAdapter,
        context: CorrelationContext,
        output_dir: Path | None,
    ) -> S3Result:
        if context.s2_decision != ValidationDecision.SUCCESS.value:
            return S3Result(
                run_id=context.run_id,
                scenario=context.scenario_id,
                status=S3Status.S3_INCONCLUSIVE,
                vendor=adapter.vendor_id,
                evidence_count=0,
                timestamp=datetime.now(timezone.utc),
                correlation_context=context,
                reason=f"s2_decision={context.s2_decision}; adapter consumer only polls after S2 success",
            )

        evidence = adapter.collect_evidence(context)
        s3_result = adapter.validate_detection(context, evidence)

        if output_dir is not None:
            adapter.build_evidence_pack(context, evidence, s3_result, output_dir)

        return s3_result

    def write_s3_results(
        self,
        base_dir: Path,
        results: list[S3Result],
        *,
        vendor_id: str = "stellar",
    ) -> Path:
        """Persist s3_result.json under evidence/<run_id>/<vendor>/."""
        if not results:
            raise ValueError("no S3 results to write")

        run_id = results[0].run_id
        vendor_dir = base_dir / "evidence" / run_id / vendor_id
        vendor_dir.mkdir(parents=True, exist_ok=True)

        payload: dict[str, Any] = {
            "run_id": run_id,
            "vendor": vendor_id,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "results": [r.to_dict() for r in results],
        }
        result_filename = (
            "s3_result_manual.json" if vendor_id == "manual" else "s3_result.json"
        )
        path = vendor_dir / result_filename
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path


def run_detection_confirmation(
    *,
    store: EventStore,
    run: Run,
    validation_results: list[ValidationResult],
    adapters: list[DetectionAdapter],
    run_dir: Path,
    vendor_id: str = "stellar",
) -> list[S3Result]:
    """Convenience entry point for post-validation S3 polling."""
    manager = DetectionManager(store, adapters)
    return manager.confirm_detection(
        run,
        validation_results,
        vendor_id=vendor_id,
        output_dir=run_dir,
    )
