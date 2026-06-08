# Detection Scenario Platform — Plugin Discovery Specification

**문서 버전:** 1.0.0 (Phase 0.5 — **FROZEN**)  
**상태:** Canonical contract — implementation MUST conform

---

## 1. Purpose

시나리오 플러그인의 **발견(discover)·등록(register)·로드(load)·검증(validate)** 절차를 고정한다.  
30–50 플러그인 규모에서도 코어 엔진 수정 없이 동작해야 한다.

---

## 2. Recommended Directory Layout

```
detection-scenario-platform/
├── dsp/
│   ├── plugins/
│   │   ├── loader.py              # discovery orchestrator
│   │   ├── registry.py            # in-memory registry
│   │   ├── validator.py           # manifest + binding validation
│   │   └── models.py              # PluginRecord, PluginStatus
│   └── ...
├── scenarios/                     # PLUGIN ROOT (configurable path)
│   ├── dns_tunnel/
│   │   ├── manifest.yaml          # REQUIRED
│   │   ├── scenario.py            # REQUIRED — Scenario subclass
│   │   └── executor.py            # REQUIRED unless manifest says otherwise
│   └── ...
└── schemas/
    └── manifest.schema.json       # Phase 1 — JSON Schema for M1–M10
```

| Path | Config key | Default |
|------|------------|---------|
| Plugin root | `DSP_SCENARIOS_DIR` | `./scenarios` relative to package root |
| Schema | `DSP_MANIFEST_SCHEMA` | `schemas/manifest.schema.json` |

---

## 3. Plugin Record Model (Frozen)

```yaml
PluginRecord:
  id: string
  manifest: Manifest              # parsed manifest.yaml
  status: PluginStatus              # enum §3.1
  status_reason: string | null
  scenario_class: type | null       # loaded Scenario subclass
  discovered_at: datetime
  manifest_path: Path
  load_error: string | null
```

### 3.1 PluginStatus (Frozen enum)

| Status | Runnable | In `list-scenarios` |
|--------|----------|---------------------|
| `active` | yes | yes, enabled |
| `disabled` | no | yes, marked disabled |
| `unavailable` | no | yes, reason shown |
| `rejected` | no | no (log only) |
| `conflict` | no | no (log only) |

---

## 4. Plugin Lifecycle

```
                    ┌──────────────┐
                    │  filesystem  │  scenarios/<id>/ exists
                    └──────┬───────┘
                           ▼
                    ┌──────────────┐
                    │  DISCOVERED  │  directory scanned
                    └──────┬───────┘
                           ▼
                    ┌──────────────┐
              ┌────►│  VALIDATING  │  manifest + files check
              │     └──────┬───────┘
              │            ├── invalid ──► REJECTED
              │            ▼
              │     ┌──────────────┐
              │     │   ENABLED?   │  manifest.enabled
              │     └──────┬───────┘
              │       false│      true
              │            ▼        ▼
              │     DISABLED    ┌──────────┐
              │                 │ LOADING  │  import scenario.py
              │                 └────┬─────┘
              │                      ├── import error ──► UNAVAILABLE
              │                      ▼
              │                 ┌──────────┐
              │                 │ ID MATCH │  class.scenario_id() == id
              │                 └────┬─────┘
              │                      ├── mismatch ──► REJECTED
              │                      ▼
              │                 ┌──────────┐
              └────────────────►│ REGISTER │  duplicate check
                                └────┬─────┘
                                     ├── duplicate ──► CONFLICT (first wins)
                                     ▼
                                ┌──────────┐
                                │  ACTIVE  │
                                └────┬─────┘
                                     │ run requested
                                     ▼
                                ┌──────────┐
                                │ RUNNING  │  Scenario Engine
                                └──────────┘
```

---

## 5. Discovery Sequence

```
DISCOVERY SEQUENCE (on Runner start or `dsp plugins reload`)

1. RESOLVE plugin root path from config
2. IF not directory → empty registry + warning
3. LIST immediate subdirectories (non-recursive)
4. FOR each subdirectory D:
   a. IF D.name starts with '_' or '.' → SKIP
   b. IF manifest.yaml missing → LOG warning, SKIP (not rejected globally)
   c. ADD D to candidate queue
5. RETURN candidate queue sorted by id (deterministic order)
```

**Non-recursive:** nested `scenarios/group/foo/` is **invalid** — flat namespace only.

**Determinism:** alphabetical `id` sort — reproducible registration order.

---

## 6. Validation Sequence

```
VALIDATION SEQUENCE (per candidate)

1. PARSE manifest.yaml (YAML safe load)
   → parse error → REJECTED (reason: yaml_parse_error)

2. CHECK manifest_schema_version in supported set {"1.0.0"}
   → unsupported → REJECTED (reason: unsupported_schema_version)

3. APPLY rules M1–M10 from SCENARIO_MANIFEST_SPEC.md §11

4. CHECK required files:
   - scenario.py MUST exist
   - executor module per manifest.executor MUST exist (unless entrypoint in scenario.py)

5. IF enabled == false:
   → REGISTER as DISABLED (skip steps 6–8)

6. CHECK requirements.dsp_min_version against platform version
   → incompatible → UNAVAILABLE (reason: dsp_version)

7. DEFER package import check to LOAD sequence

8. RETURN validation pass → proceed to LOAD
```

---

## 7. Load Sequence

```
LOAD SEQUENCE (per validated candidate)

1. IF status already DISABLED → skip load, scenario_class = null

2. TRY import scenarios.<id>.scenario (package path from plugin root)
   → ImportError → UNAVAILABLE (reason: import_error)

3. FIND exactly one concrete Scenario subclass
   → 0 found → REJECTED (reason: no_scenario_class)
   → >1 found → REJECTED (reason: ambiguous_scenario_class)

4. VERIFY subclass.scenario_id() == manifest.id
   → mismatch → REJECTED (reason: id_mismatch)

5. IF requirements.packages specified:
   TRY import each → any fail → UNAVAILABLE (reason: missing_package)

6. SET scenario_class on PluginRecord
7. SET status = ACTIVE
```

**Lazy load option (intentionally flexible):** Phase 1 MAY defer step 2–5 until first run of that scenario. If lazy: DISCOVERY+VALIDATION still run at startup; LOAD on first `run`. Document in implementation; contract unchanged.

---

## 8. Registration Sequence

```
REGISTRATION SEQUENCE (after load)

1. LOOKUP registry.by_id[manifest.id]
2. IF exists:
   a. Compare manifest.version with existing
   b. LOG CONFLICT — first registered wins (frozen rule)
   c. SET new plugin status = CONFLICT, do not register
3. ELSE:
   a. INSERT PluginRecord into registry.by_id
   b. APPEND id to registry.ordered_ids (sorted)
4. EXPOSE read-only RegistryView to Scenario Engine
```

### 8.1 Version Conflict Policy (Frozen)

| Situation | Resolution |
|-----------|------------|
| Duplicate `id`, same path scanned twice | Impossible if flat scan — guard anyway |
| Duplicate `id`, two directories | **First alphabetically by path wins** — second CONFLICT |
| Same id, hot reload | Replace only if `dsp plugins reload --force` (Phase 2 CLI) — Phase 1: process restart |

Scenario `version` semver does NOT auto-resolve conflicts — `id` is unique key.

---

## 9. Disabled Plugin Handling (Frozen)

| `enabled` | Discovery | Validation | Load | `dsp run` | `dsp list-scenarios` |
|-----------|-----------|------------|------|-----------|----------------------|
| `false` | yes | yes (schema) | no | skip silently if requested | show `disabled` |
| `true` | yes | yes | yes | execute | show `active` |

Explicit request `dsp run --scenarios disabled_id` → exit code 3 (config error) + message.

---

## 10. Registry API (Conceptual — Frozen Surface)

```python
class PluginRegistry(Protocol):
    def all(self) -> list[PluginRecord]: ...
    def get(self, id: str) -> PluginRecord | None: ...
    def active_ids(self) -> list[str]: ...
    def reload(self) -> None: ...
```

Scenario Engine MUST NOT scan filesystem directly — **only** Registry.

---

## 11. Integration Points

| Consumer | Uses registry for |
|----------|-------------------|
| Runner CLI | `list-scenarios`, run scenario set resolution |
| Scenario Engine | instantiate Scenario class |
| Validation Engine | `validation_profile` from manifest |
| Reporting Engine | `report_profile` from manifest |
| Target Provider | `supported_targets` capabilities |

---

## 12. Error Handling (Frozen)

| Failure | Platform behavior |
|---------|-------------------|
| One plugin rejected | Continue loading others |
| All plugins rejected | Runner starts; `dsp run` exits 3 |
| Plugin throws in execute() | `scenario_aborted` event; other scenarios continue (default) |
| Registry empty | `dsp run` exits 3 |

---

## 13. Testing Contract (Phase 1+)

| Test | Assert |
|------|--------|
| Valid manifest + class | status `active` |
| `enabled: false` | status `disabled`, not loaded |
| Bad schema version | status `rejected` |
| Duplicate id | first `active`, second `conflict` |
| Missing scenario.py | `rejected` |

Tests use production Loader — no parallel discovery implementation.

---

## 14. Related Documents

- [SCENARIO_MANIFEST_SPEC.md](./SCENARIO_MANIFEST_SPEC.md)
- [SCENARIO_INTERFACE_FREEZE.md](./SCENARIO_INTERFACE_FREEZE.md)
- [docs/adr/0003-scenario-plugin-architecture.md](./docs/adr/0003-scenario-plugin-architecture.md)
