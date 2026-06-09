# DSP v1.2.0 Release Readiness Revalidation

**Audit Date:** 2026-06-09  
**Audit Type:** Read-only 2차 감사 — 1차 Operational Audit 사실 재검증  
**Repository:** `/home/aella/xdr-lab-appliance`  
**Primary Code Root:** `detection-scenario-platform/`  
**Package Version (code):** `1.1.0` (`pyproject.toml` L3)

---

## 1. Executive Summary

본 2차 감사는 코드 수정·구현 없이, 1차 감사(`docs/operational-design-audit-v1.2.0.md`) 결론을 저장소 코드·문서로 재검증한다.

### 핵심 질문 답변

| # | 질문 | 답변 |
|---|------|------|
| 1 | DSP가 실제로 Remote Scenario Runner를 구현했는가? | **PARTIAL** — `RemoteScenarioRunner` 클래스 존재; `dsp-remote-scenario` 실행체 미존재; `RunManager` 미통합 |
| 2 | DSP가 실제로 JSP/PHP/ASPX 원격 실행을 구현했는가? | **PARTIAL** — HTTP webshell transport로 명령 **전달** 구현; `delivery_only: True`; 원격 호스트 webshell 서버 및 `dsp-remote-scenario` 외부 의존 |
| 3 | DSP가 실제로 Remote Event Collection을 구현했는가? | **YES (코드 경로)** — `RemoteEventCollector` + `EventSyncBridge` 구현·테스트 존재 |
| 4 | PROJECT / PRODUCT / MASTER_WBS 설계 충돌? | **YES** — `PRODUCT_CHARTER`·`MASTER_WBS` 부재; `PROJECT_CHARTER` L47 vs 1차 PRODUCT 기대 상충 (상세: `documentation-consistency-audit.md`) |
| 5 | Release NOT READY 판정 객관적 타당? | **YES** — 아래 Blocker·Readiness 재검증 결과 동일 결론 |

---

## 2. Documentation Consistency Audit

상세 표·원문 인용: [`documentation-consistency-audit.md`](./documentation-consistency-audit.md)

| 결과 | **CONFLICTED** |
|------|----------------|
| PROJECT vs PRODUCT | MAJOR CONFLICT |
| PROJECT vs WBS (1차 기준) | PARTIAL CONFLICT |
| Validation/Reporting 철학 | CONSISTENT (코드와 PROJECT/DEFINITION_OF_DONE 일치) |

---

## 3. Remote Execution Audit

### 3.1 구현체 존재 여부 (WBS 기준)

| WBS 항목 | 존재 | 분류 | 코드 근거 |
|----------|:----:|------|-----------|
| Real JSP Execution | YES | **PARTIAL** | `dsp/execution/providers/webshell/jsp/provider.py`, `jsp_runtime.py` L78–139 |
| Real PHP Execution | YES | **PARTIAL** | `dsp/execution/providers/webshell/php/provider.py`, `php_runtime.py` (`delivery_only: True`) |
| Real ASPX Execution | YES | **PARTIAL** | `dsp/execution/providers/webshell/aspx/provider.py`, `aspx_runtime.py` |
| Remote Command Execution | YES | **PARTIAL** | `WebshellExecutionProvider.execute_command()` → family provider → HTTP GET/POST |
| Remote Scenario Runner | YES | **PARTIAL** | `dsp/execution/remote/runner.py` L20–37 `RemoteScenarioRunner` |
| Remote Event Collection | YES | **COMPLIANT** | `dsp/execution/remote/collector.py` L26–71 `RemoteEventCollector` |

### 3.2 확인 질문 (YES/NO)

| # | 질문 | 답 | 증거 |
|---|------|----|------|
| 1 | RunManager가 Webshell Provider를 실제 실행 경로로 사용하는가? | **NO** | `run_manager.py` L169: `create_execution_provider("local")` 고정. webshell 호출 없음 |
| 2 | Webshell Provider가 실제 원격 명령 실행을 수행하는가? | **PARTIAL → YES (전달)** | `webshell_provider.py` L173–186 `execute_command()` → `family_provider.execute_command()` → `jsp_runtime.py` L98–109 HTTP send_get/send_post. 응답 body 파싱·명령 결과 해석 없음 (`delivery_only: True`, L137) |
| 3 | JSP 실행 구현 존재? | **YES** | `JspWebshellProvider` + `JspWebshellRuntime.execute_command()` |
| 4 | PHP 실행 구현 존재? | **YES** | `PhpWebshellProvider` + `PhpWebshellRuntime` |
| 5 | ASPX 실행 구현 존재? | **YES** | `AspxWebshellProvider` + `AspxWebshellRuntime` |
| 6 | 원격에서 Scenario 실행 구현 존재? | **PARTIAL** | `RemoteScenarioRunner.run()` L26–37: webshell에 `dsp-remote-scenario` 명령 **전달**만 수행. 원격 호스트에서 시나리오 실행은 외부 `dsp-remote-scenario` 의존 |
| 7 | `dsp-remote-scenario` 실제 존재? | **NO** | `remote/payload.py` L10 상수만 존재. `pyproject.toml` L16–17 entry point는 `dsp`만 |
| 8 | Remote Bundle Download 존재? | **YES** | `WebshellExecutionProvider.download_file()` L193–196; `RemoteEventCollector.collect()` L49 `provider.download_file()` |
| 9 | Remote Event Collection 존재? | **YES** | `RemoteEventCollector.collect()` L56 `EventSyncBridge.sync_bundle()` |

### 3.3 분류 요약

| 영역 | 분류 |
|------|------|
| JSP/PHP/ASPX HTTP Transport | **PARTIAL** (delivery only) |
| Remote Scenario Runner (class) | **COMPLIANT** (코드 존재) |
| Remote Scenario Runner (end-to-end) | **NOT IMPLEMENTED** (`dsp-remote-scenario` 없음) |
| Remote Event Collection | **COMPLIANT** (코드·테스트 존재) |
| RunManager 통합 | **NOT IMPLEMENTED** |

---

## 4. Execution Path Audit

### 4.1 Local Path (실제 연결 여부)

```
RunManager.run()
  → create_execution_provider("local")          [run_manager.py L169]
  → LocalExecutionProvider.execute()
  → run_scenario()                              [local_provider.py L43]
  → Scenario executor → EventStore.append()
  → ValidationEngine.validate_run()             [run_manager.py L201–202]
  → ReportingEngine.generate()                  [run_manager.py L224–228]
  → EventStore.export_jsonl()                   [run_manager.py L231]
```

**판정: 끝까지 연결됨 (COMPLETE)**

### 4.2 Remote Path — RunManager 경로

```
RunManager.run()
  → create_execution_provider("local")          [L169 — webshell 분기 없음]
```

**판정: RunManager 진입점에서 끊김 (BROKEN at step 1)**

### 4.2 Remote Path — operational_runner 경로

```
operational_runner.run_webshell_lab()
  → create_execution_provider("webshell", ...)  [operational_runner.py L218–224]
  → WebshellExecutionProvider.prepare()         [L234]
  → provider.execute_command() (preflight)      [L236–244]
  → RemoteScenarioRunner().run()                [L258]
      → build_scenario_command() → "dsp-remote-scenario" [payload.py L10, L28–31]
      → provider.execute_command(command)       [runner.py L36]
      → HTTP to webshell URL                    [jsp_runtime.py L98–109]
  → [REMOTE HOST] dsp-remote-scenario 실행      *** 저장소에 실행체 없음 — 끊김 ***
  → [REMOTE HOST] events.jsonl 작성             *** 외부 의존 ***
  → RemoteEventCollector().collect()            [operational_runner.py L267–274]
      → provider.download_file(bundle_path)     [collector.py L49]
      → EventSyncBridge.sync_bundle()           [collector.py L56, bridge.py L22–67]
  → EventStore (imported events)
  → EvidenceExporter / ManualVerification       [operational_runner.py L279+]
```

**판정: DSP 호스트 측 코드는 Bundle Import까지 연결. Remote Scenario 실행 단계에서 끊김 (`dsp-remote-scenario` 미구현)**

### 4.3 E2E 테스트 경로

`tests/e2e/fixtures/webshell_test_server.py` L114–163: 테스트 서버가 `dsp-remote-scenario` 명령 수신 시 **합성 bundle** 생성. 실제 원격 시나리오 실행·live traffic 아님.

`tests/e2e/test_release_1_0_webshell_flow.py` L68–118: mock HTTP 서버 + bundle sync로 Event Store 도달 검증.

**판정: 테스트는 mock 서버로 gap을 메움. production remote path는 in-repo 미완성.**

### 4.4 시나리오 remote_capable

12개 시나리오 `manifest.yaml` 전부 `remote_capable: false` (grep 결과). 원격 시나리오 실행이 manifest 수준에서도 비활성 표기.

---

## 5. Operational Readiness Revalidation

1차 감사 §9 재검증. 평가: READY / PARTIAL / NOT READY.

| 항목 | 1차 판정 | 2차 재검증 | 근거 |
|------|----------|------------|------|
| Platform Ready | NOT READY | **PARTIAL** | Event Store, Validation, Reporting, 12 시나리오, 113+ test files 동작. 버전 1.1.0 ≠ v1.2.0; charter 문서 gap |
| Traffic Generator Ready | NOT READY | **NOT READY** | `dns_dummy` L21 항상 `mock=True`; 10/12 live I/O 가능하나 validation outcome 의존 시나리오 존재 (dga, ssh, smb) |
| Remote Execution Ready | (1차: webshell PARTIAL) | **PARTIAL** | Webshell HTTP transport + factory 구현. RunManager 미통합 |
| Remote Scenario Runner Ready | (1차: PARTIAL) | **PARTIAL** | Class 존재; binary·RunManager·manifest `remote_capable` 모두 미비 |
| Operational Ready | NOT READY | **PARTIAL** | `operational_runner.py` local+webshell lab entry 존재; automated live traffic CI 없음 |
| Release Ready | NOT READY | **NOT READY** | Blocker B1–B3 재확인 |

---

## 6. Blocker Validation

| ID | 1차 Blocker | 2차 분류 | 재검증 근거 |
|----|-------------|----------|-------------|
| B1 | `dns_dummy` live traffic 불가 | **CONFIRMED** | `scenarios/dns_dummy/executor.py` L21: `DnsClient(dry_run=True, mock=True)` — live UDP 전송 코드 경로 없음 |
| B2 | remote scenario runner missing | **PARTIALLY CONFIRMED** | `RemoteScenarioRunner` 클래스 **존재** (`remote/runner.py`). `dsp-remote-scenario` **실행체 미존재** (`payload.py` L10, `pyproject.toml` L16–17). 1차 "missing"은 binary 관점에서 CONFIRMED, class 관점에서 REJECTED → **PARTIALLY CONFIRMED** |
| B3 | live traffic validation absent | **CONFIRMED** | 1차 §6.3: real traffic generation 테스트 0건. `tests/e2e/` webshell flow는 `WebshellTestServer` mock. pytest 전부 mock/dry-run/store-injection 기반 |

---

## 7. Final Verdict

```
Documentation Status:
CONFLICTED

Remote Execution:
PARTIAL

Remote Scenario Runner:
PARTIAL

Remote Event Collection:
PARTIAL

Release Readiness:
NOT READY
```

### 근거 (코드 기반)

**Remote Scenario Runner — PARTIAL**
- `RemoteScenarioRunner` (`remote/runner.py` L20–37)와 `WebshellExecutionProvider.execute()` (`webshell_provider.py` L167–168)에서 호출됨
- `dsp-remote-scenario`는 문자열 상수(`payload.py` L10)뿐이며 pyproject entry point 없음
- `RunManager`는 `local` provider만 사용 (`run_manager.py` L169)
- 12개 시나리오 manifest `remote_capable: false`

**JSP/PHP/ASPX — PARTIAL**
- Provider·Runtime 클래스 3종 모두 존재, HTTP GET/POST로 `cmd` 파라미터 전달
- `delivery_only: True` — transport 성공만 기록, 명령 출력·원격 프로세스 결과 미해석 (`jsp_runtime.py` L137)
- in-repo webshell 서버 없음; lab 외부 endpoint 필요

**Remote Event Collection — PARTIAL**
- `RemoteEventCollector.collect()` + `EventSyncBridge.sync_bundle()` 구현 완료 (`collector.py`, `bridge.py`)
- `operational_runner.run_webshell_lab()`에서 자동 호출 (`operational_runner.py` L267–274)
- End-to-end 수집은 원격 bundle 생성(`dsp-remote-scenario`)에 의존 — 해당 단계 미구현으로 **운영 완결성 PARTIAL**

**Release NOT READY — 타당**
- B1 CONFIRMED, B3 CONFIRMED, B2 PARTIALLY CONFIRMED
- `pyproject.toml` version `1.1.0` (v1.2.0 라벨과 불일치)
- `PRODUCT_CHARTER`·`MASTER_WBS` 부재로 release completion criteria 저장소 내 정의 불완전
- 1차 NOT READY 판정 **객관적으로 타당**

---

## 8. 1차 감사 대비 변경·확정 사항

| 항목 | 1차 | 2차 | 비고 |
|------|-----|-----|------|
| RemoteScenarioRunner 클래스 | YES | **YES** (재확인) | 변경 없음 |
| dsp-remote-scenario binary | NO | **NO** (재확인) | 변경 없음 |
| RunManager webshell | NO | **NO** (재확인) | 변경 없음 |
| RemoteEventCollector | COMPLIANT | **COMPLIANT (코드)** / **PARTIAL (E2E)** | 운영 완결성 관점에서 2차는 PARTIAL로 세분 |
| B2 분류 | BLOCKER | **PARTIALLY CONFIRMED** | 클래스 존재 사실 반영 |
| Release Ready | NOT READY | **NOT READY** | 동일 결론 유지 |

---

*본 문서는 코드·저장소 문서만을 근거로 작성되었으며, 설계 제안·구현·추정을 포함하지 않는다.*
