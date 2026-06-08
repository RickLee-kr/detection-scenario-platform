# ADR 0001: Python over Bash for DSP

**Status:** Accepted  
**Date:** 2026-06-05  
**Phase:** 0.1

---

## Context

xdr-lab-appliance 레거시 PoC는 수개월간 Bash(`stellar_poc.sh` 4600+ lines, 10+ include scripts)로 성장했다. DNS Tunnel·DGA 시나리오는 후기에 Python 클라이언트(`stellar_dns_tunnel_file_client.py`, `stellar_dga_model_client.py`)로 부분 전환되었으나, orchestration·validation·reporting은 여전히 Bash+awk+grep에 의존한다.

DSP는 greenfield 프로젝트이며 workspace 내 deployment automation과 분리된 `detection-scenario-platform/`에서 시작한다.

---

## Problem

Bash 기반 PoC는 다음 구조적 한계에 도달했다.

1. **실행 경로 분기** — Python executor는 이벤트를 기록하지만 Bash stage_result는 stdout/grep으로 별도 판정
2. **프로토콜 취약성** — dig/nslookup/host stdout parsing, tool missing, parse error
3. **확장 비용** — 시나리오 추가마다 4000-line monolith 수정, 함수명·stage overlap 충돌
4. **테스트 불일치** — 테스트 fixture 경로와 live run 경로가 다른 validation 함수 사용
5. **타입·스키마 부재** — TSV+awk summary, counter tier 4단계(planned/attempted/executed/successful) 불일치

기능 구현 실패가 아니라 **아키텍처 실패**가 반복 실패의 원인이었다.

---

## Alternatives Considered

### A. Bash 리팩토링 (기존 stellar_poc 구조 유지)

- 장점: 기존 운영자 친숙, webshell remote 패턴 재사용
- 단점: dual-path 버그 근본 해결 불가, 30+ 시나리오 시 monolith 비관리 가능

### B. Bash orchestration + Python executors (현재 레거시 하이브리드 유지)

- 장점: 점진적 전환
- 단점: 이미 실패한 패턴 — Bash가 validation/reporting 소유 시 Python events와 desync

### C. Go/Rust 단일 바이너리

- 장점: 배포 단순, 성능
- 단점: PoC lab 환경에 Python3 이미 보급, 프로토콜 프로토타이핑 속도 낮음, 팀 학습 비용

### D. Python 전면 (orchestration + executor + validation + reporting)

- 장점: typed models, SQLite, pytest same-path, plugin import
- 단점: remote webshell bootstrap은 Phase 2 adapter로 별도 설계 필요

---

## Decision

**DSP 코어 전체를 Python으로 구현한다.** Bash orchestration은 사용하지 않는다.

| Layer | Language |
|-------|----------|
| Runner, Engine, Validation, Reporting | Python |
| Scenario executors (DNS, HTTP, SSH, …) | Python |
| Event Store access | Python (sqlite3 stdlib) |
| Tests | pytest |

레거시 Bash PoC는 **read-only 참고**만. 함수명·stage 구조·TSV 포맷 복사 금지.

레거시에서 이식하는 것은 **검증된 프로토콜 패턴**뿐 (idx FQDN, DGA 2-phase, raw UDP/53).

---

## Consequences

### Positive

- Execution = Validation = Reporting 단일 코드베이스에서 강제 가능
- 30–50 시나리오를 plugin folder로 추가, 코어 수정 없음
- structlog/typed Event model로 schema evolution 관리
- CI에서 in-memory SQLite + 동일 ValidationEngine

### Negative

- 기존 Bash PoC 운영 스크립트와 즉시 교체 불가 (병행 기간 필요)
- webshell remote 실행은 Phase 2 adapter 설계 추가
- deployment automation(`aella_cli`) 통합은 Phase 3+ 별도 작업

### Neutral

- 레거시 `stellar_poc*.sh`는 workspace에 read-only로 잔존
- Python 버전 정책은 Phase 1에서 `pyproject.toml`로 확정 (Phase 0에서는 미작성)

---

## References

- [PROJECT_CHARTER.md](../../PROJECT_CHARTER.md) — §5 Keep/Remove
- [SKILL_SPEC.md](../../SKILL_SPEC.md) — P1, P13
- Legacy: `stellar_dns_tunnel_file_client.py`, `stellar_dga_model_client.py`
