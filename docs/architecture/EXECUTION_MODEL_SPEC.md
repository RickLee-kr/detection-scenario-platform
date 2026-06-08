# Detection Scenario Platform — Execution Model Specification

**문서 버전:** 1.0.0  
**상태:** Architecture only — no implementation  
**Phase:** Pre-implementation (Execution Provider Framework)

---

## 1. Purpose

DSP는 트래픽 생성 **위치**를 두 가지 실행 모드로 공식 지원한다. 본 문서는 Execution Model A(로컬)와 Execution Model B(원격)를 정의하고, 시나리오·Event Store·Validation·Reporting이 실행 위치와 무관하게 동작함을 명시한다.

**핵심 설계 규칙:** 시나리오는 execution-agnostic 이어야 한다. `dns_tunnel`은 로컬 실행, webshell, agent, SSH 중 **어디에서 실행되는지 알 필요가 없다**. 실행 위치는 **Execution Provider**가 결정한다.

---

## 2. Execution Model Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DSP Host (Orchestrator)                          │
│  Runner → Scenario Engine → Execution Provider Registry → Validation   │
└─────────────────────────────────────────────────────────────────────────┘
         │                                    │
         │ Mode A                             │ Mode B
         ▼                                    ▼
┌─────────────────────┐              ┌─────────────────────┐
│  Local Execution    │              │  Remote Execution   │
│  (same host as DSP) │              │  Layer              │
└──────────┬──────────┘              └──────────┬──────────┘
           │                                    │
           │                                    ▼
           │                         ┌─────────────────────┐
           │                         │ Webshell / Agent /  │
           │                         │ SSH / Future transport│
           │                         └──────────┬──────────┘
           │                                    │
           └────────────────┬───────────────────┘
                            ▼
                   Traffic Generation
                   (protocol I/O on chosen host)
                            │
                            ▼
                   Event Store (authoritative SOT)
                            │
                            ▼
                   Validation → Reporting
```

---

## 3. Execution Mode A — Local Execution

### 3.1 Definition

**Execution Mode A (Local Execution)** 은 DSP가 실행 중인 호스트에서 직접 트래픽을 생성하는 모델이다.

```
DSP Host
  ↓
Traffic Generation (local process)
  ↓
Event Store
  ↓
Validation
```

### 3.2 Characteristics

| Aspect | Local Execution |
|--------|-----------------|
| Traffic origin | DSP Host |
| Orchestrator | Runner + Scenario Engine |
| Execution Provider | `LocalExecutionProvider` (default) |
| Event append | In-process, direct to Event Store |
| Network egress | From DSP Host NIC |

### 3.3 Use Cases

- Lab validation — 단일 호스트 PoC
- Local testing — 개발·CI dry-run / mocked transport
- Standalone deployments — DSP만 설치된 환경

### 3.4 Current State

Execution Mode A는 **현재 구현·운영 중인 모델**이다. Phase 1–5 시나리오(dns_tunnel, dga, http_followup, ssh_failure 등)는 모두 로컬 실행으로 검증되었다.

---

## 4. Execution Mode B — Remote Execution

### 4.1 Definition

**Execution Mode B (Remote Execution)** 은 DSP Host가 원격 호스트에서 트래픽 생성을 **오케스트레이션**하는 모델이다. 트래픽은 원격 호스트에서 발생한다.

```
DSP Host
  ↓
Remote Execution Layer (Execution Provider)
  ↓
Webshell / Remote Agent / SSH session / Future transport
  ↓
Traffic Generation on Remote Host
  ↓
Event Store (synced or proxied to DSP Host)
  ↓
Validation
```

### 4.2 Characteristics

| Aspect | Remote Execution |
|--------|------------------|
| Traffic origin | Remote host (victim / agent endpoint) |
| Orchestrator | Runner + Scenario Engine + Execution Provider |
| Execution Provider | `WebshellExecutionProvider`, `AgentExecutionProvider`, `SSHExecutionProvider`, … |
| Event append | Remote capture → sync/proxy → **local Event Store** |
| Network egress | From remote host NIC |

### 4.3 Use Cases

- XDR/NDR PoC — compromised host 시뮬레이션
- Endpoint-origin traffic — C2, lateral movement, exfil from victim
- Lab topology — DSP orchestrator와 victim 분리
- Legacy webshell bootstrap 패턴 — adapter로 격리 (ADR-0006)

### 4.4 Current State

Execution Mode B는 **아키텍처로만 정의**된다. 구현은 Phase X 이후 Execution Provider Framework부터 순차 진행한다.

---

## 5. Execution-Agnostic Scenario Contract

### 5.1 What Scenarios Know

| Scenario responsibility | Execution-agnostic? |
|-------------------------|---------------------|
| Protocol logic (DNS, HTTP, SSH, …) | Yes — **what** to send |
| TargetSet consumption | Yes |
| Event schema (event, status, artifact, evidence) | Yes |
| manifest validation thresholds | Yes |
| prepare() / execute() / summarize() lifecycle | Yes |

### 5.2 What Scenarios Must NOT Know

| Forbidden in scenario code | Belongs to |
|----------------------------|------------|
| `if webshell:` / `if remote:` | Execution Provider |
| SSH connection setup to victim | SSHExecutionProvider |
| Webshell upload / bootstrap | WebshellExecutionProvider |
| Agent task dispatch | AgentExecutionProvider |
| Event sync transport | Execution Provider + Event Store bridge |

### 5.3 Example — dns_tunnel

`dns_tunnel` 시나리오는 다음만 수행한다:

1. FQDN 패턴 생성 (idx-pattern)
2. UDP/53 A query 전송 (Execution Provider가 제공한 transport context 사용)
3. `query_sent`, `query_response` 이벤트 기록

실행 위치(local vs remote)는 시나리오 코드에 분기 없이 **Execution Provider**가 transport를 주입한다.

---

## 6. Unchanged Core Components

Execution Mode A/B 도입 시 **변경하지 않는** 코어:

| Component | Role | Change |
|-----------|------|--------|
| Event Store | Single Source of Truth | **None** — schema, append API, query API 동일 |
| Validation Engine | Event Store 집계 → decision | **None** |
| Reporting Engine | ValidationResult + Event Store → report | **None** |
| Scenario contract | prepare / execute / summarize | **None** — execution location 분기 금지 |
| manifest validation block | threshold 선언 | **None** |

**Path Equality 유지:**

```
Execution Path = Validation Path = Reporting Path
```

원격 실행이어도 Validation은 **로컬 Event Store**만 읽는다. stdout, remote log grep, provider callback으로 판정하지 않는다.

---

## 7. Execution Provider Layer (Summary)

상세: [EXECUTION_PROVIDER_SPEC.md](../../EXECUTION_PROVIDER_SPEC.md), [ADR 0006](../adr/0006-execution-provider-architecture.md)

```
Runner
  → selects ExecutionProvider (CLI / config / manifest default)
  → Scenario Engine invokes scenario via provider.execute_scenario(...)
  → provider ensures events land in ctx.event_store
  → Validation / Reporting unchanged
```

| Provider | Mode | Transport |
|----------|------|-----------|
| `LocalExecutionProvider` | A | In-process |
| `WebshellExecutionProvider` | B | HTTP webshell |
| `AgentExecutionProvider` | B | Agent protocol (Caldera, Sliver, …) |
| `SSHExecutionProvider` | B | SSH remote command |

---

## 8. Event Flow — Local vs Remote

### 8.1 Mode A (Local)

```
Scenario.execute(ctx, targets)
  → executor.run(...)  [local sockets]
  → ctx.event_store.append(event)  [direct]
```

### 8.2 Mode B (Remote)

```
Scenario.execute(ctx, targets)   [same scenario code]
  → Execution Provider intercepts I/O OR
  → provider runs scenario bundle on remote host
  → remote events collected
  → provider.sync_events() → ctx.event_store.append(...)  [same schema]
```

**Event schema는 실행 모드와 무관하게 동일.** `evidence`에 optional `execution_host`, `execution_provider_id` 메타데이터 추가 가능 (validation threshold에 사용하지 않음).

---

## 9. CLI / Configuration (Conceptual)

```bash
# Mode A — default (local execution provider)
dsp run --scenarios dns_tunnel,dga

# Mode B — webshell provider (Python API / lab runner; not a dsp run CLI flag in v1.0.2)
python scripts/run_dsp_release_1_0_lab_test.py \
  --mode webshell \
  --webshell-type jsp \
  --webshell-url https://lab-victim.example/shell.jsp \
  --remote-bundle-path /tmp/dsp/<run_id>/events.jsonl \
  --output-dir /path/to/lab-evidence
```

Run metadata에 `execution_mode`, `execution_provider_id`, `traffic_origin_host` 기록 (reporting only, validation 무관).

---

## 10. Future Extensibility

### 10.1 New Execution Transports

새 transport 추가 시:

1. `ExecutionProvider` 구현체 추가 (코어 시나리오 수정 **금지**)
2. Provider registry 등록
3. Event sync bridge가 Event Store schema 준수 확인
4. Path equality 테스트 — remote run → local validate → report

예: gRPC agent, WinRM, Kubernetes exec, container sidecar.

### 10.2 Multi-Origin Runs (Future)

단일 run 내 시나리오별 다른 provider 선택 (advanced):

```yaml
# RunConfig (future)
execution:
  default: local
  overrides:
    dns_tunnel: webshell
    http_followup: local
```

Scenario Engine은 per-scenario provider dispatch만 담당. 시나리오 코드 변경 없음.

### 10.3 Relationship to Detection Adapters

| Layer | Abstracts | Example |
|-------|-----------|---------|
| Execution Provider | **Where** traffic is generated | webshell on 10.10.10.50 |
| Detection Adapter | **Whether** vendor detected it | Stellar NDR alert |
| Scenario | **What** traffic pattern | dns_tunnel idx-pattern |

세 레이어는 직교(orthogonal)한다.

---

## 11. Roadmap Reference (Unnumbered Phases)

| Phase | Deliverable |
|-------|-------------|
| Phase X | Execution Provider Framework (interface, registry, LocalExecutionProvider formalization) |
| Phase X+1 | Webshell Execution Provider |
| Phase X+2 | Agent Execution Provider |
| Phase X+3 | SSH Execution Provider |

Phase 번호는 [PHASE_ROADMAP.md](../../PHASE_ROADMAP.md)에서 기존 시나리오·adapter 일정과 조율 후 할당한다.

---

## 12. Anti-Patterns

| Anti-pattern | Why forbidden |
|--------------|---------------|
| Scenario `if execution_mode == "remote"` | Breaks execution-agnostic contract |
| Remote stdout as validation input | Violates ADR 0004 |
| Separate Event schema for remote | Breaks SOT path equality |
| Validation reads provider health API | Provider failure ≠ traffic failure (별도 meta event) |
| Copy-paste scenario for remote variant | `dns_tunnel_webshell` 금지 — one scenario, many providers |

---

## 13. Related Documents

- [EXECUTION_PROVIDER_SPEC.md](../../EXECUTION_PROVIDER_SPEC.md)
- [EXECUTION_PROVIDER_DECISION_RECORD.md](./EXECUTION_PROVIDER_DECISION_RECORD.md)
- [ADR 0006 — Execution Provider Architecture](../adr/0006-execution-provider-architecture.md)
- [ARCHITECTURE_SPEC.md](../../ARCHITECTURE_SPEC.md)
- [SCENARIO_FRAMEWORK_SPEC.md](../../SCENARIO_FRAMEWORK_SPEC.md)
- [TARGET_PROVIDER_SPEC.md](../../TARGET_PROVIDER_SPEC.md)
- [EVENT_STORE_SPEC.md](../../EVENT_STORE_SPEC.md)
