"""Manifest validation per SCENARIO_MANIFEST_SPEC M1–M10."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from dsp import MANIFEST_SCHEMA_VERSION
from dsp.plugins.models import Manifest

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

CATEGORIES = frozenset(
    {"network", "dns", "web", "auth", "endpoint", "identity", "composite"}
)
PROTOCOLS = frozenset(
    {"dns_udp", "dns_tcp", "http", "https", "ssh", "smb", "ldap", "rdp", "kerberos", "tcp"}
)
TARGET_CAPABILITIES = frozenset(
    {
        "alive_host",
        "dns_resolver",
        "http_host",
        "https_host",
        "web_app",
        "ssh_host",
        "windows_host",
        "linux_host",
        "domain_controller",
        "database_server",
    }
)
FORBIDDEN_ACTIONS = frozenset(
    {
        "malware_execute",
        "privilege_escalation",
        "data_exfiltration",
        "destructive_sql",
        "valid_credential_use",
        "ransomware",
        "lateral_movement",
    }
)
AGGREGATES = frozenset({"count", "sum", "distinct_artifact", "ratio", "json_extract"})


def validate_manifest(raw: dict[str, Any], directory: Path) -> tuple[bool, str | None]:
    """Return (valid, reason)."""
    schema_version = raw.get("manifest_schema_version")
    if schema_version != MANIFEST_SCHEMA_VERSION:
        return False, "unsupported_schema_version"

    plugin_id = raw.get("id")
    if not plugin_id or not _ID_PATTERN.match(str(plugin_id)):
        return False, "invalid_id"
    if str(plugin_id) != directory.name:
        return False, "id_folder_mismatch"

    version = raw.get("version")
    if not version or not _SEMVER_PATTERN.match(str(version)):
        return False, "invalid_semver"

    for field in ("name", "description", "category", "supported_targets", "supported_protocols",
                  "validation_profile", "report_profile", "safety", "executor"):
        if field not in raw:
            return False, f"missing_required_field:{field}"

    if raw["category"] not in CATEGORIES:
        return False, "invalid_category"

    targets = raw["supported_targets"]
    requires = targets.get("requires", [])
    if not requires:
        return False, "empty_supported_targets_requires"
    for cap in requires + targets.get("optional", []):
        if cap not in TARGET_CAPABILITIES:
            pass  # warning only per spec

    protocols = raw["supported_protocols"]
    if not protocols:
        return False, "empty_supported_protocols"
    for proto in protocols:
        if proto not in PROTOCOLS:
            return False, f"unknown_protocol:{proto}"

    vp = raw["validation_profile"]
    metrics = vp.get("metrics", [])
    if not metrics:
        return False, "empty_validation_metrics"
    metric_names: set[str] = set()
    for m in metrics:
        if "name" not in m or "event_filter" not in m or "aggregate" not in m:
            return False, "invalid_metric_def"
        if m["aggregate"] not in AGGREGATES:
            return False, f"unknown_aggregate:{m['aggregate']}"
        metric_names.add(m["name"])

    success = vp.get("success", {})
    if not success:
        return False, "empty_validation_success"

    rp = raw["report_profile"]
    highlights = rp.get("highlight_metrics", [])
    if not highlights:
        return False, "empty_highlight_metrics"
    for h in highlights:
        if h not in metric_names:
            return False, f"highlight_not_in_metrics:{h}"

    safety = raw["safety"]
    if safety.get("max_events", 0) <= 0:
        return False, "invalid_max_events"
    if "max_duration_sec" not in safety:
        return False, "missing_max_duration_sec"
    forbidden = safety.get("forbidden_actions")
    if forbidden is None:
        return False, "missing_forbidden_actions"

    scenario_py = directory / "scenario.py"
    if not scenario_py.exists():
        return False, "missing_scenario_py"

    return True, None


def parse_manifest(path: Path) -> Manifest:
    import yaml

    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError("manifest must be a mapping")
    return Manifest(raw=raw, path=path)
