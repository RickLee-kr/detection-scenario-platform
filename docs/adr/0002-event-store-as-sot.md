# ADR 0002: Event Store as Single Source of Truth

**Status:** Accepted  
**Date:** 2026-06-05  
**Phase:** 0.1

---

## Context

레거시 PoC는 `stellar_poc_event_sot.sh` v1.2.0에서 Event TSV를 SOT로 선언했으나, 실제 운영에서는 다음이 공존했다.

- `state/events/*.tsv` (SOT 의도)
- `stage_results.log` / stdout markers
- overlap `*_result.env`
- synthetic detection scores
- customer report narrative (cycle log)

`stellar_poc_20260605_131933_report.md`에서 동일 run에 대해 stage Success vs SOT Failed가 동시 기록되었다.

---

## Problem

**판정 데이터 소스가 여러 개**이면 다음이 불가피하다.

1. 테스트 PASS + live FAIL (다른 경로)
2. 리포트 SUCCESS + 실제 이벤트 0건
3. Follow-up validation과 customer report 모순
4. 디버깅 시 "어느 숫자가 맞는가" 논쟁
5. 시나리오 30+ 확장 시 counter/sync 버그 기하급수 증가

stdout·grep·env file은 **관측 편의**이지 **계약(contract)**이 될 수 없다.

---

## Alternatives Considered

### A. stdout structured markers as SOT

- 예: `DNS_TUNNEL_EXECUTION_SUMMARY sent=1500`
- 장점: 구현 간단, human readable
- 단점: 레거시에서 `event_reject_stdout_only_success` 필요 — stdout만으로 success 주장 가능, events=0 버그

### B. Multi-store (TSV + env + log each for purpose)

- 장점: 각 컴포넌트 독립
- 단점: 레거시 overlap env desync, reconciliation 비용

### C. Event Store only (append-only, query for everything)

- 장점: 단일 aggregate path, test=prod
- 단점: 모든 action에 event write discipline 필요

### D. External SIEM as SOT

- 장점: "실제 탐지" 반영
- 단점: 트래픽 생성 여부와 탐지 여부 혼합, lab 환경 의존, Phase 1 blocker

---

## Decision

**Event Store만이 SOT이다.**

```
Execution  → append Event
Validation → query Event Store → aggregate → threshold
Reporting  → query Event Store + ValidationResult
```

| Data | Role |
|------|------|
| Event Store (SQLite) | **SOT** — traffic execution truth |
| ValidationResult | Derived from Event Store (cached per run, reproducible) |
| stdout / debug.log | Telemetry only, never success input |
| Detection Adapter results | Separate appendix, not traffic SOT |

Fail-fast: `sent>0 && event_count=0` → `CODE_FAILURE`

---

## Consequences

### Positive

- Runtime Path Equality 달성 가능
- `dsp validate --run-id X` 재현 — 동일 DB → 동일 판정
- 50 시나리오도 aggregate spec만 추가 (manifest-driven)
- Audit: event 단위 forensic

### Negative

- 모든 executor가 event write 누락 시 silent failure → discipline + fail-fast 필수
- 고볼륨 DNS (15K events/run) 저장 설계 필요 → ADR 0005 SQLite
- Detection confirmation은 별도 adapter (traffic SOT와 분리)

### Neutral

- JSONL export는 audit용 derivative, SOT 아님
- 레거시 TSV import tool은 Phase 2 optional

---

## References

- [EVENT_STORE_SPEC.md](../../EVENT_STORE_SPEC.md)
- [ADR 0004](./0004-no-stdout-validation.md)
- Legacy: `stellar_poc_event_sot.sh`, `tests/test_event_sot_architecture.sh`
