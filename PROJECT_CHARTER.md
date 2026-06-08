# Detection Scenario Platform — Project Master Charter

**문서 버전:** 0.1.0 (Phase 0 — 설계 전용)  
**상태:** Approved for design; **구현 금지**  
**선행 프로젝트:** xdr-lab-appliance Stellar PoC (Bash) — 참고 자료만  
**Canonical Root:** `detection-scenario-platform/` (workspace 내 별도 디렉터리)

---

## 0. Repository Boundary (Workspace Safety)

본 프로젝트는 `xdr-lab-appliance` workspace에 공존하는 **XDR Lab Deployment Automation**과 분리된다.

| 규칙 | Phase 0 |
|------|---------|
| DSP 산출물 위치 | `detection-scenario-platform/` **만** |
| Deployment automation 수정 | **금지** |
| 레거시 `stellar_poc*.sh` 수정 | **금지** (읽기·분석만) |
| 통합 코드 / import / hook / CI 변경 | **금지** |
| 구현 코드 | **금지** (문서만) |

상세: [WORKSPACE_BOUNDARY.md](./WORKSPACE_BOUNDARY.md)

향후 deployment automation과 통합은 PoC Traffic Generator 완료 **이후** 별도 Phase에서 진행한다. Phase 0 목표는 **통합 가능한 설계 문서** 작성이지, 현재 workspace 자동화를 수정하는 것이 아니다.

---

## 1. Executive Summary

Detection Scenario Platform(DSP)은 XDR, NDR, EDR, SIEM 제품이 탐지할 수 있는 **실제 공격자처럼 보이는** 네트워크 트래픽과 행위 시나리오를 **Safe PoC 범위** 내에서 생성하는 Python 기반 플랫폼이다.

이 프로젝트는 기존 Bash PoC의 **리팩토링이 아니다**. 레거시 코드는 "무엇이 성공했고 무엇이 실패했는가"를 식별하는 참고 자료로만 사용한다.

---

## 2. 목적 (Purpose)

| 목표 | 설명 |
|------|------|
| **탐지 검증** | 권한이 있는 PoC 환경에서 센서/플랫폼이 공격 패턴을 탐지하는지 검증 |
| **재현 가능성** | 동일 시나리오를 반복 실행해도 동일한 이벤트·판정·리포트가 나와야 함 |
| **확장성** | Stellar 외 Microsoft Defender, SentinelOne, Splunk 등으로 확장 가능한 구조 |
| **안전성** | 실제 피해 없이 탐지 가능한 트래픽/행위만 생성 |

### 핵심 철학

> DSP는 Traffic Generator가 아니라 **Detection Scenario Platform**이다.

시나리오(DNS Tunnel, DGA, HTTP Follow-up 등)는 기능이 아니라 **동일한 계약(Contract)을 따르는 Scenario**이다.

---

## 3. 범위 (In Scope)

### 3.1 초기 시나리오 (Phase 1–2)

| 시나리오 | 검증 상태 | 핵심 패턴 |
|----------|-----------|-----------|
| `dns_tunnel` | 레거시 검증 완료 | `idx-{seq:06d}-{b32}.domain`, 실제 UDP/53 Query |
| `dga` | 레거시 검증 완료 | `*.xdr.ooo` NXDOMAIN + `*.live.xdr.ooo` resolvable |
| `http_followup` | 레거시 검증 완료 | 포트 443/8443/80/8080/8000, 고정 URL path 세트 |
| `ssh_failure` | 실행 경험 있음, SOT 미완 | `invaliduser@`, BatchMode, pubkey-only |
| `sql_injection` | 신규 | `?id=1' OR '1'='1`, `UNION SELECT` 등 탐지 가능 요청 |

### 3.2 플랫폼 구성요소

- Runner (CLI 진입점)
- Scenario Engine (시나리오 오케스트레이션)
- Target Engine (대상 선정·범위 검증)
- Event Store (Single Source of Truth)
- Validation Engine (Event Store 기반 판정)
- Reporting Engine (Event Store 기반 리포트)
- Plugin Loader (시나리오 자동 등록)

### 3.3 Safe PoC 제약 (필수)

| 금지 | 허용 |
|------|------|
| 악성코드 배포·실행 | 탐지 시그니처를 유발하는 **비실행** 파일 생성 (EICAR 등, 별도 시나리오) |
| 권한 상승 | 실패한 인증 시도 (SSH invalid user) |
| 데이터 탈취 | 제한된 lab subnet 내 트래픽 |
| 실제 피해 유발 | UDP/53 DNS query, HTTP GET/HEAD, SQLi **패턴** 요청 |

추가 안전 장치:

- `--target-net CIDR` 범위 밖 대상 차단
- lab 전용 도메인 (`xdr.ooo`, `dns-tunnel.com` 등)
- 시나리오별 볼륨 상한 (HTTP ≤20 req, DGA 500+30 등)
- 실행 시간 예산 (hard timeout)

---

## 4. 비범위 (Out of Scope)

### 4.1 명시적 제외

| 항목 | 이유 |
|------|------|
| 기존 Bash 코드 리팩토링 | 구조적 한계, 이중 판정 경로 |
| Legacy 호환 | 신규 프로젝트, API/이벤트 구조 전면 재설계 |
| ICMP Tunnel | 레거시에서 지속적 실패 (`packets_sent=0`, `sot_file_missing`) |
| DNS Visibility Gate | dig/nslookup 기반 preflight가 false negative 유발 |
| Resolver Validation (dig/nslookup) | Python raw UDP로 대체됨, parsing fragility |
| Synthetic Detection Score | 센서 이벤트와 무관한 0–100 점수 |
| Entropy-only DGA | 검증된 2-phase `xdr.ooo` 모델과 불일치 |
| Overlap Stage Architecture | `*_result.env` 이중 상태로 SOT와 desync |
| Planned vs Attempted Counter Tier | `planned=69906, attempted=0` 반복 불일치 |

### 4.2 Phase 0에서 제외

- 런타임 코드 구현
- 레거시 Bash 스크립트 수정
- 프로덕션 배포 파이프라인
- 센서 측 탐지 확인 자동화 (향후 Detection Model Adapter 영역)

---

## 5. 레거시 분석 — Keep vs Remove

### 5.1 Keep (검증된 패턴)

**Event SOT 원칙** (`stellar_poc_event_sot.sh` v1.2.0에서 학습)

- Summary / Validation / Final Decision이 **동일 Event Store**만 참조해야 함
- stdout-only 성공 거부 (`event_reject_stdout_only_success`)
- `sent > 0 && event_count == 0` → `CODE_FAILURE` fail-fast

**Python Protocol Clients** (레거시에서 가장 안정적)

- `stellar_dns_tunnel_file_client.py`: raw UDP/53, `strt/idx/end` FQDN, TSV 이벤트
- `stellar_dga_model_client.py`: 2-phase NX + resolvable, `xdr.ooo` base domain

**시나리오별 검증 기준** (Event Store 집계 기반)

- DNS Tunnel: `event_count > 0` (query sent)
- HTTP: `attempted > 0 && responses > 0`
- DGA: `base_domain=xdr.ooo`, `nx >= 300 && resolvable >= 10`

**Safe 실행 패턴**

- SSH: `invaliduser`, `BatchMode=yes`, `PasswordAuthentication=no`
- HTTP: max 2 hosts, 10 URLs/host, ≤20 requests
- Fast-safe: stage budget, fail-fast (reachable target 없으면 skip)

### 5.2 Remove (실패 원인)

**경로 분기 — 가장 치명적 실패**

`stellar_poc_20260605_131933_report.md` 사례:

| 판정 경로 | DNS Tunnel 결과 |
|-----------|-----------------|
| stage_result (stdout/grep) | Success |
| Event SOT | FAILED — `event_count=0` |
| Follow-up Validation | FAILED — all modules zero |
| Customer report narrative | Success (모순) |

원인: 실행·검증·리포트가 **서로 다른 데이터 소스**를 참조.

**폐기 대상 상세**

| 패턴 | 실패 증거 |
|------|-----------|
| dig/nslookup stdout parsing | `DNS_SERVER_VALIDATION_PARSE_ERROR`, tool missing |
| DNS Visibility Gate | execution 성공해도 `DNS_ENVIRONMENT_BLOCKED=true` |
| Synthetic scores | `detection_likelihood: low` 반복, 센서 무관 |
| Planned counters | `COUNTER_CONSISTENCY_BUG`, `attempted=0` vs `planned=69906` |
| Overlap env files | worker timeout 시 degraded zero counters |
| Entropy DGA path | SOT는 phase model, entropy는 legacy only |

---

## 6. 설계 원칙 (Design Principles)

### P1 — Unified Path (최우선)

```
Execution Path = Validation Path = Reporting Path
```

모든 성공/실패 판정은 **Event Store 조회**로만 이루어진다.

### P2 — Event Store as SOT

- stdout는 SOT가 아니다
- grep는 SOT가 아니다
- overlap `*.env`는 SOT가 아니다
- stage_result log는 SOT가 아니다

### P3 — Scenario as Plugin

신규 시나리오 추가 = `scenarios/<name>/` 폴더 추가. 코어 수정 최소화.

### P4 — Traffic vs Detection 분리

- **Traffic Generator** (시나리오 executor): 패킷/요청 생성
- **Detection Model Adapter** (향후): Stellar, Defender, Splunk 등 탐지 확인

### P5 — Executor는 성공을 선언하지 않는다

`execute()`는 이벤트를 기록할 뿐. `validate()`가 Event Store를 조회해 판정.

### P6 — 단일 Counter Tier

허용: `sent`, `event_count`, 시나리오별 outcome (`nxdomain`, `response` 등)  
금지: `planned`를 validation input으로 사용

### P7 — Preflight ≠ Scenario Validation

연결성/대상 존재 확인은 skip 결정용. 시나리오 성공 판정에 사용 금지.

### P8 — Typed Python First

Bash+dig/nslookup 대신 typed Python executor. 구조화된 이벤트 emit.

### P9 — Append-Only Events

이벤트는 삭제·수정하지 않고 append. run_id로 격리.

### P10 — Fail-Fast Invariants

논리적 불가능 상태 즉시 `CODE_FAILURE`:

- stage executed + event_count=0
- sent>0 + unique_fqdn=0
- stdout claims success + event_count=0

---

## 7. 성공 기준 (Success Criteria)

### 7.1 Phase 1 (MVP) 완료 기준

- [ ] 5개 초기 시나리오가 동일 lifecycle (`prepare → execute → validate → summarize`) 준수
- [ ] 단일 Event Store에서 summary/validation/report 생성
- [ ] 레거시 대비 동등 이상의 DNS/DGA/HTTP 트래픽 생성
- [ ] 테스트가 production executor와 **동일 validation 함수** 사용
- [ ] stdout-only success 시나리오가 CI에서 반드시 FAIL

### 7.2 Phase 2 (확장) 완료 기준

- [ ] `scenarios/<new>/` 폴더만으로 신규 시나리오 등록
- [ ] Detection Model Adapter 인터페이스 정의 및 Stellar adapter 1종
- [ ] SSH Failure, SQL Injection 시나리오 SOT 완비

### 7.3 3년 확장 기준

- [ ] 10+ 시나리오, 5+ detection vendor adapter
- [ ] 시나리오 메타데이터 버전 관리
- [ ] run artifact 재현 (동일 run_id → 동일 report)

---

## 8. 아키텍처 철학

### 8.1 레이어 모델

```
┌─────────────────────────────────────────────────────────┐
│  CLI / Runner                                           │
├─────────────────────────────────────────────────────────┤
│  Scenario Engine  │  Target Engine  │  Plugin Loader  │
├─────────────────────────────────────────────────────────┤
│  Scenario Plugins (dns_tunnel, dga, http_followup, …)     │
├─────────────────────────────────────────────────────────┤
│  Event Store (SOT)                                      │
├─────────────────────────────────────────────────────────┤
│  Validation Engine  │  Reporting Engine                 │
├─────────────────────────────────────────────────────────┤
│  Detection Model Adapters (future, optional)            │
└─────────────────────────────────────────────────────────┘
```

### 8.2 레거시와의 관계

| 레거시 | DSP 대응 |
|--------|----------|
| `stellar_poc.sh` (4600+ lines) | `dsp run` (thin orchestrator) |
| `stellar_poc_event_sot.sh` | `ValidationEngine` + `EventStore` |
| `stellar_dns_tunnel_file_client.py` | `scenarios/dns_tunnel/executor.py` |
| `stellar_dga_model_client.py` | `scenarios/dga/executor.py` |
| `*_result.env` overlap | 폐기 |
| `stage_result` log | 디버그 telemetry only |

### 8.3 프로젝트 디렉터리 (Canonical Root, Phase 1+)

모든 구현은 workspace root의 **`detection-scenario-platform/`** 에만 추가한다.  
`appliance/`, `bootstrap/`, `scripts/` 등 deployment automation 경로는 **건드리지 않는다**.

```
detection-scenario-platform/   ← CANONICAL (workspace 내 격리)
├── README.md
├── WORKSPACE_BOUNDARY.md
├── PROJECT_CHARTER.md         # … Phase 0 docs
├── dsp/                         # Phase 1+ 코어 패키지
│   ├── runner/
│   ├── engine/
│   ├── event_store/
│   ├── validation/
│   ├── reporting/
│   └── plugins/
├── scenarios/              # 시나리오 플러그인
│   ├── dns_tunnel/
│   ├── dga/
│   ├── http_followup/
│   ├── ssh_failure/
│   └── sql_injection/
├── adapters/               # Detection Model (향후)
│   └── stellar/
└── tests/
```

---

## 9. 이해관계자 및 용도

| 역할 | 사용 |
|------|------|
| PoC 운영자 | `dsp run --scenarios dns_tunnel,dga` |
| 센서 엔지니어 | 리포트에서 event_count, 패턴 메트릭 확인 |
| 시나리오 개발자 | `scenarios/<name>/` 플러그인 추가 |
| Cursor Agent | `SKILL_SPEC.md` 준수하여 구현 |

---

## 10. 리스크 및 완화

| 리스크 | 완화 |
|--------|------|
| 레거시 패턴 재유입 (stdout 판정) | SKILL_SPEC 금지사항 + CI gate |
| Event Store 성능 | SQLite WAL + 인덱스; 대량 시나리오는 JSONL shard |
| 원격 실행 (webshell) | Phase 1은 local executor; remote는 Phase 2 adapter |
| 범위 밖 트래픽 | Target Engine CIDR enforcement |

---

## 11. 관련 문서

| 문서 | 내용 |
|------|------|
| [ARCHITECTURE_SPEC.md](./ARCHITECTURE_SPEC.md) | 컴포넌트·데이터 흐름 |
| [SCENARIO_FRAMEWORK_SPEC.md](./SCENARIO_FRAMEWORK_SPEC.md) | 시나리오 인터페이스·플러그인 |
| [EVENT_STORE_SPEC.md](./EVENT_STORE_SPEC.md) | SOT 스키마·저장소 선택 |
| [SKILL_SPEC.md](./SKILL_SPEC.md) | Cursor 구현 규칙 |

---

## 12. 승인 및 다음 단계

**Phase 0 (현재):** 본 Charter 및 Spec 문서 작성 — **완료 목표**  
**Phase 1:** 코어 패키지 골격 + Event Store + DNS Tunnel 시나리오 1종  
**Phase 2:** DGA, HTTP, Validation/Reporting 통합 + CI  
**Phase 3:** SSH, SQLi + Detection Adapter

> **절대 규칙:** Phase 0에서는 코드를 작성하지 않는다.
