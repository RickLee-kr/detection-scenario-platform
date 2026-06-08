"""Build Stellar API queries from scenario contracts and correlation context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from dsp.detection.models import CorrelationContext
from dsp.detection.providers.stellar.client_base import StellarSearchParams
from dsp.detection.providers.stellar.contracts.contract_loader import (
    EvidenceSource,
    QueryDimensionPriority,
    ScenarioContract,
)
from dsp.detection.providers.stellar.stellar_mapping import ScenarioDetectionMapping

ENDPOINT_PATHS = {
    EvidenceSource.ALERT: "/api/v1/detection/alerts",
    EvidenceSource.ANALYTICS: "/api/v1/detection/analytics",
    EvidenceSource.ENTITY: "/api/v1/detection/entities",
    EvidenceSource.TIMELINE: "/api/v1/detection/timeline",
}

# Analytics queries may carry nested filters — prefer POST.
POST_EVIDENCE_TYPES = frozenset({EvidenceSource.ANALYTICS})


@dataclass
class StellarApiQuery:
    """HTTP-ready Stellar API request descriptor."""

    evidence_type: EvidenceSource
    path: str
    method: str
    params: dict[str, Any] = field(default_factory=dict)


def apply_contract_time_window(
    context: CorrelationContext,
    contract: ScenarioContract,
) -> tuple[datetime, datetime]:
    """Derive API search window; ensures at least contract.search_window_minutes span."""
    start = context.time_window_start
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)

    end = context.time_window_end
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    min_end = start + timedelta(minutes=contract.search_window_minutes)
    if end < min_end:
        end = min_end
    return start, end


def _protocol_from_mapping(mapping: ScenarioDetectionMapping | None) -> str | None:
    if mapping is None:
        return None
    return mapping.correlation.get("protocol")


def _port_for_protocol(protocol: str | None) -> int | None:
    if protocol == "dns":
        return 53
    if protocol == "ssh":
        return 22
    if protocol == "http":
        return 80
    return None


def build_api_query(
    *,
    context: CorrelationContext,
    contract: ScenarioContract,
    evidence_type: EvidenceSource,
    mapping: ScenarioDetectionMapping | None = None,
    hostname: str | None = None,
    username: str | None = None,
) -> StellarApiQuery:
    """Construct a single Stellar API query for one evidence type."""
    window_start, window_end = apply_contract_time_window(context, contract)
    protocol = _protocol_from_mapping(mapping)
    port = _port_for_protocol(protocol)

    params: dict[str, Any] = {
        "run_id": context.run_id,
        "scenario_id": context.scenario_id,
        "start": window_start.isoformat().replace("+00:00", "Z"),
        "end": window_end.isoformat().replace("+00:00", "Z"),
        "detection_model_id": contract.detection_model_id,
        "category": contract.category,
    }

    dimensions = contract.query_dimensions

    if context.source_ip and dimensions.get("source_ip") != QueryDimensionPriority.NICE_TO_HAVE:
        params["source_ip"] = context.source_ip
    if context.destination_ip and dimensions.get("destination_ip") in {
        QueryDimensionPriority.REQUIRED,
        QueryDimensionPriority.OPTIONAL,
    }:
        params["destination_ip"] = context.destination_ip
    if hostname and dimensions.get("hostname") in {
        QueryDimensionPriority.REQUIRED,
        QueryDimensionPriority.OPTIONAL,
    }:
        params["hostname"] = hostname
    if username and dimensions.get("username") in {
        QueryDimensionPriority.REQUIRED,
        QueryDimensionPriority.OPTIONAL,
    }:
        params["username"] = username
    if protocol and dimensions.get("protocol") == QueryDimensionPriority.REQUIRED:
        params["protocol"] = protocol
    if port is not None and dimensions.get("port") == QueryDimensionPriority.REQUIRED:
        params["port"] = port

    if evidence_type == EvidenceSource.ALERT and contract.alert_families:
        params["alert_families"] = list(contract.alert_families)
    if evidence_type == EvidenceSource.ANALYTICS and contract.analytics_types:
        params["analytics_types"] = list(contract.analytics_types)
    if evidence_type == EvidenceSource.ENTITY and contract.entity_types:
        params["entity_types"] = list(contract.entity_types)

    method = "POST" if evidence_type in POST_EVIDENCE_TYPES else "GET"
    path = ENDPOINT_PATHS[evidence_type]

    return StellarApiQuery(
        evidence_type=evidence_type,
        path=path,
        method=method,
        params=params,
    )


def build_search_params(
    *,
    context: CorrelationContext,
    contract: ScenarioContract,
    evidence_type: EvidenceSource,
    mapping: ScenarioDetectionMapping | None = None,
    hostname: str | None = None,
    username: str | None = None,
) -> StellarSearchParams:
    """Build StellarSearchParams with contract-driven query for one evidence type."""
    api_query = build_api_query(
        context=context,
        contract=contract,
        evidence_type=evidence_type,
        mapping=mapping,
        hostname=hostname,
        username=username,
    )
    protocol = _protocol_from_mapping(mapping)
    port = _port_for_protocol(protocol)

    return StellarSearchParams(
        context=context,
        detection_model_id=contract.detection_model_id,
        alert_families=list(contract.alert_families),
        analytics_types=list(contract.analytics_types),
        correlation=dict(mapping.correlation if mapping else {}),
        query=dict(api_query.params),
        http_method=api_query.method,
        api_path=api_query.path,
        evidence_type=evidence_type.value,
        category=contract.category,
        entity_types=list(contract.entity_types),
        protocol=protocol,
        port=port,
    )


def evidence_types_to_query(
    contract: ScenarioContract,
    *,
    include_optional: bool = False,
) -> list[EvidenceSource]:
    """Return evidence types to query — required only unless include_optional."""
    types = list(contract.required_evidence)
    if include_optional:
        for optional in contract.optional_evidence:
            if optional not in types:
                types.append(optional)
    return types
