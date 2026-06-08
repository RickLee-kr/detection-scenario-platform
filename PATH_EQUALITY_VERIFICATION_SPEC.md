# Detection Scenario Platform — Path Equality Verification Specification

**문서 버전:** 1.0.0 (Phase 0.6)  
**상태:** Formal verification criteria for frozen rule:

```
Execution Path = Validation Path = Reporting Path
```

Reference: [SKILL_SPEC.md](./SKILL_SPEC.md) §4.1, [docs/adr/0004-no-stdout-validation.md](./docs/adr/0004-no-stdout-validation.md)

---

## 1. Purpose

Path Equality는 DSP의 **핵심 불변조건(invariant)**이다.  
본 문서는 구현·테스트·리뷰 시 **합격/불합격을 기계적으로 판정**할 수 있는 기준을 정의한다.

---

## 2. Path Definitions (Frozen)

| Path | Input | Output | Writer / Reader |
|------|-------|--------|-----------------|
| **Execution** | RunContext, TargetSet, Scenario config | Events in Event Store | Scenario `execute()` **writes** Store |
| **Validation** | Event Store (`run_id`, `scenario_id`) | `ValidationResult` | ValidationEngine **reads** Store only |
| **Reporting** | Event Store + `ValidationResult[]` | Report artifact | ReportingEngine **reads** Store + Results |

**Core rule:** Scenario가 기록한 Event만 Validation 가능. ValidationResult + Event sample만 Reporting primary truth.

---

## 3. Verification Procedure

### 3.1 Static Verification (Code Review)

1. Search codebase for forbidden patterns (§6 Anti-patterns)
2. Confirm ValidationEngine has no optional `stdout` / `log_path` parameters
3. Confirm ReportingEngine primary table builder accepts only `ValidationResult[]`
4. Confirm no `if TESTING:` / `if os.getenv("DSP_TEST")` validation branches
5. Confirm Runner exit code function reads ValidationResult only

### 3.2 Dynamic Verification (Runtime)

For a given `run_id`:

1. Export Event Store snapshot (`events.db` or JSONL export)
2. Run ValidationEngine against snapshot → `validation.json`
3. Run ReportingEngine against snapshot + validation → `report.md`
4. Assert metric equality (§4 Success examples)
5. Re-run validate + report **without** re-execute → identical primary outputs

### 3.3 Test Verification (CI)

Mandatory pytest categories:

| Test | Asserts |
|------|---------|
| `test_path_equality_synthetic_events` | populate Store → validate → report metrics match |
| `test_stdout_only_rejected` | events=0 + stdout success → `code_failure` |
| `test_report_regeneration` | report from Store+validation equals post-run report |
| `test_no_test_validation_bypass` | import graph: no `validate_from_stdout` |
| `test_runner_exit_from_validation` | exit code matrix from ValidationResult only |

**Rule:** Tests MUST use production `ValidationEngine`, `ReportingEngine`, `EventStore` classes — not duplicates.

---

## 4. Success Examples

### 4.1 Dummy Scenario Dry-Run (Phase 1A)

```
1. dsp run --scenarios dummy --dry-run
2. events.db contains:
   - scenario_started (info)
   - synthetic_action (sent) × N
   - scenario_completed (info)
3. ValidationEngine aggregates query_sent count from events
4. ValidationResult.decision = success (threshold met)
5. Report scenario row: decision=success, metrics match ValidationResult
6. Runner exit code = 0 (all success)
```

**Evidence:** `events.db` + `validation.json` + `report.md` with matching metric keys.

### 4.2 Synthetic Fixture (No Network)

```python
store = EventStore(":memory:")
store.open_run(run_id="test_run", ...)
append_lifecycle_events(store, scenario_id="dummy")
append_traffic_events(store, event="synthetic_action", status="sent", count=5)

result = ValidationEngine(store, registry).validate("test_run", "dummy")
report = ReportingEngine(store).generate("test_run", [result])

assert result.metrics["synthetic_action_count"] == 5
assert report.traffic_validation[0].metrics == result.metrics
```

### 4.3 Report Regeneration

```
1. Complete run → artifacts written
2. Delete report.md only
3. dsp report --run-id <id>  (or ReportingEngine.generate offline)
4. New report primary table byte-identical to original (modulo timestamps)
```

### 4.4 Skip Path (Still Equal)

```
1. Scenario raises ScenarioSkipError in prepare
2. Runner writes scenario_skipped event
3. ValidationResult.decision = skipped
4. Report row decision = skipped
5. No execute() traffic events — validation still reads Store only
```

---

## 5. Failure Examples

### 5.1 Stdout-Only Success

```
Executor prints: "DUMMY_SUCCESS sent=100"
events.db: 0 traffic rows
ValidationEngine: success (reads stdout count)  ← FAIL
```

**Expected:** `code_failure` or fail-fast `SOT_EMPTY_AFTER_EXECUTE`; exit non-zero.

### 5.2 Dual Validation Path

```
Production: ValidationEngine(store)
Tests: validate_dummy_from_log(log_fixture)  ← FAIL
```

**Expected:** PR rejected; tests must call production engine.

### 5.3 Report Counter Injection

```
ReportingEngine.build_row(
    decision="success",
    metrics={"sent": 200}  # not from ValidationResult
)  ← FAIL
```

**Expected:** Report metrics ⊆ ValidationResult.metrics + Store samples only.

### 5.4 Execute Return Bool

```
def execute(...) -> bool:
    return sent_count > 0  ← FAIL
Runner: if scenario.execute(): mark_success()  ← FAIL
```

**Expected:** `execute()` returns `None`; Runner never branches on return value.

### 5.5 Planned Counter Validation

```
manifest sets planned=1000
ValidationEngine: success if attempted/planned >= 0.9  ← FAIL
(events never recorded for attempted)  ← FAIL
```

**Expected:** Only event-derived metrics in validation_profile.

### 5.6 TESTING Bypass

```python
if os.getenv("PYTEST_CURRENT_TEST"):
    return ValidationResult(decision="success", ...)  ← FAIL
```

---

## 6. Anti-Patterns (Forbidden)

| Anti-pattern | Category | Detection |
|--------------|----------|-----------|
| `validate_from_stdout()` | stdout parsing | grep codebase |
| `grep -c query_sent log` | grep parsing | shell in validation |
| `planned` counter in validation_profile or engine | planned counter | manifest/code review |
| `attempted` without matching events | attempted counter | aggregate vs event count |
| In-memory counter passed to ValidationEngine | synthetic counter | type signature audit |
| Report builder `fake_metrics=` parameter | report-only counter | API review |
| Validation-only counter dict | validation-only path | separate from Store |
| `stage_result.env` / `*_result.env` | legacy overlap | grep repo |
| `ValidationService_BypassForTests` | test-only path | class name / env flag |
| `ReportCounterBuilder` | non-event report | class responsibility |
| `StdoutSummaryParser` in Runner | stdout in orchestration | Runner code review |
| Executor `print("SUCCESS")` for validation | stdout marker | scenario review |
| `if vendor == "stellar"` in execute | wrong layer | scenario code |

---

## 7. Required Evidence

Phase gate / PR MUST include:

| Evidence | Format | Proves |
|----------|--------|--------|
| Path Equality pytest output | CI log / local pytest -v | Dynamic equality |
| Sample run artifacts | `events.db`, `validation.json`, `report.md` | End-to-end trace |
| Metric trace table | Markdown or test assert | Each report metric → ValidationResult → aggregate SQL |
| Code search attestation | `rg` output showing no forbidden symbols | Static compliance |
| Regeneration diff | report before/after | Reporting reads Store+validation only |

### 7.1 Metric Trace Table Template

| Report field | ValidationResult field | Store aggregate | Event filter |
|--------------|------------------------|-----------------|--------------|
| decision | decision | — | — |
| synthetic_action_count | metrics.synthetic_action_count | COUNT | event=synthetic_action, status=sent |

Every populated report metric row MUST be fillable.

---

## 8. Forbidden Evidence

다음은 Path Equality **증명으로 인정하지 않는다**:

| Forbidden evidence | Why invalid |
|--------------------|-------------|
| Executor stdout showing "sent=N" | S1, not SOT |
| debug.log line counts | Non-SOT |
| Manual operator observation | S1 |
| Separate test ValidationEngine class | Test-only path |
| Spreadsheet / ad-hoc metrics | Non-reproducible |
| `planned` / `attempted` env files | Legacy overlap |
| CI artifact that skips Event Store | Bypass |
| Screenshot of successful traffic | No Store proof |
| Detection platform alert | S3, not S2 |

**Rule:** If evidence cannot be reproduced from `events.db` (+ manifest) alone, it does not prove Path Equality.

---

## 9. Acceptance Threshold

| Criterion | Threshold |
|-----------|-----------|
| Forbidden anti-patterns in production code | **0** |
| Path Equality tests | **100% pass** |
| Report metrics without trace | **0** |
| Test validation bypass functions | **0** |
| Runner exit code derived from non-ValidationResult source | **0** |

---

## 10. Related Documents

- [DEFINITION_OF_DONE.md](./DEFINITION_OF_DONE.md) §2.2
- [ARCHITECTURE_COMPLIANCE_CHECKLIST.md](./ARCHITECTURE_COMPLIANCE_CHECKLIST.md) §10
- [PHASE_1_ACCEPTANCE_CRITERIA.md](./PHASE_1_ACCEPTANCE_CRITERIA.md) §7.5
- [EVENT_STORE_ACCEPTANCE_SPEC.md](./EVENT_STORE_ACCEPTANCE_SPEC.md)
- [DETECTION_CONFIDENCE_MODEL.md](./DETECTION_CONFIDENCE_MODEL.md)
