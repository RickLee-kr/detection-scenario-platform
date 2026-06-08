# Phase 0.5 — Architecture Freeze Review Report

**문서 버전:** 1.0.0  
**날짜:** 2026-06-05  
**상태:** Architecture freeze complete — **Phase 1 NOT authorized in this document**

---

## 1. Executive Summary

Phase 0.5는 DSP **핵심 계약(contract)을 동결**하여 Phase 1 구현 시 아키텍처 재논의 없이 코딩할 수 있게 한다.

| Metric | Count |
|--------|-------|
| New freeze documents (Phase 0.5) | 8 |
| Total canonical documents | 21+ (incl. ADR, reviews) |
| Frozen contract families | 9 |
| Code files created | **0** |
| Workspace files modified outside canonical root | **0** |

---

## 2. New Documents Created (Phase 0.5)

| # | Document | Purpose |
|---|----------|---------|
| 1 | [SCENARIO_MANIFEST_SPEC.md](./SCENARIO_MANIFEST_SPEC.md) | manifest.yaml canonical schema v1.0.0 |
| 2 | [PLUGIN_DISCOVERY_SPEC.md](./PLUGIN_DISCOVERY_SPEC.md) | discover/register/load/validate sequences |
| 3 | [EVENT_SCHEMA_FREEZE.md](./EVENT_SCHEMA_FREEZE.md) | Run, ScenarioRun, Event, ValidationResult, Report entities |
| 4 | [SCENARIO_INTERFACE_FREEZE.md](./SCENARIO_INTERFACE_FREEZE.md) | Scenario protocol v1.0.0 |
| 5 | [TARGET_PROVIDER_SPEC.md](./TARGET_PROVIDER_SPEC.md) | Target abstraction + capability model |
| 6 | [PROTOCOL_LIBRARY_SPEC.md](./PROTOCOL_LIBRARY_SPEC.md) | dns/http/ssh shared library boundaries |
| 7 | [DETECTION_CONFIDENCE_MODEL.md](./DETECTION_CONFIDENCE_MODEL.md) | S1/S2/S3 three-state model |
| 8 | [PHASE_0_5_ARCHITECTURE_FREEZE_REVIEW.md](./PHASE_0_5_ARCHITECTURE_FREEZE_REVIEW.md) | 본 리포트 |

### Updated (canonical only)

| Document | Change |
|----------|--------|
| [README.md](./README.md) | Phase 0.5 doc index |

---

## 3. Frozen Contracts

다음 계약은 **ADR 없이 변경 불가** (Phase 1 구현 MUST conform):

### 3.1 Core Architecture (Phase 0 / 0.1 — reaffirmed)

| Contract | ID / Rule | Source |
|----------|-----------|--------|
| Python over Bash | ADR 0001 | docs/adr/ |
| Event Store as SOT | ADR 0002 | docs/adr/ |
| Scenario plugin folders | ADR 0003 | docs/adr/ |
| No stdout/grep validation | ADR 0004 | docs/adr/ |
| SQLite primary storage | ADR 0005 | docs/adr/ |
| Runtime Path Equality | Execution = Validation = Reporting | SKILL_SPEC §4.1 |
| Workspace boundary | canonical root only | WORKSPACE_BOUNDARY |
| Scenario ≠ Detection Model | two-layer architecture | ARCHITECTURE_SPEC §16 |

### 3.2 Phase 0.5 Freeze IDs

| Contract | Frozen version | Document |
|----------|----------------|----------|
| Manifest schema | `manifest_schema_version: 1.0.0` | SCENARIO_MANIFEST_SPEC |
| Event row schema | `event_schema_version: 1.0.0` | EVENT_SCHEMA_FREEZE |
| Event status vocabulary | `event_status_vocab: 1.0.0` | EVENT_SCHEMA_FREEZE §3.3.1 |
| Validation result shape | `validation_result_schema: 1.0.0` | EVENT_SCHEMA_FREEZE §3.4 |
| Report format | `report_format_version: 1.0.0` | EVENT_SCHEMA_FREEZE §3.5 |
| Scenario interface | `scenario_interface_version: 1.0.0` | SCENARIO_INTERFACE_FREEZE |
| Plugin lifecycle | PluginStatus enum + sequences | PLUGIN_DISCOVERY_SPEC |
| Target capability IDs | §3.1 registry | TARGET_PROVIDER_SPEC |
| Protocol library API | `protocol_library_version: 1.0.0` | PROTOCOL_LIBRARY_SPEC |
| Detection confidence | S1 / S2 / S3 semantics | DETECTION_CONFIDENCE_MODEL |

### 3.3 Frozen Behaviors

| Behavior | Rule |
|----------|------|
| `execute()` return type | `None` only |
| Success declaration | ValidationEngine only |
| Disabled plugin | discovered, not loaded, not runnable |
| Duplicate plugin id | first wins, second CONFLICT |
| Empty targets | skip + `scenario_skipped`, not failed |
| Exit code Phase 1–2 | S2 (Traffic Validated) only |
| Report primary table | ValidationResult only |
| Event append | immutable, no delete in retention window |

---

## 4. Intentionally Flexible (Not Frozen)

| Area | Why flexible | Decided in |
|------|--------------|------------|
| Lazy vs eager plugin load | performance | Phase 1 implementation |
| `runs` metadata storage | JSON file vs SQLite table | Phase 1 |
| Exact probe algorithm for alive_host | lab network variance | Phase 1 TargetProvider |
| CLI command names (`dsp` vs `python -m dsp`) | UX | Phase 1 |
| `schemas/manifest.schema.json` tooling | JSON Schema optional Phase 1 | Phase 1 |
| Log format (structlog vs stdlib) | ops preference | Phase 1 |
| Remote executor adapter design | webshell sync | Phase 2 |
| Inventory file format details | deployment integration | Phase 3 |
| `--require-detection` exit policy | operator choice | Phase 4 |
| Composite scenario orchestration | campaign feature | Phase 3 |
| Lazy metric `ratio` computation in validation | engine implementation | Phase 1 (semantics frozen, algo flexible) |

---

## 5. Architecture Review — Ambiguity Resolution

### 5.1 Resolved in Phase 0.5

| Previous ambiguity | Resolution |
|--------------------|------------|
| `title` vs `name` in manifest | **`name`** canonical (SCENARIO_MANIFEST_SPEC) |
| `scenario` vs `scenario_id` column | **`scenario_id`** canonical in freeze |
| manifest `validation` vs `validation_profile` | **`validation_profile`** canonical |
| Who owns timeout | **Runner** enforces; executor cooperates |
| Skip vs fail for no targets | **skip** (S2=skipped) |
| Detection score | **abolished** — S1/S2/S3 model |
| Protocol code location | **`dsp/protocols/`** only |
| Plugin conflict resolution | **first wins** |

### 5.2 Remaining Open Questions (Phase 1 kickoff)

| # | Question | Recommendation |
|---|----------|----------------|
| Q1 | Python minimum 3.11 or 3.10? | **3.11** per manifest default |
| Q2 | `idx_pattern_ratio` metric — precompute in executor or SQL? | executor sets evidence flag; engine counts |
| Q3 | Package name: `dsp` vs `detection_scenario_platform`? | **`dsp`** short import |
| Q4 | Run directory: `~/.dsp/runs/` vs `./runs/`? | `~/.dsp/runs/` default, env override |
| Q5 | Single events.db per run vs global db? | **per run** (frozen EVENT_SCHEMA_FREEZE retention) |
| Q6 | pyproject.toml in Phase 1 — hatchling vs setuptools? | operator decision at Phase 1 start |
| Q7 | Cursor Skill install timing | first commit of Phase 1 |

None of Q1–Q7 block architecture freeze.

---

## 6. Cross-Document Consistency Check

| Check | Status |
|-------|--------|
| Manifest ↔ Plugin Discovery | ✅ M1–M10 aligned |
| Manifest ↔ Scenario Interface | ✅ id, validation_profile, safety |
| Event Schema ↔ Event Store Spec | ✅ SQLite columns aligned (scenario_id) |
| Event Schema ↔ Confidence Model | ✅ S2=ValidationResult |
| Interface ↔ SKILL_SPEC | ✅ Path equality, no execute bool |
| Target Provider ↔ Manifest capabilities | ✅ same ID registry |
| Protocol Lib ↔ Manifest protocols | ✅ enum aligned |
| Detection Catalog ↔ detection_mappings | ✅ optional mirror |
| ADR 0001–0005 ↔ freeze docs | ✅ no contradiction |
| Historical draft `docs/detection-scenario-platform/` | ✅ untouched |

---

## 7. Scalability Assessment (30–50 Scenarios)

| Dimension | Assessment |
|-----------|------------|
| Plugin discovery | ✅ O(n) scan, flat namespace |
| Manifest-driven validation | ✅ no core if/else per scenario |
| Event Store | ✅ indexed scenario_id |
| Protocol reuse | ✅ dns/http/ssh shared |
| Detection mappings | ✅ catalog + adapter, not scenario forks |
| Target roles | ✅ capability registry extensible |
| Documentation | ✅ DETECTION_CATALOG tracks candidates |

**Verdict:** Core architecture supports 50 scenarios without engine rewrite.

---

## 8. Recommended Phase 1 Scope

**Phase 1 goal:** Prove frozen contracts with **one scenario end-to-end**.

### 8.1 In Scope

| # | Deliverable |
|---|-------------|
| 1 | `pyproject.toml` + `dsp/` package skeleton (canonical root only) |
| 2 | `EVENT_SCHEMA_FREEZE` → SQLite EventStore implementation |
| 3 | `PLUGIN_DISCOVERY_SPEC` → Loader + Registry + Validator |
| 4 | `SCENARIO_INTERFACE_FREEZE` → base Scenario + RunContext |
| 5 | `PROTOCOL_LIBRARY_SPEC` → `dsp/protocols/dns.py` |
| 6 | `scenarios/dns_tunnel/` full manifest v1.0.0 |
| 7 | `ValidationEngine` — generic `validation_profile` applicator |
| 8 | `ReportingEngine` — minimal report v1.0.0 |
| 9 | `TargetProvider` Phase 1 capabilities only |
| 10 | `dsp run --scenarios dns_tunnel --dry-run` |
| 11 | pytest: Path Equality tests (SKILL_SPEC §4.1, §7.2) |
| 12 | Cursor Skill from SKILL_SPEC |

### 8.2 Out of Scope (Phase 1)

| Item | Phase |
|------|-------|
| dga, http_followup, ssh, sql_injection | 2 |
| Detection adapters (S3) | 3 |
| Remote webshell executor | 2 |
| deployment / aella_cli integration | 3+ |
| `manifest.schema.json` CI gate | 1 optional / 2 required |
| inventory.yaml role-based targets | 3 |

### 8.3 Phase 1 Success Criteria

- [ ] dry-run → events in SQLite → validate → report — single path
- [ ] stdout-only fixture → `code_failure` in test
- [ ] Second scenario folder added without editing `validation/engine.py` case statements
- [ ] No files modified outside `detection-scenario-platform/`

---

## 9. Document Map (Canonical Tree)

```
detection-scenario-platform/
├── README.md
├── PROJECT_CHARTER.md
├── ARCHITECTURE_SPEC.md
├── SCENARIO_FRAMEWORK_SPEC.md          # conceptual (superseded in detail by freezes)
├── SCENARIO_MANIFEST_SPEC.md           # FROZEN v1.0.0
├── SCENARIO_INTERFACE_FREEZE.md        # FROZEN v1.0.0
├── PLUGIN_DISCOVERY_SPEC.md            # FROZEN v1.0.0
├── EVENT_STORE_SPEC.md
├── EVENT_SCHEMA_FREEZE.md              # FROZEN v1.0.0
├── TARGET_PROVIDER_SPEC.md             # FROZEN v1.0.0
├── PROTOCOL_LIBRARY_SPEC.md            # FROZEN v1.0.0
├── DETECTION_CONFIDENCE_MODEL.md       # FROZEN v1.0.0
├── DETECTION_CATALOG.md
├── SKILL_SPEC.md
├── WORKSPACE_BOUNDARY.md
├── PHASE_0_1_ARCHITECTURE_REVIEW.md
├── PHASE_0_5_ARCHITECTURE_FREEZE_REVIEW.md
└── docs/adr/0001–0005
```

---

## 10. Compliance Statement

| Rule | Status |
|------|--------|
| No Python implementation | ✅ |
| No tests | ✅ |
| No integration code | ✅ |
| No deployment/legacy/CI modification | ✅ |
| All writes under `detection-scenario-platform/` | ✅ |

---

## 11. Architecture Freeze Gate

| Gate | Status |
|------|--------|
| Core contracts documented | ✅ |
| ADR trail complete | ✅ |
| 30–50 scenario scalability reviewed | ✅ |
| Phase 1 scope bounded | ✅ |
| **Authorized to start Phase 1 coding** | ⏸ **Awaiting explicit user approval** |

Phase 0.5 completes the **architecture freeze**. Implementation remains blocked until separate Phase 1 authorization.
