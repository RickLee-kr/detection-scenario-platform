# DSP Runtime Dependency Audit

**Project:** Detection Scenario Platform (DSP)  
**Audit date:** 2026-06-07  
**Scope:** All Python imports under `detection-scenario-platform/` (`dsp/`, `scenarios/`, `tests/`)  
**Python target:** 3.12 (Ubuntu 24.04)  
**Source of truth:** Static AST analysis of 296 `.py` files + `pyproject.toml` + import-chain verification with `python3.12 -S` (no site-packages)

---

## Executive Summary

| Category | Count | Blocks clean Ubuntu 24.04 runtime? |
|----------|------:|-------------------------------------|
| Python standard library | 38 top-level modules | No (with full `python3.12` package) |
| Third-party runtime | **1** (`yaml` / PyYAML) | **Yes** |
| Third-party development | **1** (`pytest`) | No (test-only) |
| Build system | **1** (`hatchling`) | Yes for `pip install` (not runtime) |
| External OS binaries | **2** (`ssh`, `ldapsearch`) | Scenario-specific, not core CLI |

DSP has an exceptionally lean third-party footprint: **PyYAML is the only non-stdlib Python package imported by runtime code.** As of the runtime dependency hardening pass (2026-06-07), PyYAML is **lazy-imported** and no longer blocks module import. It is still required when YAML files are actually read (manifest loading, Stellar contract/mapping/alias files).

---

## Runtime Dependency Hardening (2026-06-07)

Module-level `import yaml` was converted to function-scoped lazy imports in:

| File | Lazy import location | Trigger |
|------|---------------------|---------|
| `dsp/plugins/validator.py` | `parse_manifest()` | Reading `scenarios/*/manifest.yaml` |
| `dsp/detection/providers/stellar/contracts/contract_loader.py` | `load_scenario_contracts()` | Reading `scenario_contracts.yaml` |
| `dsp/detection/providers/stellar/stellar_mapping.py` | `load_stellar_mapping()` | Reading `scenario_mapping.yaml` |
| `dsp/detection/providers/stellar/normalization.py` | `_load_alias_registry()` | Reading `stellar_aliases.yaml` |

### Import paths that work without PyYAML (`python3.12 -S`)

Verified 2026-06-07 after hardening:

| Module | Status |
|--------|--------|
| `dsp.event_store` | OK |
| `dsp.evidence` | OK |
| `dsp.manual_verification` | OK |
| `dsp.execution.remote` | OK |
| `dsp.runner.cli` | OK (import only) |
| `dsp.runner.run_manager` | OK (import only) |
| `dsp.plugins.loader` | OK (import only) |
| `dsp.detection.providers.stellar.stellar_adapter` | OK (import only) |

`yaml` is not loaded into `sys.modules` after any of the above imports.

### Call paths that still require PyYAML (and why)

| Call path | YAML file | Why PyYAML is required |
|-----------|-----------|------------------------|
| `parse_manifest(path)` | `scenarios/*/manifest.yaml` | Manifest format is YAML; unchanged by design |
| `PluginLoader.discover_and_load()` | via `parse_manifest()` | Parses each scenario manifest; without PyYAML, plugins are rejected with `yaml_parse_error:*` |
| `load_scenario_contracts()` | `scenario_contracts.yaml` | Stellar S3 contract definitions |
| `load_stellar_mapping()` | `scenario_mapping.yaml` | Stellar scenario→detection-model mapping |
| `_load_alias_registry()` / `resolve_field()` / normalization | `stellar_aliases.yaml` | Vendor field alias registry |
| `StellarAdapter(...)` | contracts + mapping YAML | `__init__` calls both loaders by default |
| `create_detection_adapter(stellar_client="mock"\|"http")` | via `StellarAdapter()` | Instantiates adapter which loads YAML |
| `dsp run --confirm-detection --stellar-client mock\|http` | via adapter init | Full S3 confirmation path |
| Tests using `import yaml` directly | fixtures | Test-only (`tests/plugins/`, `tests/detection/test_stellar_contracts.py`) |

### Call paths that do NOT require PyYAML

| Call path | Notes |
|-----------|-------|
| `dsp --version` | CLI module imports without loading YAML |
| `dsp run --scenarios dummy --dry-run` (no `--confirm-detection`) | Uses `ManualDetectionAdapter`; no Stellar YAML loaders |
| Core packages: event_store, evidence, manual_verification, execution.remote | No YAML dependency in import chain |
| `create_detection_adapter(stellar_client="manual")` | Uses `ManualDetectionAdapter`; no Stellar YAML |

**Test result:** 803 passed (`pytest -q`, 2026-06-07).

---

## Methodology

1. Parsed every `.py` file (excluding `.venv/`, `__pycache__/`) with `ast` to collect `import` and absolute `from … import` statements.
2. Classified each top-level module against Python 3.12 `sys.stdlib_module_names`.
3. Cross-referenced declared dependencies in `pyproject.toml`.
4. Verified import chains with `/usr/bin/python3.12 -S` (stdlib only, no site-packages) to identify runtime blockers.
5. Inspected `subprocess` call sites for external binary dependencies.

Internal packages (`dsp`, `scenarios`, `tests`) are excluded from dependency tables — they are first-party code.

---

## Clean Ubuntu 24.04 Blockers

Assumption: **only** `python3.12` is installed (no venv, no `pip install`, no optional system tools).

### Python package blockers

| Import | PyPI package | When it blocks | First failure point |
|--------|--------------|----------------|---------------------|
| `yaml` | **PyYAML** (`pyyaml>=6.0`) | When YAML files are actually read (manifests, Stellar contracts/mappings/aliases) | Function-scoped: `parse_manifest()`, `load_scenario_contracts()`, `load_stellar_mapping()`, `_load_alias_registry()` |

**Post-hardening:** Module import no longer fails. Example — these succeed without PyYAML:

```
import dsp.runner.cli
import dsp.event_store
import dsp.execution.remote
```

Example — these fail without PyYAML when invoked:

```
ModuleNotFoundError: No module named 'yaml'
  dsp/plugins/validator.py (inside parse_manifest)
  dsp/detection/providers/stellar/contracts/contract_loader.py (inside load_scenario_contracts)
```

### Installation blockers (not import-time, but required to deploy)

| Tool / package | Declared in | Why it blocks |
|----------------|-------------|---------------|
| `pip` | — | Not bundled with minimal Python installs; required to install PyYAML and the `dsp` package itself |
| `hatchling` | `[build-system]` in `pyproject.toml` | Required to build/install the package via `pip install -e .` |
| `dsp` (editable install) | `[project.scripts]` | Console entry point `dsp = dsp.runner.cli:main` requires package installation |

### System library blockers (stdlib extension modules)

These are **not** pip packages but may be absent on a truly minimal `python3.12-minimal` install:

| Stdlib module | Ubuntu system library | Used for |
|---------------|----------------------|----------|
| `_sqlite3` / `sqlite3` | `libsqlite3-0` | Event Store (`events.db`) — `dsp/event_store/store.py` |
| `_ssl` / `ssl` | `libssl3` | Stellar HTTPS client, LDAPS, TLS-wrapped sockets |

The standard Ubuntu `python3.12` metapackage pulls these in. A bare `python3.12-minimal` install may lack them.

### External OS binary blockers (scenario-specific)

These are not Python imports but prevent specific scenarios from executing live traffic:

| Binary | Ubuntu package | Invoked from | Scenarios affected |
|--------|----------------|--------------|-------------------|
| `ssh` | `openssh-client` | `dsp/protocols/ssh/client.py:39,96` | `ssh_failure` |
| `ldapsearch` | `ldap-utils` | `dsp/protocols/ldap/client.py:61` | `ldap_enumeration` (search path; anonymous bind uses raw sockets as fallback) |

---

## Third-Party Runtime Dependencies

| Import name | Package name | Scope | Locations used | Replacement recommendation |
|-------------|--------------|-------|----------------|---------------------------|
| `yaml` | **PyYAML** (`pyyaml>=6.0`) | **runtime + test** | **Runtime (lazy):** `dsp/plugins/validator.py:129`, `dsp/detection/providers/stellar/contracts/contract_loader.py` (`load_scenario_contracts`), `dsp/detection/providers/stellar/normalization.py` (`_load_alias_registry`), `dsp/detection/providers/stellar/stellar_mapping.py` (`load_stellar_mapping`). **Test:** `tests/detection/test_stellar_contracts.py:8`, `tests/plugins/test_loader.py:8` | **Short term:** Document `pip install pyyaml` or `pip install -e .` as mandatory for manifest/Stellar YAML loading. **Medium term:** migrate YAML files to JSON/TOML if zero third-party deps desired. Lazy imports already decouple core module import from PyYAML. |

### PyYAML lazy-import sites (post-hardening)

```
parse_manifest()              → scenarios/*/manifest.yaml
load_scenario_contracts()     → scenario_contracts.yaml
load_stellar_mapping()        → scenario_mapping.yaml
_load_alias_registry()        → stellar_aliases.yaml
```

Module import of Stellar adapter, CLI, and run manager no longer touches PyYAML.

---

## Third-Party Development Dependencies

| Import name | Package name | Scope | Locations used | Replacement recommendation |
|-------------|--------------|-------|----------------|---------------------------|
| `pytest` | **pytest** (`>=8.0`, optional `[dev]`) | **test only** | 78 test files under `tests/` (e.g. `tests/conftest.py:5`, all `test_*.py` modules) | Keep as optional dev extra: `pip install -e ".[dev]"`. No runtime impact. Standard test runner for the project. |

### Build-system dependency (not imported at runtime)

| Package name | Declared in | Scope | Replacement recommendation |
|--------------|-------------|-------|---------------------------|
| **hatchling** | `[build-system] requires = ["hatchling"]` | **build only** | Required for `pip install -e .`. Could switch to `setuptools` if lab environments lack hatchling caching, but no runtime effect. |

---

## Python Standard Library Dependencies

All modules below ship with Python 3.12. None require `pip install`. Modules marked **test only** do not affect production runtime.

| Import name | Package name | Scope | File count (runtime / test) | Purpose | Example location |
|-------------|--------------|-------|----------------------------:|---------|------------------|
| `__future__` | — (stdlib) | runtime + test | 173 / 123 | Postponed annotation evaluation | `dsp/detection/base.py:3` |
| `abc` | — (stdlib) | runtime | 10 / 0 | Abstract base classes for adapters and protocols | `dsp/detection/base.py` |
| `argparse` | — (stdlib) | runtime | 1 / 0 | CLI argument parsing | `dsp/runner/cli.py` |
| `ast` | — (stdlib) | test only | 0 / 1 | AST inspection in tests | `tests/e2e/conftest.py` |
| `base64` | — (stdlib) | runtime + test | 1 / 1 | Payload encoding (DNS tunnel, webshell) | `dsp/protocols/dns/tunnel.py` |
| `collections` | — (stdlib) | runtime | 1 / 0 | Specialized containers | `dsp/execution/providers/runtime/transport/transport_runtime.py` |
| `copy` | — (stdlib) | runtime | 1 / 0 | Deep copy in normalization | `dsp/detection/providers/stellar/normalization.py` |
| `dataclasses` | — (stdlib) | runtime + test | 49 / 10 | Data models across all domains | `dsp/detection/models.py` |
| `datetime` | — (stdlib) | runtime + test | 55 / 35 | Timestamps, run IDs, events | `dsp/event_store/models.py` |
| `enum` | — (stdlib) | runtime | 8 / 0 | Status and mode enumerations | `dsp/detection/models.py` |
| `functools` | — (stdlib) | runtime | 1 / 0 | Function utilities | `dsp/detection/providers/stellar/normalization.py` |
| `hashlib` | — (stdlib) | runtime | 1 / 0 | Detection cache hashing | `dsp/detection/providers/stellar/detection_cache.py` |
| `http` | — (stdlib) | test only | 0 / 1 | HTTP test server fixture | `tests/e2e/fixtures/webshell_test_server.py` |
| `importlib` | — (stdlib) | runtime | 12 / 0 | Dynamic scenario plugin loading | `dsp/plugins/loader.py` |
| `inspect` | — (stdlib) | test only | 0 / 10 | Test introspection | `tests/e2e/conftest.py` |
| `io` | — (stdlib) | test only | 0 / 1 | In-memory I/O in tests | `tests/protocols/http/test_http_client.py` |
| `json` | — (stdlib) | runtime + test | 14 / 33 | Run artifacts, reporting, serialization | `dsp/runner/run_manager.py` |
| `os` | — (stdlib) | runtime | 4 / 0 | Environment variables, paths | `dsp/detection/providers/stellar/stellar_config.py` |
| `pathlib` | — (stdlib) | runtime + test | 53 / 31 | Path handling throughout | `dsp/plugins/loader.py` |
| `random` | — (stdlib) | runtime + test | 1 / 1 | DGA domain generation | `dsp/protocols/dns/dga.py` |
| `re` | — (stdlib) | runtime | 6 / 0 | Pattern matching, normalization | `dsp/detection/providers/stellar/normalization.py` |
| `shutil` | — (stdlib) | test only | 0 / 1 | Filesystem helpers in tests | `tests/scenarios/test_dummy_e2e.py` |
| `socket` | — (stdlib) | runtime + test | 7 / 4 | DNS, LDAP, SMB, port sweep I/O | `dsp/protocols/dns/client.py` |
| `sqlite3` | — (stdlib) | runtime | 1 / 0 | Event Store (SQLite per-run DB) | `dsp/event_store/store.py` |
| `ssl` | — (stdlib) | runtime | 4 / 0 | HTTPS (Stellar), LDAPS, TLS sockets | `dsp/detection/providers/stellar/http_client.py` |
| `string` | — (stdlib) | runtime | 1 / 0 | DGA character sets | `dsp/protocols/dns/dga.py` |
| `struct` | — (stdlib) | runtime + test | 1 / 4 | Binary DNS/LDAP protocol packing | `dsp/protocols/dns/client.py` |
| `subprocess` | — (stdlib) | runtime | 2 / 0 | External `ssh` / `ldapsearch` calls | `dsp/protocols/ssh/client.py`, `dsp/protocols/ldap/client.py` |
| `sys` | — (stdlib) | runtime | 2 / 0 | Exit codes, module path for plugins | `dsp/runner/cli.py` |
| `tempfile` | — (stdlib) | runtime | 1 / 0 | Temporary artifact directories | `dsp/execution/providers/runtime/transport/transport_runtime.py` |
| `textwrap` | — (stdlib) | test only | 0 / 2 | Text formatting in tests | `tests/plugins/test_loader.py` |
| `threading` | — (stdlib) | test only | 0 / 1 | Concurrent test server | `tests/e2e/fixtures/webshell_test_server.py` |
| `time` | — (stdlib) | runtime + test | 16 / 1 | Rate limiting, scenario pacing | `dsp/detection/providers/stellar/http_client.py` |
| `traceback` | — (stdlib) | runtime | 1 / 0 | Orchestrator error formatting | `dsp/engine/orchestrator.py` |
| `typing` | — (stdlib) | runtime + test | 101 / 6 | Type hints | `dsp/detection/correlation.py` |
| `unittest` | — (stdlib) | test only | 0 / 33 | `MagicMock`, `patch` in tests | `tests/protocols/ssh/test_ssh_client.py` |
| `urllib` | — (stdlib) | runtime + test | 8 / 2 | HTTP clients (Stellar, webshell, sqli) | `dsp/detection/providers/stellar/http_client.py` |
| `uuid` | — (stdlib) | runtime | 16 / 0 | Run IDs, attempt IDs | `dsp/runner/run_manager.py` |

### Stdlib sub-module detail

| Import name | Parent | Scope | Locations |
|-------------|--------|-------|-----------|
| `urllib.request` | `urllib` | runtime | `dsp/detection/providers/stellar/http_client.py`, `dsp/protocols/http/client.py`, webshell transport modules |
| `urllib.parse` | `urllib` | runtime | `dsp/detection/providers/stellar/http_client.py`, `dsp/protocols/http/sqli_payloads.py` |
| `urllib.error` | `urllib` | runtime | `dsp/detection/providers/stellar/http_client.py`, `dsp/execution/webshell/transport/real_http_transport.py` |
| `http.server` | `http` | test only | `tests/e2e/fixtures/webshell_test_server.py` |
| `unittest.mock` | `unittest` | test only | 33 test files (`MagicMock`, `patch`) |

---

## Scenario Plugin Imports

All 12 scenario plugins under `scenarios/` import **only** first-party `dsp.*` modules and Python stdlib (`__future__`, `datetime`, `time`, `uuid`). No scenario introduces additional third-party dependencies.

Example (`scenarios/dummy/scenario.py`):

- `datetime`, `__future__` (stdlib)
- `dsp.engine.scenario_engine`, `dsp.event_store` (first-party)

---

## Declared vs. Actual Dependencies

| Declared in `pyproject.toml` | Actually imported | Match? |
|------------------------------|-------------------|--------|
| `pyyaml>=6.0` | `yaml` in 4 runtime + 2 test files | Yes |
| `pytest>=8.0` (optional `[dev]`) | `pytest` in 78 test files | Yes |
| `hatchling` (build-system) | Not imported | Expected |

**No undeclared third-party runtime imports were found.** The dependency declaration in `pyproject.toml` is complete and accurate.

---

## Minimum Viable Install on Ubuntu 24.04

To run DSP on a clean Ubuntu 24.04 host:

```bash
# System prerequisites
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv python3-pip

# Optional: scenario-specific OS tools
sudo apt-get install -y openssh-client ldap-utils

# Python environment
cd detection-scenario-platform
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .

# Verify
dsp --version
dsp plugins list
```

Minimum pip packages installed: **`pyyaml`** + **`dsp`** (editable).

---

## Recommendations (No Code Changes Applied)

Priority-ordered actions for improving clean-host compatibility:

1. **Document PyYAML as required for manifest/Stellar YAML loading** — not needed for core module import after hardening.
2. ~~**Lazy-import `yaml` in Stellar modules**~~ — **Done** (2026-06-07).
3. **Consider JSON/TOML migration for manifests and contracts** — eliminates the sole third-party runtime dependency entirely.
4. **Document OS binary prerequisites per scenario** — extend `ENVIRONMENT_VALIDATION.md` with `openssh-client` and `ldap-utils` requirements.
5. **Keep pytest and hatchling as dev/build-only** — no changes needed.

---

## Related Documents

- [ENVIRONMENT_VALIDATION.md](./runtime/ENVIRONMENT_VALIDATION.md) — existing environment checklist
- [pyproject.toml](../pyproject.toml) — declared dependencies
- [EXECUTION_GUIDE.md](./runtime/EXECUTION_GUIDE.md) — runtime execution instructions
