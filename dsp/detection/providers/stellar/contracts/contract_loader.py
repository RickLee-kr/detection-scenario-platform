"""Load and validate Stellar scenario detection contracts from YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_DEFAULT_CONTRACTS_PATH = Path(__file__).resolve().parent / "scenario_contracts.yaml"

IMPLEMENTED_SCENARIOS = frozenset(
    {
        "dns_tunnel",
        "dga",
        "http_followup",
        "ssh_failure",
        "sql_injection",
        "smb_login_failure",
        "port_sweep",
        "ldap_enumeration",
        "kerberos_failure",
    }
)

_REQUIRED_SCENARIO_FIELDS = frozenset(
    {
        "category",
        "confidence",
        "search_window_minutes",
        "required_evidence",
        "detection_model_id",
        "entity_types",
        "analytics_types",
        "query_dimensions",
    }
)


class ScenarioContractValidationError(ValueError):
    """Raised when scenario contract YAML fails validation."""


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EvidenceSource(str, Enum):
    ALERT = "alert"
    ANALYTICS = "analytics"
    ENTITY = "entity"
    TIMELINE = "timeline"


class QueryDimensionPriority(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    NICE_TO_HAVE = "nice_to_have"


@dataclass
class ScenarioContract:
    scenario_id: str
    category: str
    confidence: ConfidenceLevel
    search_window_minutes: int
    required_evidence: list[EvidenceSource]
    detection_model_id: str
    entity_types: list[str] = field(default_factory=list)
    analytics_types: list[str] = field(default_factory=list)
    optional_evidence: list[EvidenceSource] = field(default_factory=list)
    alert_families: list[str] = field(default_factory=list)
    query_dimensions: dict[str, QueryDimensionPriority] = field(default_factory=dict)
    fallback: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "category": self.category,
            "confidence": self.confidence.value,
            "search_window_minutes": self.search_window_minutes,
            "required_evidence": [e.value for e in self.required_evidence],
            "optional_evidence": [e.value for e in self.optional_evidence],
            "detection_model_id": self.detection_model_id,
            "entity_types": self.entity_types,
            "analytics_types": self.analytics_types,
            "alert_families": self.alert_families,
            "query_dimensions": {k: v.value for k, v in self.query_dimensions.items()},
            "fallback": self.fallback,
        }


@dataclass
class ScenarioContractRegistry:
    version: str
    vendor: str
    scenarios: dict[str, ScenarioContract]

    def get(self, scenario_id: str) -> ScenarioContract | None:
        return self.scenarios.get(scenario_id)

    def supported_scenarios(self) -> list[str]:
        return sorted(self.scenarios.keys())


def _parse_confidence(value: Any, *, scenario_id: str) -> ConfidenceLevel:
    if value is None:
        raise ScenarioContractValidationError(
            f"{scenario_id}: missing required field 'confidence'"
        )
    try:
        return ConfidenceLevel(str(value).upper())
    except ValueError as exc:
        allowed = ", ".join(c.value for c in ConfidenceLevel)
        raise ScenarioContractValidationError(
            f"{scenario_id}: invalid confidence '{value}'; expected one of: {allowed}"
        ) from exc


def _parse_evidence_sources(
    values: Any,
    *,
    scenario_id: str,
    field_name: str,
) -> list[EvidenceSource]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ScenarioContractValidationError(
            f"{scenario_id}: '{field_name}' must be a list"
        )
    sources: list[EvidenceSource] = []
    for item in values:
        try:
            sources.append(EvidenceSource(str(item).lower()))
        except ValueError as exc:
            allowed = ", ".join(e.value for e in EvidenceSource)
            raise ScenarioContractValidationError(
                f"{scenario_id}: invalid {field_name} entry '{item}'; "
                f"expected one of: {allowed}"
            ) from exc
    return sources


def _parse_query_dimensions(
    raw: Any,
    *,
    scenario_id: str,
) -> dict[str, QueryDimensionPriority]:
    if raw is None:
        raise ScenarioContractValidationError(
            f"{scenario_id}: missing required field 'query_dimensions'"
        )
    if not isinstance(raw, dict):
        raise ScenarioContractValidationError(
            f"{scenario_id}: 'query_dimensions' must be a mapping"
        )
    dimensions: dict[str, QueryDimensionPriority] = {}
    for key, value in raw.items():
        try:
            dimensions[str(key)] = QueryDimensionPriority(str(value).lower())
        except ValueError as exc:
            allowed = ", ".join(p.value for p in QueryDimensionPriority)
            raise ScenarioContractValidationError(
                f"{scenario_id}: invalid query dimension priority for '{key}': "
                f"'{value}'; expected one of: {allowed}"
            ) from exc
    return dimensions


def _parse_scenario_contract(scenario_id: str, cfg: Any) -> ScenarioContract:
    if not isinstance(cfg, dict):
        raise ScenarioContractValidationError(
            f"{scenario_id}: scenario entry must be a mapping"
        )

    missing = _REQUIRED_SCENARIO_FIELDS - set(cfg.keys())
    if missing:
        raise ScenarioContractValidationError(
            f"{scenario_id}: missing required fields: {', '.join(sorted(missing))}"
        )

    required_evidence = _parse_evidence_sources(
        cfg["required_evidence"],
        scenario_id=scenario_id,
        field_name="required_evidence",
    )
    if not required_evidence:
        raise ScenarioContractValidationError(
            f"{scenario_id}: 'required_evidence' must contain at least one entry"
        )

    search_window = cfg["search_window_minutes"]
    if not isinstance(search_window, int) or search_window <= 0:
        raise ScenarioContractValidationError(
            f"{scenario_id}: 'search_window_minutes' must be a positive integer"
        )

    return ScenarioContract(
        scenario_id=scenario_id,
        category=str(cfg["category"]),
        confidence=_parse_confidence(cfg["confidence"], scenario_id=scenario_id),
        search_window_minutes=search_window,
        required_evidence=required_evidence,
        optional_evidence=_parse_evidence_sources(
            cfg.get("optional_evidence", []),
            scenario_id=scenario_id,
            field_name="optional_evidence",
        ),
        detection_model_id=str(cfg["detection_model_id"]),
        entity_types=list(cfg.get("entity_types", [])),
        analytics_types=list(cfg.get("analytics_types", [])),
        alert_families=list(cfg.get("alert_families", [])),
        query_dimensions=_parse_query_dimensions(
            cfg["query_dimensions"],
            scenario_id=scenario_id,
        ),
        fallback=dict(cfg.get("fallback", {})),
    )


def validate_scenario_contracts(registry: ScenarioContractRegistry) -> None:
    """Ensure registry covers all implemented scenarios with valid contracts."""
    missing = IMPLEMENTED_SCENARIOS - set(registry.scenarios.keys())
    if missing:
        raise ScenarioContractValidationError(
            f"contract registry missing implemented scenarios: {', '.join(sorted(missing))}"
        )

    for scenario_id, contract in registry.scenarios.items():
        if contract.scenario_id != scenario_id:
            raise ScenarioContractValidationError(
                f"scenario key '{scenario_id}' does not match contract.scenario_id "
                f"'{contract.scenario_id}'"
            )
        if "time_range" not in contract.query_dimensions:
            raise ScenarioContractValidationError(
                f"{scenario_id}: query_dimensions must include 'time_range'"
            )
        if contract.query_dimensions["time_range"] != QueryDimensionPriority.REQUIRED:
            raise ScenarioContractValidationError(
                f"{scenario_id}: 'time_range' query dimension must be required"
            )


def load_scenario_contracts(
    path: Path | None = None,
    *,
    validate: bool = True,
) -> ScenarioContractRegistry:
    """Load scenario contracts from YAML and optionally validate."""
    import yaml

    contract_path = path or _DEFAULT_CONTRACTS_PATH
    raw = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ScenarioContractValidationError("contract file root must be a mapping")

    scenarios_raw = raw.get("scenarios")
    if not isinstance(scenarios_raw, dict):
        raise ScenarioContractValidationError("'scenarios' must be a mapping")

    scenarios: dict[str, ScenarioContract] = {}
    for scenario_id, cfg in scenarios_raw.items():
        scenarios[scenario_id] = _parse_scenario_contract(scenario_id, cfg)

    registry = ScenarioContractRegistry(
        version=str(raw.get("version", "1.0.0")),
        vendor=str(raw.get("vendor", "stellar")),
        scenarios=scenarios,
    )

    if validate:
        validate_scenario_contracts(registry)

    return registry
