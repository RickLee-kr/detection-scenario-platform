"""Externalized scenario mapping loader — no hardcoded scenario rules in adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DEFAULT_MAPPING_PATH = Path(__file__).resolve().parent / "scenario_mapping.yaml"


@dataclass
class ScenarioDetectionMapping:
    scenario_id: str
    detection_model_id: str
    alert_families: list[str] = field(default_factory=list)
    analytics_types: list[str] = field(default_factory=list)
    correlation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "detection_model_id": self.detection_model_id,
            "alert_families": self.alert_families,
            "analytics_types": self.analytics_types,
            "correlation": self.correlation,
        }


@dataclass
class StellarMappingRegistry:
    version: str
    vendor: str
    scenarios: dict[str, ScenarioDetectionMapping]

    def get(self, scenario_id: str) -> ScenarioDetectionMapping | None:
        return self.scenarios.get(scenario_id)

    def supported_scenarios(self) -> list[str]:
        return sorted(self.scenarios.keys())


def load_stellar_mapping(path: Path | None = None) -> StellarMappingRegistry:
    """Load scenario mapping from YAML file."""
    import yaml

    mapping_path = path or _DEFAULT_MAPPING_PATH
    raw = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))

    scenarios: dict[str, ScenarioDetectionMapping] = {}
    for scenario_id, cfg in raw.get("scenarios", {}).items():
        scenarios[scenario_id] = ScenarioDetectionMapping(
            scenario_id=scenario_id,
            detection_model_id=cfg["detection_model_id"],
            alert_families=list(cfg.get("alert_families", [])),
            analytics_types=list(cfg.get("analytics_types", [])),
            correlation=dict(cfg.get("correlation", {})),
        )

    return StellarMappingRegistry(
        version=str(raw.get("version", "1.0.0")),
        vendor=str(raw.get("vendor", "stellar")),
        scenarios=scenarios,
    )
