"""Plugin discovery, validation, and loading."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from dsp import __version__ as DSP_VERSION
from dsp.engine.scenario_engine import Scenario
from dsp.plugins.models import Manifest, PluginRecord, PluginStatus
from dsp.plugins.registry import PluginRegistry
from dsp.plugins.validator import parse_manifest, validate_manifest


def default_scenarios_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "scenarios"


class PluginLoader:
    def __init__(self, scenarios_dir: Path | None = None) -> None:
        self.scenarios_dir = scenarios_dir or default_scenarios_dir()
        self.registry = PluginRegistry()

    def discover_and_load(self) -> PluginRegistry:
        self.registry.reload()
        if not self.scenarios_dir.is_dir():
            return self.registry

        candidates: list[Path] = []
        for entry in sorted(self.scenarios_dir.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith("_") or entry.name.startswith("."):
                continue
            manifest_path = entry / "manifest.yaml"
            if not manifest_path.exists():
                continue
            candidates.append(entry)

        for directory in candidates:
            self._process_candidate(directory)

        return self.registry

    def _process_candidate(self, directory: Path) -> None:
        manifest_path = directory / "manifest.yaml"
        try:
            manifest = parse_manifest(manifest_path)
        except Exception as exc:
            record = PluginRecord(
                id=directory.name,
                manifest=Manifest(raw={"id": directory.name}, path=manifest_path),
                status=PluginStatus.REJECTED,
                status_reason=f"yaml_parse_error:{exc}",
                manifest_path=manifest_path,
            )
            self.registry.register(record)
            return

        valid, reason = validate_manifest(manifest.raw, directory)
        if not valid:
            record = PluginRecord(
                id=manifest.id,
                manifest=manifest,
                status=PluginStatus.REJECTED,
                status_reason=reason,
                manifest_path=manifest_path,
            )
            self.registry.register(record)
            return

        if not manifest.enabled:
            record = PluginRecord(
                id=manifest.id,
                manifest=manifest,
                status=PluginStatus.DISABLED,
                status_reason="enabled_false",
                manifest_path=manifest_path,
            )
            self.registry.register(record)
            return

        req = manifest.raw.get("requirements", {})
        dsp_min = req.get("dsp_min_version")
        if dsp_min and _semver_lt(DSP_VERSION, str(dsp_min)):
            record = PluginRecord(
                id=manifest.id,
                manifest=manifest,
                status=PluginStatus.UNAVAILABLE,
                status_reason="dsp_version",
                manifest_path=manifest_path,
            )
            self.registry.register(record)
            return

        scenario_class, load_error = self._load_scenario_class(directory, manifest)
        if load_error:
            status = PluginStatus.UNAVAILABLE if "import" in load_error else PluginStatus.REJECTED
            record = PluginRecord(
                id=manifest.id,
                manifest=manifest,
                status=status,
                status_reason=load_error,
                manifest_path=manifest_path,
                load_error=load_error,
            )
            self.registry.register(record)
            return

        record = PluginRecord(
            id=manifest.id,
            manifest=manifest,
            status=PluginStatus.ACTIVE,
            scenario_class=scenario_class,
            manifest_path=manifest_path,
        )
        self.registry.register(record)

    def _load_scenario_class(
        self, directory: Path, manifest: Manifest
    ) -> tuple[type | None, str | None]:
        scenario_path = directory / "scenario.py"
        module_name = f"dsp_scenario_{manifest.id}"
        spec = importlib.util.spec_from_file_location(module_name, scenario_path)
        if spec is None or spec.loader is None:
            return None, "import_error:spec_failed"

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            return None, f"import_error:{exc}"

        subclasses = [
            obj
            for obj in vars(module).values()
            if isinstance(obj, type)
            and issubclass(obj, Scenario)
            and obj is not Scenario
        ]
        if len(subclasses) == 0:
            return None, "no_scenario_class"
        if len(subclasses) > 1:
            return None, "ambiguous_scenario_class"

        scenario_class = subclasses[0]
        try:
            sid = scenario_class.scenario_id()
        except Exception as exc:
            return None, f"id_mismatch:{exc}"
        if sid != manifest.id:
            return None, "id_mismatch"

        packages = manifest.raw.get("requirements", {}).get("packages", [])
        for pkg in packages:
            try:
                importlib.import_module(str(pkg).split("[")[0].replace("-", "_"))
            except ImportError:
                return None, f"missing_package:{pkg}"

        return scenario_class, None


def _semver_lt(a: str, b: str) -> bool:
    def parse(v: str) -> tuple[int, int, int]:
        parts = v.split(".")
        return int(parts[0]), int(parts[1]), int(parts[2])

    return parse(a) < parse(b)
