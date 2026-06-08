# ADR 0007: Webshell Execution Provider Architecture

**Status:** Accepted  
**Date:** 2026-06-06  
**Phase:** Architecture (pre-implementation)

---

## Context

DSP Execution Provider Framework (Phase X)는 `LocalExecutionProvider`만 구현한 상태이다. ADR 0006은 Mode A/B dual-model과 provider abstraction을 채택했으나, **WebshellExecutionProvider**의 구체 설계는 남겨두었다.

XDR/NDR PoC 요구사항과 레거시 `stellar_poc.sh`는 webshell bootstrap → remote executor → victim-origin traffic → event retrieval 패턴을 사용한다. 이 패턴을 시나리오 코드에 재유입하면 execution-agnostic 계약이 깨진다.

Webshell provider는 **첫 번째 Mode B 구현체**이며, JSP/PHP/ASPX 등 lab 환경에서 흔한 webshell family를 지원해야 한다.

---

## Problem

Webshell execution을 도입할 때 해결해야 할 architectural questions:

1. **경계:** webshell HTTP transport, remote command dispatch, file upload/download — 어디까지가 provider 책임인가?
2. **Event flow:** remote host에서 생성된 traffic events를 DSP Host Event Store에 어떻게 반영하는가?
3. **Scenario isolation:** `dns_tunnel` 등 기존 9개 시나리오를 수정 없이 webshell에서 실행 가능한가?
4. **Security:** lab-only webshell credential, command allowlist, upload restriction을 어디서 강제하는가?
5. **Validation unchanged:** remote stdout을 성공 판정에 사용하지 않으면서 어떻게 Path Equality를 유지하는가?

---

## Alternatives Considered

### A. Inline webshell logic in each scenario executor.py

- 장점: 시나리오별 fine-grained control
- 단점: 9+ 시나리오 × webshell 분기; execution-agnostic 위반; ADR 0006 거부

### B. Reconstruct events from webshell stdout (Option B sync model)

- 장점: remote stub 단순 (shell script only)
- 단점: fragile parsing; schema drift; ADR 0004 정신 위반; high-volume scenario 실패

### C. Inline structured events in HTTP response (Option A sync model)

- 장점: single round-trip
- 단점: HTTP response size limit; dns_tunnel 등 volume scenario truncate

### D. Remote event bundle download + EventSyncBridge (Option C sync model)

- 장점: legacy stellar_poc pattern formalized; schema validator on import; volume-safe
- 단점: stub + download pipeline 구현 비용

### E. WebshellContract + Family Adapters + WebshellExecutionProvider (Alternative D+E combined)

```
WebshellExecutionProvider
  → WebshellContract (healthcheck, execute, upload, download, cleanup)
  → Family Adapters (JSP, PHP, ASPX, Generic)
  → RemoteExecutorStub (victim-side bundle)
  → EventSyncBridge (Option C primary)
  → ctx.event_store.append() — same schema
```

- 장점: transport/protocol/scenario 완전 분리; family 확장 용이; Path Equality 보존
- 단점: 5-layer 구현; family별 response parsing matrix

---

## Decision

**Alternative E 채택** — WebshellContract + Family Adapters + Option C Event Sync.

### Core decisions

1. **Webshell execution은 Execution Provider 책임이다.** HTTP transport, authentication, upload/download, remote stub staging, event sync — 모두 `WebshellExecutionProvider` 및 하위 adapter에 격리.

2. **시나리오는 execution-agnostic을 유지한다.** 시나리오는 protocol logic과 Event schema만 담당. local vs webshell 분기 금지. Provider가 remote에 executor bundle을 전송하고 동일 executor logic을 원격 실행.

3. **Event Store ownership은 DSP Host에 유지한다.** Remote executor는 victim-side JSONL buffer에 기록. `EventSyncBridge`가 bundle을 download·schema validate·`ctx.event_store.append()`. Event Store API·schema 변경 없음 (ADR 0002).

4. **Validation은 local Event Store만 읽는다.** Webshell stdout/stderr는 transport diagnostic. Validation Engine·threshold·fail-fast 규칙 변경 없음 (ADR 0004).

5. **Event sync primary model = Option C (bundle download).** Option A는 meta/lifecycle events 보조용만. Option B 거부.

6. **WebshellContract는 family-agnostic interface.** JSP/PHP/ASPX/Generic adapter가 `healthcheck`, `execute`, `upload`, `download`, `cleanup`, `capture_stdout`, `capture_stderr` 구현.

7. **Security Envelope는 provider layer에서 강제.** Command allowlist, upload path restriction, credential redaction, lab-only opt-in.

8. **LocalExecutionProvider remains default.** `--execution-provider webshell` explicit selection required.

---

## Consequences

### Positive

- Mode B 첫 구현체 — XDR PoC victim-origin traffic 공식 지원
- 레거시 stellar_poc webshell 패턴을 provider로 격리 — bash monolith 재발 방지
- 9개 기존 시나리오 수정 없이 webshell 실행 가능 (capability matrix permitting)
- Path Equality 유지 — remote run → local Event Store → validate → report
- JSP/PHP/ASPX family adapter로 lab diversity 수용

### Negative

- Family adapter maintenance — response parsing edge cases
- Event sync failure handling — partial sync policy 운영 복잡도
- UDP/raw socket scenarios (dns_tunnel) — victim capability dependency
- Security review 필수 — webshell credential, command injection surface

### Neutral

- `ExecutionContext` extensions defined — runtime models updated in Phase X+1A
- Reporting may include optional `execution_provider_id`, `traffic_origin_host` in run header — validation 무관
- Factory `create_execution_provider("webshell")` — Phase X+1D에서 활성화

---

## References

- [WEBSHELL_PROVIDER_ARCHITECTURE.md](../architecture/WEBSHELL_PROVIDER_ARCHITECTURE.md)
- [WEBSHELL_PROVIDER_RISK_ANALYSIS.md](../architecture/WEBSHELL_PROVIDER_RISK_ANALYSIS.md)
- [WEBSHELL_PROVIDER_IMPLEMENTATION_PLAN.md](../architecture/WEBSHELL_PROVIDER_IMPLEMENTATION_PLAN.md)
- [EXECUTION_PROVIDER_FRAMEWORK.md](../architecture/EXECUTION_PROVIDER_FRAMEWORK.md)
- [ADR 0002 — Event Store as SOT](./0002-event-store-as-sot.md)
- [ADR 0004 — No stdout Validation](./0004-no-stdout-validation.md)
- [ADR 0006 — Execution Provider Architecture](./0006-execution-provider-architecture.md)
- Legacy: `stellar_poc.sh` webshell invoke, remote blob fetch patterns
