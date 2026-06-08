# Execution Provider Framework

**문서 버전:** 1.0.0  
**상태:** Implemented (Phase 1 — framework only)  
**Date:** 2026-06-06

---

## 1. Purpose

Execution Provider Framework는 **트래픽 생성 위치**를 추상화하는 DSP의 실행 계층이다. 시나리오 코드는 execution-agnostic을 유지하고, 실행 위치(local / webshell / ssh / agent)는 Provider가 결정한다.

본 Phase에서는 **프레임워크와 LocalExecutionProvider만** 구현한다. 원격 실행 Provider는 미구현이다.

---

## 2. Architecture

```
RunManager
  → create_execution_provider("local")
  → ExecutionProvider.prepare(ExecutionContext)
  → for each scenario:
        ExecutionProvider.execute(context, record, RunContext, TargetSet)
            → run_scenario (orchestrator)
                → Scenario.prepare()
                → Scenario.execute()
                → Scenario.summarize()
  → ExecutionProvider.cleanup(ExecutionContext)
  → ValidationEngine (unchanged)
  → ReportingEngine (unchanged)
```

**Path Equality 유지:**

```
Execution Path = Validation Path = Reporting Path
```

모든 판정은 Event Store 집계만 사용한다.

---

## 3. Provider Lifecycle

| Phase | Method | Responsibility |
|-------|--------|----------------|
| Run start | `prepare(context)` | Transport/session 준비, execution metadata 초기화 |
| Per scenario | `execute(context, record, ctx, targets)` | 시나리오 lifecycle 위임 (prepare → execute → summarize) |
| Run end | `cleanup(context)` | 세션 종료, 리소스 해제 |

LocalExecutionProvider는 `prepare`/`cleanup`이 no-op에 가깝고, `execute`가 기존 `run_scenario` orchestrator를 호출한다.

---

## 4. Provider Responsibilities

Execution Provider **OWN**:

| Responsibility | Detail |
|----------------|--------|
| Execution mode | Mode A (local) vs Mode B (remote) |
| Transport | In-process socket, SSH, webshell, agent channel |
| Event delivery | Traffic events가 `ctx.event_store`에 기록되도록 보장 |
| Capability matrix | `capabilities()` — UDP/TCP/HTTP 지원 여부 |
| Execution metadata | `ExecutionContext.execution_metadata` |

Execution Provider **MUST NOT**:

| Forbidden | Reason |
|-----------|--------|
| Validation decision 반환 | Validation Engine only |
| Scenario-specific protocol logic | Scenario plugin owns protocol |
| Event schema 변경 | Path equality |
| stdout/grep 기반 성공 판정 | ADR 0004 |

---

## 5. Scenario Responsibilities

시나리오는 **변경 없이** execution-agnostic 계약을 유지한다:

| Scenario OWN | Execution-agnostic? |
|--------------|---------------------|
| `prepare()` / `execute()` / `summarize()` | Yes |
| Protocol logic (DNS, HTTP, SSH, …) | Yes — **what** to send |
| Event schema (`query_sent`, `auth_attempted`, …) | Yes |
| manifest validation thresholds | Yes |

시나리오 **MUST NOT** 알아야 하는 것:

- local / webshell / ssh / agent
- Remote transport setup
- Event sync bridge

---

## 6. Event Store Responsibilities

Event Store는 **변경 없이** authoritative SOT로 유지된다:

| Responsibility | Change |
|----------------|--------|
| append / query / aggregate API | None |
| Event schema | None |
| Validation input | Event Store only |
| Reporting input | ValidationResult + Event Store |

원격 실행 시에도 remote events는 sync 후 **동일 schema**로 local store에 append된다 (future).

---

## 7. Package Structure

```
dsp/execution/
├── __init__.py
├── base.py              # ExecutionProvider ABC
├── factory.py           # create_execution_provider()
├── models.py            # ExecutionContext, ProviderCapabilities
├── local_provider.py    # LocalExecutionProvider
└── exceptions.py        # UnsupportedExecutionProviderError
```

---

## 8. ExecutionContext Model

```python
@dataclass
class ExecutionContext:
    run_id: str
    target_net: str
    dry_run: bool
    provider_type: str
    provider_config: dict[str, Any]
    scenario_id: str | None
    execution_metadata: dict[str, Any]
```

Future-compatible fields (via `provider_config` / `execution_metadata`):

| Field | Provider | Status |
|-------|----------|--------|
| `webshell_url` | webshell | Not implemented |
| `agent_id` | agent | Not implemented |
| `ssh_target` | ssh | Not implemented |

---

## 9. Factory

```python
from dsp.execution import create_execution_provider

provider = create_execution_provider("local")  # only supported provider
```

| Provider | Status |
|----------|--------|
| `local` | Implemented |
| `webshell` | `NotImplementedError` |
| `ssh` | `NotImplementedError` |
| `agent` | `NotImplementedError` |
| unknown | `UnsupportedExecutionProviderError` |

---

## 10. Future Provider Roadmap

| Phase | Provider | Mode | Transport |
|-------|----------|------|-----------|
| **Current** | `LocalExecutionProvider` | A | In-process |
| Next | `WebshellExecutionProvider` | B | HTTP webshell |
| Next | `AgentExecutionProvider` | B | Agent protocol |
| Next | `SSHExecutionProvider` | B | SSH remote command |

각 Provider 추가 시:

1. `ExecutionProvider` 구현체 추가
2. Factory registry 등록
3. Event sync bridge (remote → local Event Store)
4. Path equality 테스트 — artifact / validation / report parity

---

## 11. Related Documents

- [EXECUTION_MODEL_SPEC.md](./EXECUTION_MODEL_SPEC.md)
- [EXECUTION_PROVIDER_DECISION_RECORD.md](./EXECUTION_PROVIDER_DECISION_RECORD.md)
- [EXECUTION_PROVIDER_SPEC.md](../../EXECUTION_PROVIDER_SPEC.md)
- [WEBSHELL_PROVIDER_ARCHITECTURE.md](./WEBSHELL_PROVIDER_ARCHITECTURE.md)
- [WEBSHELL_PROVIDER_RISK_ANALYSIS.md](./WEBSHELL_PROVIDER_RISK_ANALYSIS.md)
- [WEBSHELL_PROVIDER_IMPLEMENTATION_PLAN.md](./WEBSHELL_PROVIDER_IMPLEMENTATION_PLAN.md)
- [ADR 0006 — Execution Provider Architecture](../adr/0006-execution-provider-architecture.md)
- [ADR 0007 — Webshell Execution Provider Architecture](../adr/0007-webshell-execution-provider-architecture.md)
