"""Normalize Stellar vendor responses into vendor-neutral evidence."""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from dsp.detection.models import (
    AlertEvidence,
    AnalyticsEvidence,
    CorrelationContext,
    EntityEvidence,
    EvidencePack,
    TimelineEvidence,
)

_SECRET_KEY_PATTERN = re.compile(
    r"(token|secret|password|authorization|api_key|apikey)",
    re.IGNORECASE,
)

_DEFAULT_ALIASES_PATH = Path(__file__).resolve().parent / "stellar_aliases.yaml"


@lru_cache(maxsize=1)
def _load_alias_registry(path: str | None = None) -> dict[str, list[str]]:
    import yaml

    alias_path = Path(path) if path else _DEFAULT_ALIASES_PATH
    if not alias_path.exists():
        return {}
    raw = yaml.safe_load(alias_path.read_text(encoding="utf-8")) or {}
    fields = raw.get("fields", {})
    registry: dict[str, list[str]] = {}
    if not isinstance(fields, dict):
        return registry
    for canonical, cfg in fields.items():
        if isinstance(cfg, dict):
            aliases = cfg.get("aliases", [])
            if isinstance(aliases, list):
                registry[str(canonical)] = [str(a) for a in aliases]
    return registry


def resolve_field(record: dict[str, Any], canonical: str, *, aliases_path: str | None = None) -> Any:
    """Return first matching value for canonical field using alias registry."""
    registry = _load_alias_registry(aliases_path)
    keys = registry.get(canonical, [canonical])
    if canonical not in keys:
        keys = [canonical, *keys]
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def apply_aliases(record: dict[str, Any], *, aliases_path: str | None = None) -> dict[str, Any]:
    """Return a shallow copy with canonical field names populated from aliases."""
    registry = _load_alias_registry(aliases_path)
    if not registry:
        return record
    normalized = dict(record)
    for canonical, alias_keys in registry.items():
        if canonical in normalized and normalized[canonical] not in (None, ""):
            continue
        for key in alias_keys:
            if key in record and record[key] not in (None, ""):
                normalized[canonical] = record[key]
                break
    return normalized


def _parse_observed_at(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _entity_refs_from_record(record: dict[str, Any], *, aliases_path: str | None = None) -> list[str]:
    refs = resolve_field(record, "entity_refs", aliases_path=aliases_path)
    if isinstance(refs, list):
        return [str(v) for v in refs if v not in (None, "")]
    return []


def sanitize_raw_record(record: dict[str, Any]) -> dict[str, Any]:
    """Redact secret-like keys from raw vendor JSON before persisting."""
    sanitized: dict[str, Any] = {}
    for key, value in record.items():
        if _SECRET_KEY_PATTERN.search(str(key)):
            sanitized[key] = "***REDACTED***"
        elif isinstance(value, dict):
            sanitized[key] = sanitize_raw_record(value)
        elif isinstance(value, list):
            sanitized[key] = [
                sanitize_raw_record(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            sanitized[key] = value
    return sanitized


def sanitize_raw_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [sanitize_raw_record(copy.deepcopy(item)) for item in items]


def normalize_alerts(
    items: list[dict[str, Any]],
    *,
    context: CorrelationContext,
    vendor: str = "stellar",
    collected_at: datetime | None = None,
    aliases_path: str | None = None,
) -> list[AlertEvidence]:
    now = collected_at or datetime.now(timezone.utc)
    alerts: list[AlertEvidence] = []
    for raw in items:
        item = apply_aliases(raw, aliases_path=aliases_path)
        alert_id = str(resolve_field(item, "id", aliases_path=aliases_path) or "")
        if not alert_id:
            continue
        alerts.append(
            AlertEvidence(
                evidence_id=alert_id,
                vendor=vendor,
                collected_at=now,
                run_id=context.run_id,
                scenario_id=context.scenario_id,
                alert_name=str(resolve_field(item, "alert_name", aliases_path=aliases_path) or ""),
                severity=str(resolve_field(item, "severity", aliases_path=aliases_path) or ""),
                observed_at=_parse_observed_at(
                    resolve_field(item, "observed_at", aliases_path=aliases_path)
                ),
                entity_refs=_entity_refs_from_record(item, aliases_path=aliases_path),
                raw_ref=alert_id,
                attributes={
                    "detection_model_id": resolve_field(
                        item, "detection_model_id", aliases_path=aliases_path
                    ),
                },
            )
        )
    return alerts


def normalize_analytics(
    items: list[dict[str, Any]],
    *,
    context: CorrelationContext,
    vendor: str = "stellar",
    collected_at: datetime | None = None,
    aliases_path: str | None = None,
) -> list[AnalyticsEvidence]:
    now = collected_at or datetime.now(timezone.utc)
    analytics: list[AnalyticsEvidence] = []
    for raw in items:
        item = apply_aliases(raw, aliases_path=aliases_path)
        incident_id = str(resolve_field(item, "id", aliases_path=aliases_path) or "")
        if not incident_id:
            continue
        analytics.append(
            AnalyticsEvidence(
                evidence_id=incident_id,
                vendor=vendor,
                collected_at=now,
                run_id=context.run_id,
                scenario_id=context.scenario_id,
                analytic_type=str(
                    resolve_field(item, "analytic_type", aliases_path=aliases_path) or ""
                ),
                incident_id=incident_id,
                observed_at=_parse_observed_at(
                    resolve_field(item, "observed_at", aliases_path=aliases_path)
                ),
                summary=str(resolve_field(item, "summary", aliases_path=aliases_path) or ""),
                raw_ref=incident_id,
                attributes={
                    "detection_model_id": resolve_field(
                        item, "detection_model_id", aliases_path=aliases_path
                    ),
                },
            )
        )
    return analytics


def normalize_entities(
    items: list[dict[str, Any]],
    *,
    context: CorrelationContext,
    vendor: str = "stellar",
    collected_at: datetime | None = None,
    aliases_path: str | None = None,
) -> list[EntityEvidence]:
    now = collected_at or datetime.now(timezone.utc)
    entities: list[EntityEvidence] = []
    for raw in items:
        item = apply_aliases(raw, aliases_path=aliases_path)
        entity_id = str(resolve_field(item, "id", aliases_path=aliases_path) or "")
        if not entity_id:
            continue
        entities.append(
            EntityEvidence(
                evidence_id=entity_id,
                vendor=vendor,
                collected_at=now,
                run_id=context.run_id,
                scenario_id=context.scenario_id,
                entity_type=str(
                    resolve_field(item, "entity_type", aliases_path=aliases_path) or ""
                ),
                entity_value=str(
                    resolve_field(item, "entity_value", aliases_path=aliases_path) or ""
                ),
                role=str(resolve_field(item, "role", aliases_path=aliases_path) or ""),
                raw_ref=entity_id,
            )
        )
    return entities


def normalize_timeline(
    items: list[dict[str, Any]],
    *,
    context: CorrelationContext,
    vendor: str = "stellar",
    collected_at: datetime | None = None,
    aliases_path: str | None = None,
) -> list[TimelineEvidence]:
    now = collected_at or datetime.now(timezone.utc)
    timeline: list[TimelineEvidence] = []
    for raw in items:
        item = apply_aliases(raw, aliases_path=aliases_path)
        event_id = str(resolve_field(item, "id", aliases_path=aliases_path) or "")
        if not event_id:
            continue
        timeline.append(
            TimelineEvidence(
                evidence_id=event_id,
                vendor=vendor,
                collected_at=now,
                run_id=context.run_id,
                scenario_id=context.scenario_id,
                event_type=str(
                    resolve_field(item, "event_type", aliases_path=aliases_path) or ""
                ),
                observed_at=_parse_observed_at(
                    resolve_field(item, "observed_at", aliases_path=aliases_path)
                ),
                description=str(
                    resolve_field(item, "description", aliases_path=aliases_path) or ""
                ),
                raw_ref=event_id,
            )
        )
    return timeline


def build_evidence_pack(
    *,
    context: CorrelationContext,
    alerts: list[dict[str, Any]],
    analytics: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    vendor: str = "stellar",
    aliases_path: str | None = None,
) -> EvidencePack:
    """Build vendor-neutral EvidencePack from normalized search results."""
    return EvidencePack(
        run_id=context.run_id,
        scenario_id=context.scenario_id,
        vendor=vendor,
        alerts=normalize_alerts(alerts, context=context, vendor=vendor, aliases_path=aliases_path),
        analytics=normalize_analytics(
            analytics, context=context, vendor=vendor, aliases_path=aliases_path
        ),
        entities=normalize_entities(
            entities, context=context, vendor=vendor, aliases_path=aliases_path
        ),
        timeline=normalize_timeline(
            timeline, context=context, vendor=vendor, aliases_path=aliases_path
        ),
    )


def normalization_counts(evidence: EvidencePack) -> dict[str, int]:
    """Return normalized evidence counts by type."""
    return {
        "alerts": len(evidence.alerts),
        "analytics": len(evidence.analytics),
        "entities": len(evidence.entities),
        "timeline": len(evidence.timeline),
        "total": evidence.evidence_count,
    }
