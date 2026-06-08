# ADR 0003: Scenario Plugin Architecture

**Status:** Accepted  
**Date:** 2026-06-05  
**Phase:** 0.1

---

## Context

레거시 PoC는 DNS, DGA, HTTP, SSH, ICMP 등이 `stellar_poc.sh` 및 include 파일에 **기능(function) 단위**로 누적되었다. enhanced/fallback dual path, overlap stage, module string 혼용(`DNS_TUNNEL_ENH_*`, `DGA_SIMULATION`)이 발생했다.

DSP 목표: **30–50+ Detection Scenario**를 3년간 추가해도 코어 아키텍처 변경 없이 운영.

---

## Problem

Monolith function-per-feature 모델의 한계:

1. 신규 시나리오 = core script 수정 → regression 위험
2. 시나리오 간 stage/counter/env 충돌
3. validation threshold가 awk case문에 하드코딩
4. 팀 병렬 개발 불가 (동일 파일 lock)
5. 시나리오 disable/enable이 조건문 숲

---

## Alternatives Considered

### A. Monolith Python package (all scenarios in `dsp/scenarios/*.py`)

- 장점: 단일 import tree
- 단점: 50 파일이 한 패키지에 있어도 registry 수동 유지, manifest 메타데이터 분리 어려움

### B. Config-only scenarios (YAML lists URLs/domains, generic executor)

- 장점: 코드 없이 시나리오 추가
- 단점: DNS tunnel idx-pattern, DGA 2-phase 등 **프로토콜 특화 로직** 표현 불가

### C. Folder-based plugins (`scenarios/<id>/` + manifest.yaml + auto-discovery)

- 장점: 격리, 병렬 개발, metadata-driven validation, zero-core-change 등록
- 단점: Plugin Loader 품질이 중요, 잘못된 manifest 런타임 발견

### D. External pip packages per scenario

- 장점: 완전 독립 배포
- 단점: PoC lab 오버헤드, 50개 패키지 운영 부담 — Phase 4+ optional

---

## Decision

**Folder-based Scenario Plugin Architecture** 채택.

```
scenarios/<scenario_id>/
├── manifest.yaml    # id, validation, safety, defaults
├── scenario.py      # class XxxScenario(Scenario)
└── executor.py      # protocol I/O
```

**등록:** Plugin Loader가 `scenarios/` scan → manifest 검증 → import `scenario.py`

**계약:** 모든 시나리오 동일 lifecycle — `prepare()` → `execute()` → (Validation Engine) → `summarize()`

**코어 변경 없이 추가 가능 조건:**

- Validation threshold는 `manifest.validation`에 선언
- Metric aggregate는 generic `AggregateSpec`
- 새 metric/filter는 manifest만 확장 (Engine generic)

**30–50 시나리오 한도 설계:**

| Mechanism | Limit handling |
|-----------|----------------|
| Plugin Loader | O(n) scan at startup, registry dict — n=50 trivial |
| Event Store | `scenario` indexed column |
| Validation Engine | manifest-driven, no per-scenario if/else |
| Detection Catalog | metadata only, not code ([DETECTION_CATALOG.md](../../DETECTION_CATALOG.md)) |

---

## Consequences

### Positive

- 시나리오 팀이 `scenarios/brute_force_ssh/` 폴더만 PR
- disable = 폴더 제거 또는 manifest `enabled: false`
- Composite scenario (Phase 3) = manifest `type: composite` without engine fork
- Cursor Agent 실수 범위를 한 폴더로 제한

### Negative

- manifest schema evolution 시 Loader validation 강화 필요
- 잘못된 plugin이 전체 run을 망가뜨릴 수 있음 → preflight manifest lint
- shared protocol utils (DNS encode) 중복 위험 → `dsp/protocols/` shared lib (코어, 시나리오 아님)

### Neutral

- Detection Model mapping은 scenario plugin 밖 ([ARCHITECTURE_SPEC.md](../../ARCHITECTURE_SPEC.md) §16)
- Composite/orchestrated campaign은 Scenario Engine policy, not new ADR

---

## References

- [SCENARIO_FRAMEWORK_SPEC.md](../../SCENARIO_FRAMEWORK_SPEC.md)
- [DETECTION_CATALOG.md](../../DETECTION_CATALOG.md)
- Legacy anti-pattern: `DNS_TUNNEL_ENH_*`, overlap stages
