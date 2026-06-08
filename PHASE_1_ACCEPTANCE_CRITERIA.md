# Phase 1A — Core Platform Skeleton Acceptance Criteria

**문서 버전:** 1.0.0 (Phase 0.6)  
**상태:** Implementation acceptance criteria — **no code in this document**  
**범위:** Phase 1A only (Core Platform Skeleton + Dummy Scenario)

---

## 1. Purpose

Phase 1A는 **동결된 아키텍처 계약을 코드로 증명**하는 단계이다.  
실제 탐지 트래픽 시나리오(dns_tunnel, dga 등)는 **Phase 1B 이후**로 연기한다.

본 문서는 Phase 1A 구현이 **완료되었다고 선언할 수 있는 조건**을 정의한다.  
범위 밖 작업은 성공으로 간주하지 않는다.

---

## 2. Goals

| # | Goal | Success signal |
|---|------|----------------|
| G1 | Event Store가 SOT로 동작 | Validation·Reporting이 Store만 읽음 |
| G2 | Runner가 end-to-end lifecycle 오케스트레이션 | `pending → running → completed` 단일 run |
| G3 | Plugin Loader가 manifest 기반 등록 | Dummy Scenario `ACTIVE` 상태 |
| G4 | Scenario Interface v1.0.0 준수 | `prepare` / `execute` / `summarize` 계약 |
| G5 | Validation Engine이 manifest-driven 판정 | `validation_profile`만으로 decision |
| G6 | Reporting Engine이 ValidationResult 기반 리포트 | primary table = ValidationResult |
| G7 | Path Equality 증명 | Execution = Validation = Reporting (동일 Store) |
| G8 | Dummy Scenario로 계약 검증 | 네트워크 I/O 없이 E2E 통과 |

---

## 3. Non-Goals (Explicitly Out of Scope)

Phase 1A에서 **다음은 구현·통합·테스트 대상이 아니다**:

| Category | Excluded items |
|----------|----------------|
| Real traffic scenarios | `dns_tunnel`, `dga`, `http_followup`, `ssh_failure`, `sql_injection` |
| Protocol libraries (production) | `dsp/protocols/dns.py`, `http.py`, `ssh.py` (stub only if needed by dummy) |
| Remote execution | webshell sync, remote executor adapter |
| Detection layer | Detection adapters, S3 confirmation, vendor API |
| Deployment integration | `aella_cli`, `appliance/`, bootstrap, installer |
| Legacy coupling | `stellar_poc*.sh` import, TSV compatibility, stdout parsing |
| Target Provider (full) | Full capability probing — minimal stub for dummy only |

Phase 1A에 real scenario를 추가하면 **scope drift**로 간주한다.

---

## 4. In-Scope Deliverables

| # | Component | Minimum capability |
|---|-----------|-------------------|
| D1 | **Event Store** | SQLite per-run, append-only, aggregate API |
| D2 | **Runner** | CLI entry, run lifecycle, scenario orchestration |
| D3 | **Plugin Loader** | discover → validate → register → ACTIVE |
| D4 | **Scenario Interface** | Base Scenario + RunContext per freeze |
| D5 | **Validation Engine** | Generic `validation_profile` applicator |
| D6 | **Reporting Engine** | Report v1.0.0 (Markdown + embedded JSON) |
| D7 | **Dummy Scenario** | `scenarios/dummy/` — dry-run events only |

---

## 5. Exit Criteria

Phase 1A는 **모든** exit criteria를 충족해야 종료된다.

### 5.1 Functional Exit Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| EC-1 | `dsp run --scenarios dummy --dry-run` completes with `Run.status = completed` | CLI + run metadata |
| EC-2 | Event Store contains lifecycle + traffic events for dummy run | SQL query / export |
| EC-3 | ValidationEngine produces `ValidationResult` with `decision` from manifest thresholds | `validation.json` |
| EC-4 | ReportingEngine generates report where scenario row matches ValidationResult | `report.md` diff |
| EC-5 | Runner exit code derives from ValidationResult only (S2) | exit code matrix test |
| EC-6 | Second dummy-like plugin folder added without editing `validation/engine.py` per-scenario branches | structural review |
| EC-7 | Plugin Loader lists dummy as `ACTIVE`; disabled plugin is discovered but not runnable | `dsp plugins list` |
| EC-8 | Completed run Event Store is read-only | append rejection test |

### 5.2 Architectural Exit Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| AC-1 | No stdout/grep validation path exists | code search + PATH_EQUALITY_VERIFICATION_SPEC |
| AC-2 | `execute()` returns `None` only | interface audit |
| AC-3 | No files created/modified outside `detection-scenario-platform/` | git diff boundary |
| AC-4 | All frozen schema versions declared in artifacts | version field audit |
| AC-5 | ARCHITECTURE_COMPLIANCE_CHECKLIST fully passed | checklist sign-off |

### 5.3 Documentation Exit Criteria

| ID | Criterion |
|----|-----------|
| DC-1 | `pyproject.toml` + package layout documented in README (Phase 1A section) |
| DC-2 | Dummy scenario manifest is valid v1.0.0 example |
| DC-3 | Known Phase 1 open questions (Q1–Q7 from Phase 0.5) resolved or explicitly deferred with ADR note |

---

## 6. Required Artifacts

구현 완료 시 `detection-scenario-platform/` 하위에 다음이 **존재**해야 한다.

### 6.1 Package Structure

```
detection-scenario-platform/
├── pyproject.toml
├── dsp/
│   ├── runner/
│   ├── event_store/
│   ├── validation/
│   ├── reporting/
│   └── plugins/
├── scenarios/
│   └── dummy/
│       ├── manifest.yaml
│       └── scenario.py
└── tests/
```

### 6.2 Per-Run Artifacts (default layout)

```
~/.dsp/runs/<run_id>/
├── events.db
├── run.json                    # or runs table equivalent
├── manifest.snapshot.json      # per scenario
├── validation.json
├── report.md
└── report.json                 # optional machine bundle
```

### 6.3 Test Artifacts

| Test suite | Purpose |
|------------|---------|
| Event Store unit tests | append, aggregate, immutability |
| Path Equality tests | production ValidationEngine + ReportingEngine on synthetic events |
| Plugin Loader tests | discover, reject, conflict, disabled |
| Dummy scenario integration | dry-run E2E without network |
| Boundary test | no repo-root file changes |

---

## 7. Required Validations

### 7.1 Manifest Validation (Loader)

- `manifest_schema_version: "1.0.0"`
- Required fields M1–M10 per [SCENARIO_MANIFEST_SPEC.md](./SCENARIO_MANIFEST_SPEC.md)
- `validation_profile.success` non-empty
- `id` == directory name == `Scenario.scenario_id()`

### 7.2 Event Validation (Store)

- Row conforms to [EVENT_SCHEMA_FREEZE.md](./EVENT_SCHEMA_FREEZE.md) §3.3
- Forbidden status values never written (`success`, `failed`, `partial`, `skipped` on Event)
- Mandatory lifecycle events for executed scenario: `scenario_started`, `scenario_completed`

### 7.3 Validation Engine

- Metrics computed **only** via `EventStore.aggregate()` + `validation_profile`
- Fail-fast invariants evaluated when declared in manifest
- `ValidationResult.decision` emitted only by ValidationEngine

### 7.4 Reporting Engine

- Primary scenario table sourced from `ValidationResult[]` only
- Event samples from Event Store (max N per scenario)
- No metric in report without Store or ValidationResult traceability

### 7.5 Path Equality (Mandatory Test Cases)

| Case | Expected |
|------|----------|
| Store populated with dummy events → validate → report | Same metrics in all three stages |
| Store empty after execute marker | `code_failure` or fail-fast `SOT_EMPTY_AFTER_EXECUTE` |
| stdout claims success, events=0 | `code_failure` (test fixture) |
| Report regenerated from Store + validation.json | Identical primary table |

---

## 8. Definition of Done (Phase 1A)

Phase 1A 작업 단위(D1–D7) 각각은 [DEFINITION_OF_DONE.md](./DEFINITION_OF_DONE.md)를 충족해야 한다.

Phase 1A **전체** Definition of Done:

- [ ] §4 In-Scope Deliverables 모두 구현
- [ ] §5 Exit Criteria 100% 통과
- [ ] §6 Required Artifacts 존재
- [ ] §7 Required Validations 자동화 (pytest)
- [ ] [ARCHITECTURE_COMPLIANCE_CHECKLIST.md](./ARCHITECTURE_COMPLIANCE_CHECKLIST.md) 서명 가능
- [ ] [PATH_EQUALITY_VERIFICATION_SPEC.md](./PATH_EQUALITY_VERIFICATION_SPEC.md) evidence 제출
- [ ] [EVENT_STORE_ACCEPTANCE_SPEC.md](./EVENT_STORE_ACCEPTANCE_SPEC.md) criteria 충족
- [ ] [IMPLEMENTATION_RISK_REGISTER.md](./IMPLEMENTATION_RISK_REGISTER.md) mitigations verified or accepted
- [ ] No scope items from §3 Non-Goals merged into Phase 1A PRs

---

## 9. Phase 1A vs Phase 1B Boundary

| Phase | Scope |
|-------|-------|
| **1A (this document)** | Core skeleton + Dummy Scenario |
| **1B (future)** | First real scenario (e.g. `dns_tunnel`) + protocol library + Target Provider subset |
| **2+** | Additional scenarios, remote executor, detection adapters |

Phase 1A 완료는 Phase 1B 착수 **필요조건**이지 **충분조건**이 아니다.  
Phase 1B는 별도 acceptance criteria 문서로 정의한다.

---

## 10. Related Documents

- [DEFINITION_OF_DONE.md](./DEFINITION_OF_DONE.md)
- [PHASE_1_EXECUTION_PLAN.md](./PHASE_1_EXECUTION_PLAN.md)
- [PATH_EQUALITY_VERIFICATION_SPEC.md](./PATH_EQUALITY_VERIFICATION_SPEC.md)
- [EVENT_STORE_ACCEPTANCE_SPEC.md](./EVENT_STORE_ACCEPTANCE_SPEC.md)
- [ARCHITECTURE_COMPLIANCE_CHECKLIST.md](./ARCHITECTURE_COMPLIANCE_CHECKLIST.md)
- [SCENARIO_INTERFACE_FREEZE.md](./SCENARIO_INTERFACE_FREEZE.md)
- [EVENT_SCHEMA_FREEZE.md](./EVENT_SCHEMA_FREEZE.md)
- [PHASE_0_5_ARCHITECTURE_FREEZE_REVIEW.md](./PHASE_0_5_ARCHITECTURE_FREEZE_REVIEW.md)
