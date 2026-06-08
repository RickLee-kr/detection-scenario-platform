# ADR 0006: Execution Provider Architecture

**Status:** Accepted  
**Date:** 2026-06-06  
**Phase:** Architecture (pre-implementation)

---

## Context

DSP Phase 1–5는 **Execution Mode A (Local Execution)** 만으로 운영되었다:

```
DSP Host → Traffic Generation → Event Store → Validation → Reporting
```

원래 XDR/NDR PoC 요구사항에는 **Execution Mode B (Remote Execution)** 가 포함되어 있었다:

```
DSP Host → Remote Execution Layer → Webshell/Agent → Traffic on Remote Host → Event Store → Validation
```

레거시 `stellar_poc.sh`는 webshell bootstrap, remote executor copy, victim-origin traffic 패턴을 bash include로 혼재 구현했다. DSP는 시나리오 플러그인·Event Store SOT·Path Equality 원칙으로 재설계되었으나, **실행 위치 추상화**는 아직 공식 아키텍처에 정의되지 않았다.

`ARCHITECTURE_SPEC.md` §9.2에 "Remote Executor Adapter"가 언급되어 있으나, Target Provider·Detection Adapter와 대등한 **Execution Provider** 계층으로 formalize되지 않았다.

---

## Problem

실행 위치를 시나리오 코드에 두면:

1. `dns_tunnel` × (local, webshell, agent, SSH) = N×4 분기 지옥
2. 신규 transport 추가 시 30–50 시나리오 전부 수정
3. Local/remote validation path divergence 위험 (stdout, remote log)
4. PoC lab topology(DSP orchestrator ≠ victim) 표현 불가
5. 레거시 webshell 패턴이 시나리오 executor에 재유입

반대로, 실행 위치를 추상화하지 않으면 Mode B 요구사항을 **공식적으로 지원할 수 없다**.

---

## Alternatives Considered

### A. Duplicate scenarios per execution mode

```
scenarios/dns_tunnel/          # local
scenarios/dns_tunnel_remote/   # webshell copy
```

- 장점: 구현 단순
- 단점: validation threshold·protocol logic 이중 유지, ADR 0003 zero-core-change 위반, 50 시나리오 × 4 mode = 200 폴더

### B. Scenario manifest flag `remote_capable: true` + inline remote logic in executor.py

- 장점: 한 폴더
- 단점: executor가 transport + protocol + sync 혼재, execution-agnostic 위반

### C. Runner-level `--executor remote-webshell` with ad-hoc script copy (legacy stellar_poc pattern)

- 장점: 빠른 PoC
- 단점: provider registry 없음, webshell/agent/SSH 각각 Runner 분기, 테스트·확장 불가

### D. Execution Provider layer (formal abstraction)

```
Runner → ExecutionProviderRegistry → LocalExecutionProvider | WebshellExecutionProvider | ...
Scenario.execute() unchanged — provider supplies transport / remote dispatch
Event Store remains local SOT
```

- 장점: Target Provider·Detection Adapter와 동일한 추상화 패턴, 시나리오 무수정 확장, Path Equality 보존
- 단점: Provider framework + event sync bridge 구현 비용

---

## Decision

**Execution Provider Architecture (Alternative D)** 채택.

### Core decisions

1. **실행 위치는 Execution Provider가 결정한다.** Scenario Engine은 선택된 provider를 통해 시나리오 lifecycle을 실행한다.

2. **시나리오 로직은 execution-agnostic 이어야 한다.** `dns_tunnel`은 local/webshell/agent/SSH를 알 필요 없다. Protocol logic(what to send)만 담당.

3. **원격 실행은 Provider 책임이다.** Webshell bootstrap, agent tasking, SSH session, event sync — 모두 provider 구현체에 격리.

4. **Event Store는 DSP Host의 authoritative SOT를 유지한다.** Remote events는 sync/proxy 후 **동일 schema**로 append. Validation·Reporting은 Event Store만 읽는다 (ADR 0002, ADR 0004).

5. **LocalExecutionProvider는 default.** Mode A는 기존 동작과 100% 호환. Mode B는 explicit provider 선택.

### Architecture placement

```
Runner
  ├── TargetProvider      (where to send traffic — endpoints)
  ├── ExecutionProvider   (where traffic originates — host/process)
  └── Scenario Plugins    (what traffic pattern — protocol)
         ↓ events
    Event Store (SOT)
         ↓
    Validation Engine (unchanged)
         ↓
    Reporting Engine (unchanged)
```

---

## Consequences

### Positive

- Mode A/B 공식 dual-model — XDR/NDR PoC 요구사항 아키텍처 충족
- Webshell/agent/SSH를 provider plugin으로 추가 — 시나리오 0건 수정
- Target Provider(대상) vs Execution Provider(출발지) 관심사 분리
- Path Equality 유지 — remote run도 local Event Store → validate → report
- 레거시 webshell bootstrap을 provider로 격리 — bash monolith 재발 방지

### Negative

- Event sync bridge latency·실패 처리 정책 필요 (provider meta event, not validation bypass)
- Remote provider 보안 review (webshell upload, credential handling) — Safety Envelope 확장
- Provider framework 테스트 matrix 증가 (scenario × provider 조합)

### Neutral

- Phase 번호 미할당 — Phase X~X+3로 roadmap에만 기록
- Detection Adapter layer와 직교 — execution location ≠ detection confirmation
- `manifest.executor.remote_capable`은 **hint**만 (provider capability matrix), scenario 분기 아님

---

## References

- [EXECUTION_MODEL_SPEC.md](../architecture/EXECUTION_MODEL_SPEC.md)
- [EXECUTION_PROVIDER_SPEC.md](../../EXECUTION_PROVIDER_SPEC.md)
- [EXECUTION_PROVIDER_DECISION_RECORD.md](../architecture/EXECUTION_PROVIDER_DECISION_RECORD.md)
- [ADR 0002 — Event Store as SOT](./0002-event-store-as-sot.md)
- [ADR 0003 — Scenario Plugin Architecture](./0003-scenario-plugin-architecture.md)
- [ADR 0004 — No stdout Validation](./0004-no-stdout-validation.md)
- [TARGET_PROVIDER_SPEC.md](../../TARGET_PROVIDER_SPEC.md)
- Legacy: `stellar_poc.sh` webshell bootstrap pattern
