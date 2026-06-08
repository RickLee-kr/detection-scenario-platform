"""Stellar Detection Adapter — mock and HTTP client support."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dsp.detection.base import DetectionAdapter
from dsp.detection.correlation import correlate
from dsp.detection.models import CorrelationContext, EvidencePack, S3Result, S3Status
from dsp.detection.providers.stellar.client_base import (
    StellarClient,
    StellarSearchParams,
    StellarSearchResult,
)
from dsp.detection.providers.stellar.contracts.contract_loader import (
    EvidenceSource,
    ScenarioContractRegistry,
    load_scenario_contracts,
)
from dsp.detection.providers.stellar.detection_cache import DetectionQueryCache, build_cache_key
from dsp.detection.providers.stellar.detection_logger import DetectionLogger
from dsp.detection.providers.stellar.evidence_limits import (
    EvidenceLimitConfig,
    TruncationSummary,
    apply_evidence_limits,
)
from dsp.detection.providers.stellar.mock_client import MockStellarClient
from dsp.detection.providers.stellar.normalization import (
    build_evidence_pack,
    normalization_counts,
    sanitize_raw_items,
)
from dsp.detection.providers.stellar.query_builder import (
    build_search_params,
    evidence_types_to_query,
)
from dsp.detection.providers.stellar.stellar_mapping import (
    StellarMappingRegistry,
    load_stellar_mapping,
)

_EVIDENCE_SEARCH_METHODS = {
    EvidenceSource.ALERT: "search_alerts",
    EvidenceSource.ANALYTICS: "search_analytics",
    EvidenceSource.ENTITY: "search_entities",
    EvidenceSource.TIMELINE: "search_timeline",
}


class StellarAdapter(DetectionAdapter):
    """Stellar adapter — uses normalized evidence for all S3 decisions."""

    def __init__(
        self,
        *,
        client: StellarClient | None = None,
        mapping: StellarMappingRegistry | None = None,
        mapping_path: Path | None = None,
        contracts: ScenarioContractRegistry | None = None,
        contracts_path: Path | None = None,
        simulate_detection: bool = True,
        simulate_empty: bool = False,
        client_mode: str = "mock",
        query_optional_evidence: bool = False,
        evidence_limits: EvidenceLimitConfig | None = None,
        query_cache: DetectionQueryCache | None = None,
    ) -> None:
        self._mapping = mapping or load_stellar_mapping(mapping_path)
        self._contracts = contracts or load_scenario_contracts(contracts_path)
        self._client_mode = client_mode
        self._query_optional_evidence = query_optional_evidence
        self._client = client or MockStellarClient(
            simulate_detection=simulate_detection,
            simulate_empty=simulate_empty,
        )
        self._evidence_limits = evidence_limits or EvidenceLimitConfig()
        self._query_cache = query_cache or DetectionQueryCache()
        self._collection_errors: list[str] = []
        self._raw_responses: dict[str, list[dict[str, Any]]] = {}
        self._query_log: list[dict[str, Any]] = []
        self._response_counts: dict[str, int] = {}
        self._pagination_counts: dict[str, int] = {}
        self._execution_times_ms: dict[str, float] = {}
        self._truncation_summary = TruncationSummary()
        self._logger = DetectionLogger()

    @property
    def vendor_id(self) -> str:
        return "stellar"

    @property
    def mapping(self) -> StellarMappingRegistry:
        return self._mapping

    @property
    def contracts(self) -> ScenarioContractRegistry:
        return self._contracts

    @property
    def client_mode(self) -> str:
        return self._client_mode

    @property
    def detection_logger(self) -> DetectionLogger:
        return self._logger

    @property
    def query_cache(self) -> DetectionQueryCache:
        return self._query_cache

    def collect_evidence(self, context: CorrelationContext) -> EvidencePack:
        self._collection_errors = []
        self._raw_responses = {}
        self._query_log = []
        self._response_counts = {}
        self._pagination_counts = {}
        self._execution_times_ms = {}
        self._truncation_summary = TruncationSummary()
        self._query_cache.clear()
        self._logger = DetectionLogger()
        self._reset_client_run_state()

        self._logger.log(
            "provider_selected",
            run_id=context.run_id,
            scenario_id=context.scenario_id,
            provider=self.vendor_id,
            client_mode=self._client_mode,
        )

        contract = self._contracts.get(context.scenario_id)
        scenario_mapping = self._mapping.get(context.scenario_id)

        alerts: list[dict[str, Any]] = []
        analytics: list[dict[str, Any]] = []
        entities: list[dict[str, Any]] = []
        timeline: list[dict[str, Any]] = []

        if contract is None:
            self._logger.log(
                "contract_missing",
                run_id=context.run_id,
                scenario_id=context.scenario_id,
                message="no scenario contract; falling back to legacy full collection",
            )
            params = self._build_legacy_search_params(context, scenario_mapping)
            alerts = self._search("alerts", self._client.search_alerts, params)
            analytics = self._search("analytics", self._client.search_analytics, params)
            entities = self._search("entities", self._client.search_entities, params)
            timeline = self._search("timeline", self._client.search_timeline, params)
        else:
            evidence_types = evidence_types_to_query(
                contract,
                include_optional=self._query_optional_evidence,
            )
            for evidence_type in evidence_types:
                params = build_search_params(
                    context=context,
                    contract=contract,
                    evidence_type=evidence_type,
                    mapping=scenario_mapping,
                )
                method_name = _EVIDENCE_SEARCH_METHODS[evidence_type]
                search_fn = getattr(self._client, method_name)
                key = evidence_type.value
                items = self._search(key, search_fn, params)
                if evidence_type == EvidenceSource.ALERT:
                    alerts = items
                elif evidence_type == EvidenceSource.ANALYTICS:
                    analytics = items
                elif evidence_type == EvidenceSource.ENTITY:
                    entities = items
                elif evidence_type == EvidenceSource.TIMELINE:
                    timeline = items

        alerts, analytics, entities, timeline, self._truncation_summary = apply_evidence_limits(
            alerts=alerts,
            analytics=analytics,
            entities=entities,
            timeline=timeline,
            config=self._evidence_limits,
        )
        if self._truncation_summary.any_truncated:
            self._logger.log(
                "evidence_truncated",
                run_id=context.run_id,
                scenario_id=context.scenario_id,
                truncation=self._truncation_summary.to_dict(),
            )

        evidence = build_evidence_pack(
            context=context,
            alerts=alerts,
            analytics=analytics,
            entities=entities,
            timeline=timeline,
        )

        counts = normalization_counts(evidence)
        self._logger.log(
            "normalization_complete",
            run_id=context.run_id,
            scenario_id=context.scenario_id,
            raw_response_counts=self._response_counts,
            pagination_counts=self._pagination_counts,
            normalization_counts=counts,
            evidence_counts={
                "alerts": len(evidence.alerts),
                "analytics": len(evidence.analytics),
                "entities": len(evidence.entities),
                "timeline": len(evidence.timeline),
                "total": evidence.evidence_count,
            },
        )

        return evidence

    def validate_detection(
        self,
        context: CorrelationContext,
        evidence: EvidencePack,
    ) -> S3Result:
        if self._collection_errors:
            self._logger.log(
                "s3_decision",
                run_id=context.run_id,
                scenario_id=context.scenario_id,
                status=S3Status.S3_INCONCLUSIVE.value,
                correlation_score=0.0,
                reason=f"stellar_client_errors: {'; '.join(self._collection_errors)}",
                evidence_count=evidence.evidence_count,
            )
            return S3Result(
                run_id=context.run_id,
                scenario=context.scenario_id,
                status=S3Status.S3_INCONCLUSIVE,
                vendor=self.vendor_id,
                evidence_count=evidence.evidence_count,
                timestamp=datetime.now(timezone.utc),
                correlation_context=context,
                reason=f"stellar_client_errors: {'; '.join(self._collection_errors)}",
                evidence_pack=evidence,
            )

        scenario_mapping = self._mapping.get(context.scenario_id)
        detection_model_id = (
            scenario_mapping.detection_model_id if scenario_mapping else None
        )

        status, score, reason = correlate(
            context,
            evidence,
            detection_model_id=detection_model_id,
        )

        self._logger.log(
            "s3_decision",
            run_id=context.run_id,
            scenario_id=context.scenario_id,
            status=status.value,
            correlation_score=round(score, 4),
            reason=reason,
            evidence_count=evidence.evidence_count,
        )

        return S3Result(
            run_id=context.run_id,
            scenario=context.scenario_id,
            status=status,
            vendor=self.vendor_id,
            evidence_count=evidence.evidence_count,
            timestamp=datetime.now(timezone.utc),
            correlation_context=context,
            reason=reason,
            evidence_pack=evidence,
        )

    def build_evidence_pack(
        self,
        context: CorrelationContext,
        evidence: EvidencePack,
        s3_result: S3Result,
        output_dir: Path,
    ) -> Path:
        vendor_dir = output_dir / "evidence" / context.run_id / self.vendor_id
        vendor_dir.mkdir(parents=True, exist_ok=True)
        raw_dir = vendor_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        self._logger.set_log_path(vendor_dir / "detection.log")
        self._logger.flush()

        self._write_json(vendor_dir / "alerts.json", [a.to_dict() for a in evidence.alerts])
        self._write_json(
            vendor_dir / "analytics.json",
            [a.to_dict() for a in evidence.analytics],
        )
        self._write_json(vendor_dir / "entities.json", [e.to_dict() for e in evidence.entities])
        self._write_json(vendor_dir / "timeline.json", [t.to_dict() for t in evidence.timeline])
        self._write_json(vendor_dir / "s3_result.json", s3_result.to_dict())

        for name, items in self._raw_responses.items():
            self._write_json(raw_dir / f"{name}.json", sanitize_raw_items(items))

        if self._collection_errors:
            self._write_json(
                vendor_dir / "client_errors.json",
                {"errors": self._collection_errors},
            )

        self._write_evidence_md(vendor_dir / "evidence.md", context, evidence, s3_result)

        return vendor_dir

    def _reset_client_run_state(self) -> None:
        reset_fn = getattr(self._client, "reset_run_state", None)
        if callable(reset_fn):
            reset_fn()

    def _build_legacy_search_params(
        self,
        context: CorrelationContext,
        scenario_mapping,
    ) -> StellarSearchParams:
        if scenario_mapping is None:
            return StellarSearchParams(context=context)

        return StellarSearchParams(
            context=context,
            detection_model_id=scenario_mapping.detection_model_id,
            alert_families=list(scenario_mapping.alert_families),
            analytics_types=list(scenario_mapping.analytics_types),
            correlation=dict(scenario_mapping.correlation),
        )

    def _search(
        self,
        name: str,
        method,
        params: StellarSearchParams,
    ) -> list[dict[str, Any]]:
        query_snapshot = {
            "evidence_type": name,
            "method": params.http_method or "GET",
            "path": params.api_path,
            "query_keys": sorted(params.query.keys()) if params.query else [],
        }
        self._query_log.append(query_snapshot)

        cache_key = build_cache_key(
            provider=self.vendor_id,
            evidence_type=name,
            params=params,
        )
        cached = self._query_cache.get(cache_key)
        if cached is not None:
            self._record_query_result(name, params, cached, cache_hit=True)
            return list(cached.items)

        self._logger.log(
            "query_executed",
            run_id=params.context.run_id,
            scenario_id=params.context.scenario_id,
            evidence_type=name,
            http_method=params.http_method or "GET",
            api_path=params.api_path,
            query_keys=query_snapshot["query_keys"],
            cache_hit=False,
        )

        result: StellarSearchResult = method(params)
        self._query_cache.put(cache_key, result)
        self._record_query_result(name, params, result, cache_hit=False)
        return list(result.items)

    def _record_query_result(
        self,
        name: str,
        params: StellarSearchParams,
        result: StellarSearchResult,
        *,
        cache_hit: bool,
    ) -> None:
        self._raw_responses[name] = list(result.items)
        self._response_counts[name] = len(result.items)
        self._pagination_counts[name] = result.page_count
        if result.execution_time_ms is not None:
            self._execution_times_ms[name] = result.execution_time_ms

        self._logger.log(
            "query_response",
            run_id=params.context.run_id,
            scenario_id=params.context.scenario_id,
            evidence_type=name,
            response_count=len(result.items),
            total_fetched=result.total_fetched or len(result.items),
            page_count=result.page_count,
            http_status=result.http_status,
            execution_time_ms=result.execution_time_ms,
            cache_hit=cache_hit,
            error=str(result.error) if result.error else None,
        )

        if result.error is not None:
            self._collection_errors.append(f"{name}: {result.error}")

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _write_evidence_md(
        self,
        path: Path,
        context: CorrelationContext,
        evidence: EvidencePack,
        s3_result: S3Result,
    ) -> None:
        lines = [
            f"# S3 Evidence — {context.scenario_id}",
            "",
            f"**Run ID:** {context.run_id}",
            f"**Vendor:** {evidence.vendor}",
            f"**S3 Status:** {s3_result.status.value}",
            f"**Evidence Count:** {evidence.evidence_count}",
            f"**Reason:** {s3_result.reason}",
            "",
            "## Correlation Context",
            "",
            f"- Time window: {context.time_window_start.isoformat()} → {context.time_window_end.isoformat()}",
            f"- Source IP: {context.source_ip or 'n/a'}",
            f"- Destination IP: {context.destination_ip or 'n/a'}",
            f"- Scenario type: {context.scenario_type}",
            "",
        ]

        if self._truncation_summary.any_truncated:
            lines.extend(["## Evidence Truncation", ""])
            for record in self._truncation_summary.records:
                if not record.truncated:
                    continue
                lines.append(
                    f"- `{record.evidence_type}`: retained {record.retained_count} of "
                    f"{record.original_count} (limit {record.limit})"
                )
            lines.append("")

        if s3_result.status == S3Status.S3_INCONCLUSIVE:
            lines.extend(
                [
                    "## S3 Inconclusive",
                    "",
                    "Stellar client errors or incomplete vendor data prevented a confirmed S3 result.",
                    "S2 traffic validation remains authoritative.",
                    "",
                ]
            )

        lines.extend(["## Alerts", ""])
        if evidence.alerts:
            for alert in evidence.alerts:
                lines.append(
                    f"- `{alert.alert_name}` ({alert.severity}) "
                    f"score={alert.correlation_score:.2f}"
                )
        else:
            lines.append("- (none)")

        lines.extend(["", "## Analytics", ""])
        if evidence.analytics:
            for item in evidence.analytics:
                lines.append(f"- `{item.analytic_type}` — {item.summary}")
        else:
            lines.append("- (none)")

        lines.extend(["", "## Entities", ""])
        if evidence.entities:
            for entity in evidence.entities:
                lines.append(f"- {entity.role}: {entity.entity_value} ({entity.entity_type})")
        else:
            lines.append("- (none)")

        lines.extend(["", "## Timeline", ""])
        if evidence.timeline:
            for event in evidence.timeline:
                lines.append(f"- {event.event_type}: {event.description}")
        else:
            lines.append("- (none)")

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
