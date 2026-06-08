# Detection Scenario Platform — Definition of Done

**문서 버전:** 1.0.0 (Phase 0.6)  
**상태:** DSP-wide DoD — applies to **all future phases**  
**범위:** Every PR, component, scenario plugin, and phase gate

---

## 1. Purpose

Definition of Done(DoD)는 "완료"의 의미를 팀·에이전트·리뷰어 간에 **동일하게** 고정한다.  
코드가 동작한다고 해서 Done이 아니다. **아키텍처 계약 준수 + 검증 증거 + 경계 준수**가 함께 충족되어야 한다.

---

## 2. Universal Completion Checklist

모든 DSP 구현 작업(Phase 1A 이후)은 merge/phase-close 전에 아래를 **모두** 충족한다.

### 2.1 Architecture Compliance

- [ ] 변경이 [ARCHITECTURE_SPEC.md](./ARCHITECTURE_SPEC.md) 및 frozen contract 문서와 모순되지 않음
- [ ] ADR 0001–0005 위반 없음 (Python, Event Store SOT, plugin folders, no stdout validation, SQLite)
- [ ] Scenario ≠ Detection Model 분리 유지 (traffic 코드에 vendor 분기 없음)
- [ ] Breaking contract change 시 ADR + version bump 포함 (사전 승인)

### 2.2 Path Equality Compliance

- [ ] Execution Path writes **Event Store only** (traffic truth)
- [ ] Validation Path reads **Event Store only**
- [ ] Reporting Path reads **Event Store + ValidationResult only**
- [ ] Test·CI·CLI가 production ValidationEngine / ReportingEngine / EventStore API 사용
- [ ] Forbidden parallel paths 없음 ([PATH_EQUALITY_VERIFICATION_SPEC.md](./PATH_EQUALITY_VERIFICATION_SPEC.md))
- [ ] `if TESTING:` validation bypass 없음

### 2.3 Event Store Compliance

- [ ] Append-only semantics (no update/delete in retention window)
- [ ] `event_schema_version: 1.0.0` on every row
- [ ] Forbidden event.status values 미사용
- [ ] aggregate API가 validation_profile metrics의 **유일한** 입력
- [ ] Completed run store read-only
- [ ] [EVENT_STORE_ACCEPTANCE_SPEC.md](./EVENT_STORE_ACCEPTANCE_SPEC.md) 충족

### 2.4 Validation Compliance

- [ ] Success/failure **only** ValidationEngine emits `ValidationResult.decision`
- [ ] Thresholds from `manifest.validation_profile` only — no per-scenario hardcoded if/else in core
- [ ] Fail-fast invariants from manifest or frozen registry only
- [ ] S2 (Traffic Validated) = ValidationResult; S1 (stdout/log) never used
- [ ] `validation_result_schema: 1.0.0` shape preserved

### 2.5 Reporting Compliance

- [ ] Primary scenario table from ValidationResult[] only
- [ ] ScenarioSummary is supplementary — cannot override decision
- [ ] Event samples traceable to Store rows (run_id + scenario_id + event id)
- [ ] `report_format_version: 1.0.0` declared in artifact
- [ ] stdout/debug.log in appendix only, labeled non-SOT
- [ ] No synthetic detection score or report-only counters

### 2.6 Repository Boundary Compliance

- [ ] All new/modified files under `detection-scenario-platform/` only
- [ ] No changes to deployment automation, CI/CD, legacy PoC scripts
- [ ] No import/link from DSP into `appliance/`, `scripts/`, root tooling
- [ ] Historical draft `docs/detection-scenario-platform/` untouched
- [ ] [WORKSPACE_BOUNDARY.md](./WORKSPACE_BOUNDARY.md) checklist passed

### 2.7 Documentation Requirements

| Change type | Required documentation |
|-------------|------------------------|
| New core component | Module docstring + ARCHITECTURE_SPEC cross-ref if public API |
| New scenario plugin | Valid `manifest.yaml` v1.0.0 + README scenario list entry |
| New metric / fail-fast | manifest `validation_profile` update + spec example if novel |
| Behavior change | ADR or phase acceptance criteria update |
| Phase completion | Phase acceptance criteria sign-off document |

- [ ] Public CLI commands documented (help text + README)
- [ ] Frozen version IDs visible in run/report artifacts where applicable

### 2.8 Testing Requirements

- [ ] Unit tests for new logic (no network where avoidable)
- [ ] Path Equality test for any validation/reporting change
- [ ] Plugin manifest rejection cases for loader changes
- [ ] CI runs tests from `detection-scenario-platform/tests/` only
- [ ] No test-only validation functions that bypass Event Store

### 2.9 Code Quality (Minimum)

- [ ] Typed Python (type hints on public APIs)
- [ ] No secrets committed
- [ ] Safety envelope respected (`target_net`, manifest `safety`)
- [ ] Linter/formatter consistent with project config (when introduced)

---

## 3. Component-Specific DoD Extensions

### 3.1 Scenario Plugin

- [ ] Implements Scenario Interface v1.0.0 (`prepare`, `execute`, `summarize`)
- [ ] `execute()` returns `None`
- [ ] Lifecycle events emitted
- [ ] No ValidationEngine import in scenario code
- [ ] manifest `id` == folder == `scenario_id()`

### 3.2 Runner

- [ ] Orchestrates prepare → execute → validate → report in order
- [ ] Handles `ScenarioSkipError`, `SafetyViolationError` per interface freeze
- [ ] Exit code from ValidationResult (S2) only in Phase 1–2
- [ ] Timeout enforcement at run and scenario level

### 3.3 Plugin Loader

- [ ] PluginStatus enum behavior per PLUGIN_DISCOVERY_SPEC
- [ ] Duplicate id → CONFLICT (first wins)
- [ ] `enabled: false` → DISABLED, not runnable
- [ ] Manifest validation before ACTIVE

### 3.4 Validation Engine

- [ ] Generic metric applicator — no scenario name switch in core
- [ ] fail_fast_codes populated when invariants fire
- [ ] Cached to `validation.json` per run

### 3.5 Reporting Engine

- [ ] Regenerable from Store + validation.json without re-execute
- [ ] PII-free event samples
- [ ] Executive summary counts match ValidationResult decisions

---

## 4. Phase Gate DoD

Phase 종료 시 추가 조건:

| Gate | Requirement |
|------|-------------|
| Phase acceptance doc | All exit criteria checked |
| Compliance checklist | ARCHITECTURE_COMPLIANCE_CHECKLIST signed |
| Risk register | Open risks accepted or mitigated |
| Scope audit | No non-goals merged under phase label |
| Readiness review | Go/No-Go document updated |

---

## 5. Explicit Non-Completion Signals

다음 중 하나라도 해당하면 **Done 아님**:

| Signal | Meaning |
|--------|---------|
| Validation reads stdout or log file | Path Equality violation |
| Report row built from executor return value | Path Equality violation |
| `planned` / `attempted` counters not backed by events | Legacy counter bug |
| Test uses `validate_from_stdout()` or equivalent | Forbidden test path |
| File modified outside canonical root | Boundary violation |
| Real scenario merged under Phase 1A label | Scope drift |
| Detection adapter required for phase success (Phase 1A–2) | Wrong confidence layer |

---

## 6. Related Documents

- [ARCHITECTURE_COMPLIANCE_CHECKLIST.md](./ARCHITECTURE_COMPLIANCE_CHECKLIST.md)
- [PATH_EQUALITY_VERIFICATION_SPEC.md](./PATH_EQUALITY_VERIFICATION_SPEC.md)
- [EVENT_STORE_ACCEPTANCE_SPEC.md](./EVENT_STORE_ACCEPTANCE_SPEC.md)
- [SKILL_SPEC.md](./SKILL_SPEC.md) §3–§4
- [WORKSPACE_BOUNDARY.md](./WORKSPACE_BOUNDARY.md)
