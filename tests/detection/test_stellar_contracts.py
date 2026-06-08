"""Tests for Stellar scenario detection contracts (Phase 10)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dsp.detection.providers.stellar.contracts import (
    IMPLEMENTED_SCENARIOS,
    ConfidenceLevel,
    ScenarioContractValidationError,
    load_scenario_contracts,
    validate_scenario_contracts,
)
from dsp.detection.providers.stellar.contracts.contract_loader import (
    ScenarioContractRegistry,
)


def test_scenario_contracts_load_correctly():
    registry = load_scenario_contracts()
    assert registry.vendor == "stellar"
    assert registry.version == "1.0.0"
    assert registry.supported_scenarios() == sorted(IMPLEMENTED_SCENARIOS)


def test_all_implemented_scenarios_exist():
    registry = load_scenario_contracts()
    for scenario_id in IMPLEMENTED_SCENARIOS:
        contract = registry.get(scenario_id)
        assert contract is not None, f"missing contract for {scenario_id}"
        assert contract.scenario_id == scenario_id


@pytest.mark.parametrize("scenario_id", sorted(IMPLEMENTED_SCENARIOS))
def test_required_contract_fields_exist(scenario_id: str):
    contract = load_scenario_contracts().get(scenario_id)
    assert contract is not None
    assert contract.category
    assert contract.detection_model_id.startswith("stellar.")
    assert contract.search_window_minutes > 0
    assert len(contract.required_evidence) >= 1
    assert "time_range" in contract.query_dimensions
    assert contract.confidence in ConfidenceLevel


def test_dns_tunnel_contract_details():
    contract = load_scenario_contracts().get("dns_tunnel")
    assert contract is not None
    assert contract.category == "DNS Tunnel"
    assert contract.confidence == ConfidenceLevel.HIGH
    assert contract.search_window_minutes == 30
    evidence_types = {e.value for e in contract.required_evidence}
    assert evidence_types == {"alert", "analytics", "entity"}


def test_malformed_contract_missing_scenarios_key(tmp_path: Path):
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text("version: '1.0.0'\nvendor: stellar\n", encoding="utf-8")
    with pytest.raises(ScenarioContractValidationError, match="scenarios"):
        load_scenario_contracts(bad_file, validate=False)


def test_malformed_contract_missing_required_field(tmp_path: Path):
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text(
        yaml.dump(
            {
                "version": "1.0.0",
                "vendor": "stellar",
                "scenarios": {
                    "dns_tunnel": {
                        "category": "DNS Tunnel",
                        "confidence": "HIGH",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ScenarioContractValidationError, match="missing required fields"):
        load_scenario_contracts(bad_file, validate=False)


def test_malformed_contract_invalid_confidence(tmp_path: Path):
    base = load_scenario_contracts()
    raw = {
        "version": base.version,
        "vendor": base.vendor,
        "scenarios": {
            "dns_tunnel": {
                "category": "DNS Tunnel",
                "confidence": "VERY_HIGH",
                "search_window_minutes": 30,
                "required_evidence": ["alert"],
                "detection_model_id": "stellar.dns_tunnel",
                "entity_types": ["ip"],
                "analytics_types": ["dns_query_volume_anomaly"],
                "query_dimensions": {"time_range": "required"},
            }
        },
    }
    bad_file = tmp_path / "bad_confidence.yaml"
    bad_file.write_text(yaml.dump(raw), encoding="utf-8")
    with pytest.raises(ScenarioContractValidationError, match="invalid confidence"):
        load_scenario_contracts(bad_file, validate=False)


def test_malformed_contract_invalid_evidence_source(tmp_path: Path):
    raw = {
        "version": "1.0.0",
        "vendor": "stellar",
        "scenarios": {
            "dga": {
                "category": "DGA",
                "confidence": "HIGH",
                "search_window_minutes": 30,
                "required_evidence": ["alert", "unknown_type"],
                "detection_model_id": "stellar.dga",
                "entity_types": ["ip"],
                "analytics_types": ["nxdomain_burst"],
                "query_dimensions": {"time_range": "required"},
            }
        },
    }
    bad_file = tmp_path / "bad_evidence.yaml"
    bad_file.write_text(yaml.dump(raw), encoding="utf-8")
    with pytest.raises(ScenarioContractValidationError, match="invalid required_evidence"):
        load_scenario_contracts(bad_file, validate=False)


def test_validation_fails_when_implemented_scenario_missing(tmp_path: Path):
    registry = ScenarioContractRegistry(
        version="1.0.0",
        vendor="stellar",
        scenarios={},
    )
    with pytest.raises(ScenarioContractValidationError, match="missing implemented scenarios"):
        validate_scenario_contracts(registry)


def test_confidence_enum_validation_accepts_all_levels(tmp_path: Path):
    for level in ("HIGH", "MEDIUM", "LOW"):
        raw = {
            "version": "1.0.0",
            "vendor": "stellar",
            "scenarios": {
                "dns_tunnel": {
                    "category": "DNS Tunnel",
                    "confidence": level,
                    "search_window_minutes": 30,
                    "required_evidence": ["alert"],
                    "detection_model_id": "stellar.dns_tunnel",
                    "entity_types": ["ip"],
                    "analytics_types": ["dns_query_volume_anomaly"],
                    "query_dimensions": {"time_range": "required"},
                },
                "dga": {
                    "category": "DGA",
                    "confidence": "HIGH",
                    "search_window_minutes": 30,
                    "required_evidence": ["alert"],
                    "detection_model_id": "stellar.dga",
                    "entity_types": ["ip"],
                    "analytics_types": ["nxdomain_burst"],
                    "query_dimensions": {"time_range": "required"},
                },
                "http_followup": {
                    "category": "HTTP Reconnaissance",
                    "confidence": "HIGH",
                    "search_window_minutes": 15,
                    "required_evidence": ["alert"],
                    "detection_model_id": "stellar.http_recon",
                    "entity_types": ["ip"],
                    "analytics_types": ["http_path_enumeration"],
                    "query_dimensions": {"time_range": "required"},
                },
                "ssh_failure": {
                    "category": "SSH Login Failure",
                    "confidence": "HIGH",
                    "search_window_minutes": 30,
                    "required_evidence": ["alert"],
                    "detection_model_id": "stellar.ssh_login_failure",
                    "entity_types": ["ip"],
                    "analytics_types": ["ssh_auth_failure_burst"],
                    "query_dimensions": {"time_range": "required"},
                },
                "sql_injection": {
                    "category": "SQL Injection",
                    "confidence": "HIGH",
                    "search_window_minutes": 15,
                    "required_evidence": ["alert"],
                    "detection_model_id": "stellar.sql_injection",
                    "entity_types": ["ip"],
                    "analytics_types": ["sqli_payload_detected"],
                    "query_dimensions": {"time_range": "required"},
                },
                "smb_login_failure": {
                    "category": "SMB Authentication Failure",
                    "confidence": "HIGH",
                    "search_window_minutes": 30,
                    "required_evidence": ["alert", "entity"],
                    "detection_model_id": "stellar.smb_login_failure",
                    "entity_types": ["ip", "host", "user"],
                    "analytics_types": ["smb_auth_failure_burst"],
                    "query_dimensions": {"time_range": "required"},
                },
                "port_sweep": {
                    "category": "Port Sweep",
                    "confidence": "HIGH",
                    "search_window_minutes": 30,
                    "required_evidence": ["alert", "entity"],
                    "detection_model_id": "stellar.port_sweep",
                    "entity_types": ["ip", "host"],
                    "analytics_types": ["port_scan_burst"],
                    "query_dimensions": {"time_range": "required"},
                },
                "ldap_enumeration": {
                    "category": "LDAP Enumeration",
                    "confidence": "MEDIUM",
                    "search_window_minutes": 30,
                    "required_evidence": ["alert", "entity"],
                    "detection_model_id": "stellar.ldap_enumeration",
                    "entity_types": ["ip", "host"],
                    "analytics_types": ["ldap_query_burst"],
                    "query_dimensions": {"time_range": "required"},
                },
                "kerberos_failure": {
                    "category": "Kerberos Authentication Failure",
                    "confidence": "HIGH",
                    "search_window_minutes": 30,
                    "required_evidence": ["alert", "entity"],
                    "detection_model_id": "stellar.kerberos_failure",
                    "entity_types": ["ip", "host", "user"],
                    "analytics_types": ["kerberos_auth_failure_burst"],
                    "query_dimensions": {"time_range": "required"},
                },
            },
        }
        path = tmp_path / f"confidence_{level.lower()}.yaml"
        path.write_text(yaml.dump(raw), encoding="utf-8")
        contract = load_scenario_contracts(path).get("dns_tunnel")
        assert contract is not None
        assert contract.confidence.value == level
