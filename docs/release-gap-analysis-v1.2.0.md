# DSP v1.2.0 Release Gap Analysis

**Analysis Date:** 2026-06-09  
**Scope:** 전체 Repository (`detection-scenario-platform/` 중심)  
**기준:** 사용자가 정의한 최종 동작 (Detection Scenario 실행 + Evidence 제공, 탐지/Alert/Case 판단 없음)  
**Package Version:** `1.1.0` (`pyproject.toml` L3)

---

## 사용자 목표 (분석 기준)

| # | 요구 | DSP 역할 |
|---|------|----------|
| 1 | Local Host **또는** Webshell Remote Host에서 실제 Detection Scenario 실행 | 실행·이벤트 기록 |
| 2 | 실제 네트워크 트래픽 생성 (DNS/HTTP/SSH/LDAP/SMB/Kerberos/Port Scan) | 트래픽 발생 |
| 3 | Stellar Sensor 관찰 가능 | lab 네트워크 전제 (DSP는 evidence만 제공) |
| 4 | 사용자가 Stellar UI에서 Alert/Logs/Events/Cases **수동 확인** | DSP 미판단 |
| 5 | Execution Evidence / Events / Evidence Package 제공 | DSP 산출물 |

**DSP가 하지 않는 것:** 탐지 성공, Alert 생성, Case 생성 판단.

---

## 1. End-to-End Flow Analysis

### 1.1 Local Flow

목표: `RunManager → Scenario → Traffic Generation → Event Store → Evidence Export`

| 단계 | 상태 | 근거 |
|------|------|------|
| RunManager 진입 | **IMPLEMENTED** | `dsp run` / `RunManager.run()` (`cli.py`, `run_manager.py`) |
| Scenario 실행 | **IMPLEMENTED** | `LocalExecutionProvider.execute()` → `run_scenario()` (`local_provider.py` L43) |
| Traffic Generation | **PARTIAL** | 10/12 시나리오 live I/O 가능; `dummy`·`dns_dummy`는 네트워크 미전송 |
| Event Store 기록 | **IMPLEMENTED** | `EventStore.append()` 경로 완결 |
| Validation / Reporting | **IMPLEMENTED** | `ValidationEngine` + `ReportingEngine` (`run_manager.py` L201–229) |
| Evidence Export | **MISSING** | `RunManager`·`dsp run`이 `EvidenceExporter` / `ManualVerificationPackageGenerator` 호출 안 함. `operational_runner.run_local_lab()`에서만 호출 (`operational_runner.py` L107–112) |

**Local Flow 종합: PARTIAL** — 핵심 실행·SOT는 완결; 표준 CLI 경로에 Evidence Package 없음.

### 1.2 Remote Flow

목표: `RunManager → Webshell Provider → Remote Scenario Runner → Traffic Generation → Bundle Collection → Event Import → Event Store → Evidence Export`

| 단계 | 상태 | 근거 |
|------|------|------|
| RunManager → Webshell Provider | **MISSING** | `run_manager.py` L169: `create_execution_provider("local")` 고정 |
| Webshell Provider 연결 | **IMPLEMENTED** | `WebshellExecutionProvider.prepare()` — JSP/PHP/ASPX (`webshell_provider.py`) |
| Remote Scenario Runner (명령 전달) | **IMPLEMENTED** | `RemoteScenarioRunner.run()` (`remote/runner.py` L26–37) |
| Remote Traffic / Scenario 실행 | **MISSING** | `dsp-remote-scenario` 실행체 저장소에 없음 (`payload.py` L10 상수만; `pyproject.toml` entry `dsp`만). `WebshellExecutionProvider.execute()`는 명령 전달 후 `None` 반환, in-process 시나리오 미실행 (`webshell_provider.py` L157–171) |
| Bundle Collection (download) | **IMPLEMENTED** | `RemoteEventCollector.collect()` → `download_file()` (`collector.py` L49) |
| Event Import | **IMPLEMENTED** | `EventSyncBridge.sync_bundle()` (`bridge.py` L22–67) |
| Event Store | **IMPLEMENTED** | import 경로 동작 (E2E mock 서버 검증: `test_release_1_0_webshell_flow.py`) |
| Validation / Reporting | **MISSING** | `operational_runner.run_webshell_lab()`에 `ValidationEngine`·`ReportingEngine` 없음 |
| Evidence Export | **IMPLEMENTED** | `operational_runner` webshell 경로에서 `_export_artifacts()` 호출 (L279–283) |

**Remote Flow 종합: PARTIAL** — transport·bundle import까지 코드 존재; RunManager 미연결, 원격 시나리오 실행체·validation·표준 CLI 통합 부재.

### 1.3 진입점 분리 (Gap)

| 진입점 | Local Scenario | Remote Scenario | Evidence Package | Validation/Report |
|--------|:--------------:|:---------------:|:----------------:|:-----------------:|
| `dsp run` / RunManager | YES | NO | NO | YES |
| `operational_runner --mode local` | YES | NO | YES | YES (RunManager 경유) |
| `operational_runner --mode webshell` | NO | PARTIAL | YES | NO |

사용자 목표의 **단일 플랫폼 진입점** 관점에서 RunManager 기준 Remote·Evidence 통합이 Gap.

---

## 2. Scenario Operational Readiness

평가 기준:
- **Local Execution:** `dsp run` 또는 `operational_runner --mode local`로 시나리오 실행 가능
- **Remote Execution:** webshell 경로에서 해당 시나리오가 원격 호스트에서 실제 실행됨
- **Real Traffic Generation:** `dry_run=False` 시 센서 관찰 가능한 네트워크 I/O
- **Evidence Generation:** Evidence Package (JSON/MD evidence + manual verification templates)

| Scenario | Local Exec | Remote Exec | Real Traffic | Evidence |
|----------|:----------:|:-----------:|:------------:|:--------:|
| `dummy` | READY | MISSING | MISSING | PARTIAL |
| `dns_dummy` | READY | MISSING | MISSING | PARTIAL |
| `dns_transport_dummy` | READY | MISSING | READY | PARTIAL |
| `dns_tunnel` | READY | MISSING | READY | PARTIAL |
| `dga` | READY | MISSING | READY | PARTIAL |
| `http_followup` | READY | MISSING | READY | PARTIAL |
| `kerberos_failure` | READY | MISSING | READY | PARTIAL |
| `ldap_enumeration` | READY | MISSING | READY | PARTIAL |
| `port_sweep` | READY | MISSING | READY | PARTIAL |
| `smb_login_failure` | READY | MISSING | PARTIAL | PARTIAL |
| `sql_injection` | READY | MISSING | READY | PARTIAL |
| `ssh_failure` | READY | MISSING | READY | PARTIAL |

**Evidence 열 PARTIAL 공통 이유:** `dsp run` 경로는 `events.db`·`report.md`·`events.jsonl`만 생성; `EvidenceExporter`·`ManualVerificationPackageGenerator`는 `operational_runner`에서만 호출.

**Remote Exec 열 MISSING 공통 이유:**
1. 12개 manifest 전부 `remote_capable: false`
2. `dsp-remote-scenario` 미구현 — 원격 호스트에서 시나리오 executor 미실행
3. `RunManager` webshell 분기 없음

**Real Traffic 세부 Gap:**
- `dummy`: EventStore synthetic append only (`scenario.py` L39–55), socket/subprocess 없음
- `dns_dummy`: `DnsClient(dry_run=True, mock=True)` 고정 (`executor.py` L21)
- `smb_login_failure`: TCP/445 connect only, SMB auth negotiation 없음 (`smb/client.py` L54–66, `note: tcp_connect_only_no_credentials`)

---

## 3. Webshell Readiness (JSP / PHP / ASPX)

| Layer | JSP | PHP | ASPX |
|-------|:---:|:---:|:----:|
| Transport Layer | READY | READY | READY |
| Runtime Layer | READY | READY | READY |
| Scenario Execution | MISSING | MISSING | MISSING |
| Artifact Upload | READY | READY | READY |
| Bundle Download | READY | READY | READY |
| Event Collection | READY | READY | READY |

**근거:**
- Transport: `RealHttpTransport` — GET/POST/multipart (`webshell/transport/`)
- Runtime: `JspWebshellRuntime` / `PhpWebshellRuntime` / `AspxWebshellRuntime` — `execute_command()` HTTP 전달 (`jsp_runtime.py` L78–139, `delivery_only: True`)
- Upload/Download: `transport_runtime.py` L279–300 + provider wrapper (`jsp/provider.py` L102–117)
- Event Collection: `RemoteEventCollector` + `EventSyncBridge` (family 무관)
- **Scenario Execution MISSING:** webshell은 명령 문자열 `dsp-remote-scenario {json}` 전달만 수행. 원격에서 `run_scenario()`·protocol client를 호출하는 in-repo 실행체 없음. E2E는 `WebshellTestServer`가 합성 bundle 생성으로 gap 메움 (`webshell_test_server.py` L114–163).

---

## 4. Release Gap Matrix (남은 작업만)

이미 구현된 항목(Event Store, LocalExecutionProvider, ValidationEngine, ReportingEngine, Webshell HTTP transport, RemoteEventCollector, EventSyncBridge, EvidenceExporter, ManualVerificationPackage, 10개 live 시나리오 executor)은 **제외**.

| Gap ID | 남은 작업 | 영향 |
|--------|-----------|------|
| G1 | **`dsp-remote-scenario` 실행체** — 원격 호스트에서 시나리오 plugin·protocol client 실행, `events.jsonl` bundle 작성 | Remote Host Detection Scenario 실행 불가 |
| G2 | **RunManager Webshell 통합** — provider 선택, remote flow 오케스트레이션 | 사용자 목표 Remote Flow가 `dsp run`으로 불가 |
| G3 | **원격 시나리오 실행 후 Validation/Reporting** — webshell 경로에 `ValidationEngine`·`ReportingEngine` 연결 | Remote run의 S2 판정·report 산출물 없음 |
| G4 | **`dsp run` Evidence Package 통합** — `EvidenceExporter` + `ManualVerificationPackageGenerator`를 RunManager 완료 경로에 포함 | 표준 CLI로 Evidence Workflow 미완 |
| G5 | **Manifest `remote_capable` 및 remote 실행 계약** — 12개 시나리오 전부 `false`; remote 실행 대상·파라미터 전달 규약 미정의 | Remote 시나리오 운영 매트릭스 없음 |
| G6 | **`dns_dummy` live traffic 경로** — 항상 mock (`executor.py` L21) | DNS validation 시나리오로 live 트래픽 불가 |
| G7 | **`smb_login_failure` 실제 SMB auth 트래픽** — TCP connect only | SMB 탐지 시나리오로서 센서 관찰 트래픽 부족 |
| G8 | **Live lab 트래픽 검증** — pytest 전부 mock/dry-run; automated live target_net 테스트 0건 | 운영 신뢰도 검증 수단 없음 |
| G9 | **단일 CLI remote 옵션** — `dsp run`에 `--mode webshell`·`--webshell-url` 등 없음; `operational_runner` 스크립트 분리 | 운영 진입점 이원화 |
| G10 | **Remote bundle lifecycle 오류 처리** — bundle 미생성·download 실패·run_id mismatch 시 operational 복구 경로 미정의 (코드는 예외 throw 수준) | 원격 실행 실패 시 운영 복구 어려움 |

---

## 5. Fix Priority

### P0 — 없으면 Detection Scenario 실행 불가 (목표 관점)

| ID | Gap | 이유 |
|----|-----|------|
| G1 | `dsp-remote-scenario` 실행체 | Webshell Remote Host에서 시나리오·트래픽 생성 자체가 불가 |
| G2 | RunManager Webshell 통합 | 사용자 목표 흐름의 Remote 진입점 없음 |
| G5 | Manifest remote 지원 + remote 실행 계약 | 어떤 시나리오를 원격 실행할지 플랫폼 수준 정의 없음 |

### P1 — 동작은 하지만 운영 불가

| ID | Gap | 이유 |
|----|-----|------|
| G3 | Remote Validation/Reporting | Remote run 후 validation.json·report 없음 |
| G4 | `dsp run` Evidence Package | 운영자가 표준 CLI만으로 Evidence·Manual Verification 수령 불가 |
| G6 | `dns_dummy` live traffic | DNS 계열 live 검증 시나리오 dead-end |
| G9 | 단일 CLI remote 옵션 | lab 운영 시 스크립트·API 이원화 |
| G10 | Remote bundle lifecycle | 원격 실패 시 run artifact 불완전 |

### P2 — 운영 가능하지만 품질 개선

| ID | Gap | 이유 |
|----|-----|------|
| G7 | SMB 실제 auth 트래픽 | SMB 시나리오 센서 가시성 향상 |
| G8 | Live lab automated tests | regression·release confidence |
| — | `dummy` 시나리오 | architecture용; 운영 traffic matrix에서 제외 권장 수준 |

---

## 6. Completion Estimate

코드·연결 상태 기준 추정 (구현 분량 아님, **기능 완결도**).

| 영역 | Completion | 근거 |
|------|:----------:|------|
| Platform Completion | **88%** | Event Store, Scenario Engine, Plugin Loader, Local Provider, Validation, Reporting, 12 시나리오 plugin |
| Remote Execution | **38%** | Transport·Runner·Collector 구현; 실행체·RunManager·E2E live 미완 |
| Scenario Execution (Local) | **83%** | 10/12 live traffic; `dummy`·`dns_dummy` 제외; SMB partial |
| Scenario Execution (Remote) | **8%** | 명령 전달 shell만; 실제 remote executor 없음 |
| Evidence Workflow | **72%** | Exporter·ManualVerification 구현; `dsp run`·remote validation 경로 미연결 |
| Stellar Manual Verification Support | **85%** | Manual verification templates·checklist 존재; operational_runner 한정 |
| **Overall** | **74%** | Local-first 플랫폼은 사용 가능; 사용자 목표( Local **또는** Remote unified platform) 기준 미완 |

---

## 7. 최종 결론

### 현재 DSP가 할 수 있는 것

1. **DSP Host (Local)에서** `dsp run` 또는 `operational_runner --mode local`로 10개 시나리오의 **실제 네트워크 트래픽** 생성 (DNS/HTTP/SSH/LDAP/Kerberos/TCP scan 등, `dummy`·`dns_dummy`·SMB partial 제외).
2. 실행 이벤트를 **Event Store (SQLite SOT)** 에 기록하고, Local 경로에서 **Validation·Report** (`validation.json`, `report.md/json`, `events.jsonl`) 생성.
3. `operational_runner` 경로에서 **Evidence Package** (JSON/MD evidence + manual verification checklist/notes) 생성.
4. Webshell **HTTP transport**로 원격 호스트에 명령 전달, **bundle download·Event Store import** (lab/mock 환경에서 검증됨).
5. `--confirm-detection`은 **optional**이며 기본 success 경로와 분리 — DSP가 Alert/Case를 판단하지 않음 (`run_manager.py` L206–219, optional flag).

### 현재 DSP가 할 수 없는 것

1. **Webshell Remote Host에서 실제 Detection Scenario 실행** — `dsp-remote-scenario` 없음; 원격 트래픽·시나리오 executor 미실행.
2. **`dsp run` 단일 진입점으로 Remote Flow 완결** — RunManager는 local only.
3. **Remote run의 Validation·Reporting** — webshell lab 경로에 없음.
4. **`dsp run`만으로 Evidence Package 수령** — EvidenceExporter가 RunManager에 미연결.
5. **12개 시나리오 중任意 remote 실행** — manifest `remote_capable: false`, remote 실행 계약 없음.
6. **`dns_dummy` live UDP/53 트래픽** — mock 고정.
7. **SMB login failure로 실제 SMB auth 패킷** — TCP connect만.

### Release NOT READY의 진짜 이유

Release NOT READY는 문서·이름 문제가 아니라 **구현 연결 Gap** 때문이다.

| 순위 | 이유 |
|------|------|
| 1 | 사용자 목표의 **Remote Detection Scenario 실행 경로 미완성** (`dsp-remote-scenario` + RunManager 통합) |
| 2 | **단일 운영 진입점 부재** — local은 `dsp run`, remote·evidence는 `operational_runner` 분리 |
| 3 | **Remote run 산출물 불완전** — validation/report 없음 |
| 4 | **일부 시나리오 live traffic dead-end** — `dns_dummy`, SMB partial |
| 5 | **Automated live lab 검증 없음** — release confidence 부족 |

### 사용자 목표 플랫폼 완성을 위해 남은 구현 (정확히)

```
P0 (필수)
├── dsp-remote-scenario
│     └── 원격 호스트: scenario plugin 로드 → protocol client live 실행 → events.jsonl 작성
├── RunManager webshell mode
│     └── provider 선택 → RemoteScenarioRunner → RemoteEventCollector → Event Store
└── Manifest remote_capable + remote 실행 파라미터 계약

P1 (운영 완결)
├── RunManager 완료 시 EvidenceExporter + ManualVerificationPackage 자동 생성
├── Webshell 경로 ValidationEngine + ReportingEngine 연결
├── dsp run CLI에 remote/webshell/evidence 옵션 통합 (operational_runner 흡수 또는 위임)
├── dns_dummy live mode (또는 운영 matrix에서 제외 정책 코드 반영)
└── Remote bundle 실패·timeout·retry 운영 처리

P2 (품질)
├── smb_login_failure 실제 SMB negotiation 트래픽
└── Opt-in live lab integration tests
```

**한 줄 요약:** Local Detection Scenario 실행·이벤트·(부분) Evidence는 동작한다. 사용자가 원하는 **"Local 또는 Remote Host에서 동일하게 Detection Scenario를 실행하고 Evidence를 남기는 단일 플랫폼"** 을 완성하려면, **`dsp-remote-scenario` 구현**과 **RunManager 기준 Remote·Evidence·Validation 통합**이 남은 핵심 Gap이다.

---

*본 문서는 저장소 코드만을 근거로 작성. 문서 철학·제품 정의·신규 아키텍처 제안 없음.*
