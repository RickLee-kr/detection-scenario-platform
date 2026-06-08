# ADR 0004: Prohibition of stdout/grep Validation

**Status:** Accepted  
**Date:** 2026-06-05  
**Phase:** 0.1

---

## Context

레거시 PoC는 webshell remote execution, parallel workers, Bash pipeline 특성상 **stdout을 primary observability**로 사용했다. 구조화 marker (`DNS_TUNNEL_EXECUTION_SUMMARY`, `SSH_BURST_ATTEMPT`)를 grep하여 attempted/success 카운트.

후기 Event SOT 도입 후에도 `stage_result`, `write_report_entries`, overlap env가 stdout/grep 경로를 유지하여 dual judgment 지속.

`event_reject_stdout_only_success` 테스트가 추가되었으나 — **금지가 코드 곳곳에 강제되지 않음**.

---

## Problem

stdout/grep 기반 validation의 실패 모드:

| Failure | Example |
|---------|---------|
| False success | stdout `sent=200`, events=0 |
| Tool variance | dig vs nslookup output format |
| Race | overlap worker timeout → zero env, stdout partial |
| Plan vs execute | `planned=69906` in summary line, attempted=0 |
| Test divergence | test mocks stdout, prod uses events |
| Report pollution | customer report reads cycle log, not SOT |

grep는 **텍스트 가정**에 의존 — locale, buffering, truncated output, nested shell이 깨뜨린다.

---

## Alternatives Considered

### A. stdout primary, events secondary (legacy)

- 거부: 이미 프로덕션 모순 발생

### B. stdout + events reconciliation layer

- 장점: transitional
- 단점: reconciliation 규칙이 제3의 진실원 — 복잡도만 증가

### C. events primary, stdout debug-only

- 장점: single path, grep 제거
- 단점: executor discipline 필요

### D. Binary telemetry (pcap, eBPF)

- 장점: ground truth
- 단점: lab PoC 범위 초과, Phase 4+ optional evidence

---

## Decision

**stdout, grep, log parsing으로 validation·reporting·success 판정을 하지 않는다.**

### Forbidden as validation/reporting inputs

| Source | Status |
|--------|--------|
| Executor stdout markers | Debug only |
| `grep -c SUCCESS` on log files | **Forbidden** |
| `stage_results.log` | **Forbidden** |
| overlap `*_result.env` | **Forbidden** |
| Synthetic detection score | **Forbidden** |
| Planned / Attempted counter (non-event) | **Forbidden** |
| Test-only validation function | **Forbidden** |
| Report-only counter | **Forbidden** |

### Runtime Path Equality Rule

```
Execution Path = Validation Path = Reporting Path
```

Scenario가 Event Store에 기록한 event만:

- Validation 가능
- Reporting 가능
- Exit code 결정 가능

테스트는 production `ValidationEngine.validate()` + 동일 `EventStore`만 사용.

---

## Consequences

### Positive

- `stellar_poc_20260605` class 모순 재발 방지
- CI가 live와 동일 함수 호출 — "테스트만 통과" 제거
- 50 시나리오에서도 grep 규칙 50개 유지 불필요

### Negative

- Operator가 터미널에서 즉시 보는 피드백 감소 → structured progress log + `dsp report`로 보완
- Remote webshell executor는 event sync 필수 (Phase 2)

### Neutral

- Debug log에 stdout tee 허용 — SOT 아님을 명시 라벨
- ADR 0002 Event Store와 쌍으로 적용

---

## References

- [SKILL_SPEC.md](../../SKILL_SPEC.md) — §4 Runtime Path Equality, P3, P11, P12
- [ADR 0002](./0002-event-store-as-sot.md)
- Legacy: `event_reject_stdout_only_success`, `stellar_poc_20260605_131933_report.md`
