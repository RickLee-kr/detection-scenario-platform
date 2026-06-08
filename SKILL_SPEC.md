# Detection Scenario Platform — Skill Specification

**문서 버전:** 0.2.0 (Phase 0.1)  
**상태:** Design only  
**향후 설치 경로:** `.cursor/skills/dsp-platform/SKILL.md`

---

## 1. Purpose

본 문서는 Cursor Agent가 DSP를 **구현·수정·테스트**할 때 반드시 따라야 하는 규칙이다.

Phase 1 구현 시작 시 본 문서를 Cursor Skill로 변환한다. 그 전까지는 **구현 금지**.

---

## 2. Skill Metadata (Phase 1 변환용)

```yaml
---
name: dsp-platform
description: >-
  Implements and extends the Detection Scenario Platform (Python).
  Use when building scenarios, event store, validation, reporting,
  or when the user mentions DSP, detection scenario platform,
  dns_tunnel/dga/http_followup scenarios, or Event Store SOT rules.
---
```

---

## 3. Absolute Prohibitions

다음은 **어떤 상황에서도** 구현하지 않는다:

| # | 금지 | 레거시 실패 근거 |
|---|------|------------------|
| P1 | Bash PoC 구조 유지·리팩토링 | 구조적 한계 |
| P2 | Legacy 호환 (TSV path, 함수명, event 구조) | 신규 프로젝트 |
| P3 | stdout/grep으로 success 판정 | `event_reject_stdout_only_success` |
| P4 | `execute()` 반환값으로 성공 선언 | dual-path bug |
| P5 | ICMP Tunnel 시나리오 | 지속적 zero-event 실패 |
| P6 | DNS Visibility Gate (dig/nslookup preflight blocker) | false negative |
| P7 | Resolver Validation via dig/nslookup parsing | `PARSE_ERROR` |
| P8 | Synthetic Detection Score / likelihood | 센서 무관 |
| P9 | Entropy-only DGA validation | phase model과 불일치 |
| P10 | Overlap stage `*_result.env` as state | SOT desync |
| P11 | `planned` counter를 validation input으로 사용 | `COUNTER_CONSISTENCY_BUG` |
| P12 | stage_result log를 report success 근거로 사용 | 20260605 report 모순 |
| P13 | 레거시 `stellar_poc.sh`에 기능 추가 | 별도 패키지 |
| P14 | 악성코드 실행, 권한 상승, 데이터 탈취 | Safe PoC 위반 |

---

## 4. Mandatory Design Principles

### 4.1 Runtime Path Equality Rule (CRITICAL)

```
Execution Path = Validation Path = Reporting Path
```

세 경로는 **동일한 Event Store 스냅샷**만을 입력으로 사용한다. 예외·우회·테스트 전용 분기 **없음**.

#### 4.1.1 Path Definition

| Path | Input | Output | Owner |
|------|-------|--------|-------|
| **Execution** | Scenario `execute()` | Events appended to Event Store | Scenario Plugin |
| **Validation** | Event Store (`run_id`) | `ValidationResult` | Validation Engine |
| **Reporting** | Event Store + `ValidationResult[]` | Report artifact | Reporting Engine |

#### 4.1.2 Core Rule

> **Scenario가 생성한 Event만 Validation 가능. Scenario가 생성한 Event만 Reporting 가능.**

- Validation은 execute()가 기록한 row를 aggregate한다
- Reporting은 ValidationResult와 Event sample을 표시한다
- Runner exit code는 ValidationResult에서만 파생한다

#### 4.1.3 Forbidden Parallel Paths

다음은 **어떤 경로에서도** success/failure 판정 입력으로 사용 금지:

| Forbidden Source | Category |
|------------------|----------|
| 테스트 전용 validation 함수 | Test-only path |
| Validation 전용 counter (Event 미기록) | Validation-only path |
| Report 전용 counter (Event 미기록) | Report-only path |
| `Synthetic Counter` / detection score | Synthetic |
| `Planned Counter` | Legacy tier |
| `Attempted Counter` (Event 없이 stdout/env만) | Legacy tier |
| `stdout Counter` / grep count | stdout |
| `stage_result` log | Legacy |
| overlap `*_result.env` | Legacy |

#### 4.1.4 Test Path Equality

```python
# CORRECT — test uses production path
store = EventStore(":memory:")
populate_events(store, scenario="dns_tunnel", count=1500)
result = ValidationEngine(store).validate(run_id, "dns_tunnel")
report = ReportingEngine(store).generate(run_id, [result])

# WRONG — forbidden
def test_validate_dns_tunnel_fast():
    return validate_dns_tunnel_from_stdout(stdout_fixture)  # NO

def test_report_dns_tunnel():
    return report_with_fake_counters(attempted=200)  # NO
```

pytest·CI·live run·`dsp validate`·`dsp report` — **동일** `ValidationEngine` + **동일** `EventStore` API.

#### 4.1.5 PR Gate

PR에 다음이 있으면 **즉시 거부**:

- `if TESTING:` validation 분기
- `validate_from_stdout()` 또는 유사 함수
- Report builder가 Event Store 없이 counter dict 수신
- `planned=` / `attempted=` (Event 미기록) threshold

상세: [docs/adr/0004-no-stdout-validation.md](./docs/adr/0004-no-stdout-validation.md)

### 4.2 Executor vs Validator 분리

| Component | May declare success? |
|-----------|---------------------|
| Scenario.execute() | **No** |
| ValidationEngine | **Yes** |
| ReportingEngine | **No** (reports ValidationResult) |

### 4.3 Scenario = Plugin Folder

신규 시나리오 추가 시 **허용 수정 범위:**

```
scenarios/<new_id>/**
tests/scenarios/test_<new_id>**
```

코어 변경 없이 등록되어야 함. 코어 변경이 필요하면 framework spec 먼저 수정.

### 4.4 Traffic vs Detection 분리

- Traffic validation: Event Store (필수)
- Detection confirmation: Adapter (선택, 별도 리포트 섹션)

혼합 금지.

### 4.5 Typed Python

- Protocol clients: raw socket / `httpx` / `paramiko` 등 typed library
- Bash+dig/nslookup 금지
- 설정: `manifest.yaml` + pydantic/dataclass

### 4.6 Append-Only Events

이벤트 update/delete 금지. 수정 필요 시 새 event with `status=info` correction note.

### 4.7 Safety Envelope

모든 executor는 Target Engine이 검증한 target만 사용:

- `target_net` CIDR check
- manifest `safety` block (max_events, allowed_domains, forbidden_actions)

---

## 5. Implementation Rules

### 5.1 Package Layout

```
detection-scenario-platform/
├── dsp/
│   ├── __init__.py
│   ├── runner/
│   ├── engine/
│   │   ├── scenario_engine.py
│   │   └── target_engine.py
│   ├── event_store/
│   │   ├── store.py
│   │   └── models.py
│   ├── validation/
│   │   └── engine.py
│   ├── reporting/
│   │   └── engine.py
│   └── plugins/
│       └── loader.py
├── scenarios/
└── tests/
```

레거시 repo root에 섞지 않는다. 별도 top-level package.

### 5.2 Naming Conventions

| Item | Convention | Example |
|------|------------|---------|
| Scenario ID | snake_case | `dns_tunnel`, `http_followup` |
| Event name | snake_case verb_noun | `query_sent`, `auth_attempted` |
| Status | controlled vocab (EVENT_STORE_SPEC §3.3) | `sent`, `nxdomain` |
| Module path | `scenarios.<id>.scenario` | — |
| Test file | `test_<id>_validation.py` | — |

**금지 legacy 이름:** `DNS_TUNNEL_ENH_*`, `DGA_SIMULATION`, `HTTP_URL_SCAN` as scenario id (internal mapping 문서화만 허용)

### 5.3 Scenario Implementation Checklist

새 시나리오 PR마다:

1. `manifest.yaml` with `validation` block
2. `Scenario` subclass: `prepare`, `execute`, `summarize`
3. `executor.py` — network I/O only
4. Events: `scenario_started`, traffic events, `scenario_completed`
5. Test: synthetic events → `ValidationEngine.validate()` (no network)
6. Test: integration dry-run → events in store
7. Safety block verified

### 5.4 Event Emission Rules

```python
# CORRECT
ctx.event_store.append(Event(
    run_id=ctx.run_id,
    scenario="dns_tunnel",
    event="query_sent",
    status="sent",
    target=resolver_ip,
    artifact=fqdn,
    evidence={"qtype": "A", "seq": seq},
))

# WRONG — never do this
print(f"DNS_TUNNEL_SUCCESS sent={count}")
return count > 0
```

### 5.5 Validation Implementation

```python
# CORRECT — manifest-driven
def validate(self, run_id: str, scenario_id: str) -> ValidationResult:
    metrics = self.store.aggregate(run_id, scenario_id)
    spec = self.registry.get_manifest(scenario_id).validation
    return apply_thresholds(metrics, spec)

# WRONG
def validate(self, stdout: str) -> bool:
    return "SUCCESS" in stdout
```

### 5.6 Reporting Implementation

```python
# CORRECT
for result in validation_results:
    report.add_row(result.scenario_id, result.decision, result.reason, result.metrics)

# WRONG
if "DNS_TUNNEL_FINAL_SUMMARY" in log_text:
    report.mark_success("dns_tunnel")
```

---

## 6. Validation Principles

### 6.1 Threshold Source

시나리오별 threshold는 `scenarios/<id>/manifest.yaml`의 `validation.success`에만 정의.

Validation Engine은 generic `apply_thresholds()` — 시나리오별 if/else 하드코딩 최소화.

### 6.2 Initial Thresholds (from legacy, do not weaken without approval)

| Scenario | Minimum success |
|----------|-----------------|
| dns_tunnel | `query_sent >= 1` |
| dga | `nxdomain >= 300`, `resolvable >= 10`, `base_domain == xdr.ooo` |
| http_followup | `attempted >= 1`, `responses >= 1` |
| ssh_failure | `auth_attempted >= 1` |
| sql_injection | `injection_request_sent >= 1` |

### 6.3 Fail-Fast (must implement)

| Code | Trigger |
|------|---------|
| `SOT_EMPTY_AFTER_EXECUTE` | executed + traffic event count = 0 |
| `SOT_SENT_WITHOUT_ARTIFACT` | sent > 0, unique artifact = 0 |
| `COUNTER_IMPOSSIBLE` | responses > attempted |

### 6.4 Decision Vocabulary

`success` | `partial` | `failed` | `skipped` | `CODE_FAILURE`

`success`는 Validation Engine만 설정.

---

## 7. Testing Principles

### 7.1 Same Path Rule

```python
# tests MUST call production validation
from dsp.validation.engine import ValidationEngine

def test_dns_tunnel_success():
    store = populate_dns_events(1500)
    result = ValidationEngine(store).validate(run_id, "dns_tunnel")
    assert result.decision == "success"
```

테스트 전용 validation 함수 생성 **금지**.

### 7.2 Required Test Cases (from legacy test_event_sot_architecture.sh)

| Test | Expect |
|------|--------|
| DNS 1500 events | `success` |
| HTTP 60 responses | `success` or `partial` |
| stdout only, no events | `CODE_FAILURE` / `evidence_missing` |
| DGA wrong base_domain | `failed` |
| DGA event_count only (no nx/resolvable) | `failed` |
| sent>0, event_count=0 | `CODE_FAILURE` |

### 7.3 Test Layers

| Layer | Network | Event Store |
|-------|---------|-------------|
| Unit | No | in-memory SQLite |
| Scenario validation | No | fixtures |
| Integration dry-run | No | real store |
| Live lab | Yes (manual/scheduled) | real store |

CI는 unit + scenario validation + dry-run integration 필수. Live lab은 optional workflow.

### 7.4 No Bash Test Dependency

새 테스트는 pytest. 레거시 `.sh` 테스트를 수정하지 않는다. 동등성 이식만 허용.

---

## 8. Code Review Checklist (Agent Self-Check)

PR / 구현 완료 전 확인:

- [ ] 성공 판정이 Event Store 조회에서만 발생하는가?
- [ ] stdout 파싱이 validation/reporting에 없는가?
- [ ] `execute()`가 bool/enum success를 반환하지 않는가?
- [ ] 새 시나리오가 plugin folder만으로 추가 가능한가?
- [ ] manifest `validation` block이 있는가?
- [ ] fail-fast invariant 테스트가 있는가?
- [ ] safety block (CIDR, caps)이 enforce되는가?
- [ ] 레거시 함수명/이벤트 구조를 재사용하지 않았는가?
- [ ] Detection score / likelihood 코드가 없는가?
- [ ] planned counter가 없는가?

---

## 9. Phased Implementation Guide

### Phase 0 / 0.1 (현재) — 문서만

- [x] PROJECT_CHARTER.md
- [x] ARCHITECTURE_SPEC.md
- [x] SCENARIO_FRAMEWORK_SPEC.md
- [x] EVENT_STORE_SPEC.md
- [x] SKILL_SPEC.md
- [x] DETECTION_CATALOG.md
- [x] docs/adr/ (0001–0005)
- [ ] **코드 작성 금지**

### Phase 1 — Core + One Scenario

순서:

1. `dsp/event_store/` — SQLite, Event model, append/query/aggregate
2. `dsp/validation/engine.py` — manifest-driven thresholds
3. `dsp/plugins/loader.py` — manifest scan
4. `scenarios/dns_tunnel/` — first plugin
5. `dsp/runner/` — `dsp run --scenarios dns_tunnel --dry-run`
6. Tests: §7.2 cases for dns_tunnel

### Phase 2 — Remaining MVP Scenarios

- dga, http_followup, reporting engine
- `dsp validate`, `dsp report`
- JSONL export

### Phase 3 — SSH, SQLi, Adapters

- ssh_failure, sql_injection
- Detection adapter interface + stellar stub

---

## 10. Legacy Reference Policy

레거시 파일을 읽을 때:

| 목적 | 허용 |
|------|------|
| 프로토콜 패턴 (FQDN, phase model) | ✅ |
| 검증 threshold 수치 | ✅ |
| Safe SSH/HTTP 제약 | ✅ |
| Bash 구조 복사 | ❌ |
| 함수명/변수명 복사 | ❌ |
| TSV awk 로직 포팅 | ❌ (SQL rewrite) |
| stellar_poc.sh 수정 | ❌ |

참고 파일:

- `stellar_dns_tunnel_file_client.py` — DNS tunnel executor 패턴
- `stellar_dga_model_client.py` — DGA phase model
- `stellar_poc_event_sot.sh` — threshold/fail-fast **의미만** 참고
- `tests/test_event_sot_architecture.sh` — test case **의미만** 이식

---

## 11. Documentation Rules

| Rule | |
|------|--|
| Spec 변경 시 | 해당 spec MD만 수정; 코드와 spec 동기화 |
| 새 시나리오 | `manifest.yaml` description 필수 |
| API 변경 | `event_schema_version` bump |
| 한글 | 사용자 대화·리포트는 한글 가능; 코드·spec 본문은 영어 권장 |

---

## 12. Common Agent Mistakes to Avoid

| Mistake | Correct approach |
|---------|------------------|
| "테스트 통과를 위해 validation 완화" | 이벤트 fixture 수정 |
| "빠른 구현을 위해 stdout 파싱" | Event Store append |
| "레거시 함수 재사용" | 새 Scenario class |
| "성공 시 exit 0 in executor" | ValidationEngine decision |
| "dns_tunnel + enhanced fallback" | single executor path |
| "grep log for SUCCESS" | `store.count(query)` |

---

## 13. Exit Code Mapping (Runner)

| Validation outcome | Exit code |
|--------------------|-----------|
| All success | 0 |
| Any CODE_FAILURE | 1 |
| Mixed success/failed | 2 |
| Config/safety error | 3 |

Agent는 Runner exit code가 ValidationResult에서만 파생되도록 구현.

---

## 14. Related Documents

- [PROJECT_CHARTER.md](./PROJECT_CHARTER.md)
- [ARCHITECTURE_SPEC.md](./ARCHITECTURE_SPEC.md)
- [SCENARIO_FRAMEWORK_SPEC.md](./SCENARIO_FRAMEWORK_SPEC.md)
- [EVENT_STORE_SPEC.md](./EVENT_STORE_SPEC.md)

---

## 15. Workspace Boundary (Mandatory)

모든 DSP 구현·문서 작업은 **`detection-scenario-platform/` 디렉터리 내부**에서만 수행한다.

**절대 수정 금지:**

- XDR Lab Deployment Automation (`appliance/`, `bootstrap/`, `installer/`, `scripts/`, `config/`, …)
- Terraform, Ansible, Docker Compose, CI/CD workflows
- 루트 `README.md`, `setup.py`, `requirements*.txt`, `xdr-lab.sh`
- 레거시 `stellar_poc*.sh`, `stellar_*_client.py`

**Phase 0–2 금지:**

- deployment automation과의 import / link / integration
- `aella_cli` 서브커맨드 추가
- bootstrap/installer hook

레거시 PoC 및 deployment 코드는 **read-only** 참고만. 상세: [WORKSPACE_BOUNDARY.md](./WORKSPACE_BOUNDARY.md)

---

## 16. Skill Conversion Checklist (Phase 1 Start)

Phase 1 착수 시 Agent가 수행:

1. Create `.cursor/skills/dsp-platform/SKILL.md` from this document (condensed <500 lines)
2. Move detailed tables to `.cursor/skills/dsp-platform/reference.md`
3. Add `examples.md` with dns_tunnel event examples
4. Verify skill `description` includes trigger terms
5. Do **not** set `disable-model-invocation` — auto-apply on DSP work

---

> **Phase 0 종료 조건:** 5개 spec 문서 승인 + 구현 코드 0줄.
