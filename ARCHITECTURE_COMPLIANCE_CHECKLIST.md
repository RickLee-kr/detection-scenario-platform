# Detection Scenario Platform — Architecture Compliance Checklist

**문서 버전:** 1.0.0 (Phase 0.6)  
**상태:** Implementation review checklist — **every phase must pass**  
**사용 시점:** PR review, phase gate, release candidate

---

## 1. Purpose

본 체크리스트는 구현이 **동결된 아키텍처 계약**을 위반하지 않았는지 검증한다.  
각 섹션은 Pass / Fail / N/A로 표시한다. **하나의 Fail도 phase gate에서 block**한다 (명시적 ADR 예외 제외).

**Reviewer:** _______________  
**Phase / PR:** _______________  
**Date:** _______________

---

## 2. Manifest Compliance

Reference: [SCENARIO_MANIFEST_SPEC.md](./SCENARIO_MANIFEST_SPEC.md)

| ID | Check | Pass |
|----|-------|------|
| M-1 | Every plugin has `scenarios/<id>/manifest.yaml` | ☐ |
| M-2 | `manifest_schema_version: "1.0.0"` present and valid | ☐ |
| M-3 | `id` matches directory name and `Scenario.scenario_id()` | ☐ |
| M-4 | Required fields present: name, version, description, category | ☐ |
| M-5 | `supported_targets.requires` uses known capability IDs | ☐ |
| M-6 | `supported_protocols` uses frozen enum values only | ☐ |
| M-7 | `validation_profile.profile_version: "1.0.0"` with ≥1 metric | ☐ |
| M-8 | `validation_profile.success` non-empty | ☐ |
| M-9 | `report_profile` present per spec §6 | ☐ |
| M-10 | `safety` block present with required limits | ☐ |
| M-11 | `executor` binding present per spec §10 | ☐ |
| M-12 | Loader rejects invalid manifest before ACTIVE | ☐ |
| M-13 | No use of deprecated field names (`title`, `validation` block without `_profile`) | ☐ |

---

## 3. Plugin Compliance

Reference: [PLUGIN_DISCOVERY_SPEC.md](./PLUGIN_DISCOVERY_SPEC.md)

| ID | Check | Pass |
|----|-------|------|
| P-1 | Discovery scans configured plugin root only | ☐ |
| P-2 | PluginStatus enum matches frozen values | ☐ |
| P-3 | Invalid manifest → REJECTED (not ACTIVE) | ☐ |
| P-4 | Import error → UNAVAILABLE with reason | ☐ |
| P-5 | `enabled: false` → DISABLED, discovered but not runnable | ☐ |
| P-6 | Duplicate plugin id → CONFLICT, first wins | ☐ |
| P-7 | ACTIVE plugin has loaded Scenario class | ☐ |
| P-8 | `scenario.py` required; executor optional per manifest | ☐ |
| P-9 | No core code edit required to register new valid plugin folder | ☐ |
| P-10 | Plugin reload does not mutate completed run stores | ☐ |

---

## 4. Scenario Compliance

Reference: [SCENARIO_INTERFACE_FREEZE.md](./SCENARIO_INTERFACE_FREEZE.md)

| ID | Check | Pass |
|----|-------|------|
| S-1 | Scenario implements `scenario_id()`, `prepare()`, `execute()`, `summarize()` | ☐ |
| S-2 | `execute()` return type is `None` only | ☐ |
| S-3 | No `validate()` method on Scenario | ☐ |
| S-4 | Scenario does not import ValidationEngine | ☐ |
| S-5 | Traffic events appended via `ctx.event_store.append()` only | ☐ |
| S-6 | No stdout SUCCESS markers for validation | ☐ |
| S-7 | `ScenarioSkipError` used for intentional skip (Runner writes `scenario_skipped`) | ☐ |
| S-8 | Exceptions not swallowed to fake success | ☐ |
| S-9 | `summarize()` queries Event Store only — no success declaration | ☐ |
| S-10 | No vendor if/else in scenario/executor (detection_mappings only) | ☐ |
| S-11 | No direct SQLite bypass of EventStore API | ☐ |
| S-12 | Mandatory lifecycle events for executed scenarios | ☐ |

---

## 5. Event Store Compliance

Reference: [EVENT_SCHEMA_FREEZE.md](./EVENT_SCHEMA_FREEZE.md), [EVENT_STORE_ACCEPTANCE_SPEC.md](./EVENT_STORE_ACCEPTANCE_SPEC.md)

| ID | Check | Pass |
|----|-------|------|
| E-1 | SQLite primary storage per ADR 0005 | ☐ |
| E-2 | Append-only — no UPDATE/DELETE on events in retention | ☐ |
| E-3 | Column/schema matches freeze §8 (`scenario_id` canonical) | ☐ |
| E-4 | `event_schema_version: 1.0.0` on each row | ☐ |
| E-5 | Forbidden event.status never written | ☐ |
| E-6 | `aggregate()` API drives validation metrics | ☐ |
| E-7 | Indexes on `run_id`, `scenario_id`, `status`, `event` | ☐ |
| E-8 | Per-run isolation (`~/.dsp/runs/<run_id>/events.db` or equivalent) | ☐ |
| E-9 | Completed run store is read-only | ☐ |
| E-10 | Optional JSONL export is derivative, not SOT | ☐ |

---

## 6. Validation Compliance

Reference: [EVENT_SCHEMA_FREEZE.md](./EVENT_SCHEMA_FREEZE.md) §3.4, [SCENARIO_MANIFEST_SPEC.md](./SCENARIO_MANIFEST_SPEC.md) §5

| ID | Check | Pass |
|----|-------|------|
| V-1 | ValidationEngine reads Event Store only | ☐ |
| V-2 | Thresholds from `validation_profile` only | ☐ |
| V-3 | No per-scenario if/else in core validation engine | ☐ |
| V-4 | `ValidationResult.decision` emitted only by ValidationEngine | ☐ |
| V-5 | Decision enum: success \| partial \| failed \| skipped \| code_failure | ☐ |
| V-6 | Fail-fast invariants produce `fail_fast_codes` | ☐ |
| V-7 | Results persisted as `validation.json` per run | ☐ |
| V-8 | Skip scenarios produce `decision: skipped` with reason | ☐ |
| V-9 | Tests use production ValidationEngine + Store API | ☐ |
| V-10 | No stdout/grep/planned/attempted counter inputs | ☐ |

---

## 7. Reporting Compliance

Reference: [EVENT_SCHEMA_FREEZE.md](./EVENT_SCHEMA_FREEZE.md) §3.5

| ID | Check | Pass |
|----|-------|------|
| R-1 | `report_format_version: "1.0.0"` in artifact | ☐ |
| R-2 | Primary scenario table from ValidationResult[] only | ☐ |
| R-3 | Executive summary counts match ValidationResult decisions | ☐ |
| R-4 | Event samples from Event Store with traceable ids | ☐ |
| R-5 | ScenarioSummary cannot override validation decision | ☐ |
| R-6 | No metrics in report without Store or ValidationResult provenance | ☐ |
| R-7 | stdout/debug in appendix labeled non-SOT | ☐ |
| R-8 | Report regenerable without re-execution | ☐ |
| R-9 | Detection confirmation section absent or clearly separated (Phase 1A–2) | ☐ |
| R-10 | No synthetic detection score | ☐ |

---

## 8. Detection Confidence Compliance

Reference: [DETECTION_CONFIDENCE_MODEL.md](./DETECTION_CONFIDENCE_MODEL.md)

| ID | Check | Pass |
|----|-------|------|
| C-1 | S2 (Traffic Validated) = ValidationResult — authoritative for exit code Phase 1–2 | ☐ |
| C-2 | S1 (operational/log) not used for validation or report decision | ☐ |
| C-3 | S3 (Detection Confirmed) not required for phase success in Phase 1A–2 | ☐ |
| C-4 | Report does not collapse S2 and S3 into single score | ☐ |
| C-5 | DetectionConfirmation entity not written by Scenario.execute() | ☐ |
| C-6 | Traffic validation and detection confirmation tables separated when S3 present | ☐ |

---

## 9. Repository Boundary Compliance

Reference: [WORKSPACE_BOUNDARY.md](./WORKSPACE_BOUNDARY.md)

| ID | Check | Pass |
|----|-------|------|
| B-1 | All DSP artifacts under `detection-scenario-platform/` | ☐ |
| B-2 | No modification to `appliance/`, `bootstrap/`, `installer/`, `scripts/` | ☐ |
| B-3 | No modification to CI/CD (`.github/workflows/`, etc.) | ☐ |
| B-4 | No modification to `stellar_poc*.sh` or legacy clients | ☐ |
| B-5 | No root `pyproject.toml` / workspace tooling changes | ☐ |
| B-6 | No DSP import into deployment automation | ☐ |
| B-7 | Historical draft `docs/detection-scenario-platform/` untouched | ☐ |
| B-8 | No duplicate SOT mirroring into non-canonical paths | ☐ |

---

## 10. Path Equality (Cross-Cutting)

Reference: [PATH_EQUALITY_VERIFICATION_SPEC.md](./PATH_EQUALITY_VERIFICATION_SPEC.md)

| ID | Check | Pass |
|----|-------|------|
| PE-1 | Single Event Store snapshot feeds validate and report | ☐ |
| PE-2 | No test-only validation path | ☐ |
| PE-3 | Runner exit code from ValidationResult only | ☐ |
| PE-4 | Forbidden counter sources absent in codebase | ☐ |
| PE-5 | Path Equality pytest suite passes | ☐ |

---

## 11. Sign-Off

| Result | Criteria |
|--------|----------|
| **PASS** | All applicable checks Pass; N/A documented |
| **CONDITIONAL PASS** | Fail items have linked ADR + remediation date (rare) |
| **FAIL** | Any unchecked Fail without ADR |

**Overall result:** ☐ PASS  ☐ CONDITIONAL  ☐ FAIL

**Notes:**

---

## 12. Related Documents

- [DEFINITION_OF_DONE.md](./DEFINITION_OF_DONE.md)
- [PATH_EQUALITY_VERIFICATION_SPEC.md](./PATH_EQUALITY_VERIFICATION_SPEC.md)
- [PHASE_1_ACCEPTANCE_CRITERIA.md](./PHASE_1_ACCEPTANCE_CRITERIA.md)
- [docs/adr/](./docs/adr/)
