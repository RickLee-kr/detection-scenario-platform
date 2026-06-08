# ADR 0005: SQLite as Primary Event Store

**Status:** Accepted  
**Date:** 2026-06-05  
**Phase:** 0.1

---

## Context

레거시는 `state/events/*.tsv` (tab-separated) + awk `build_module_summary_from_events`로 집계했다. 모듈별 파일 분리(dns, dga, http), `flock` append, evidence_value pipe-delimited parsing.

DSP Event Store는 30–50 시나리오, run당 최대 ~20K events, 3년 run history 검색을 수용해야 한다.

[EVENT_STORE_SPEC.md](../../EVENT_STORE_SPEC.md)에서 JSONL vs SQLite 비교 수행.

---

## Problem

TSV/JSONL file-only SOT의 한계:

1. **Aggregate = full scan** — 시나리오·metric 증가 시 awk/Python scan 비용
2. **Schema weak** — 컬럼 drift, evidence parse error
3. **Concurrent append** — parallel scenario 시 file lock (레거시 flock)
4. **Query expressiveness** — `nxdomain>=300 AND base_domain=xdr.ooo` 매번 스크립트
5. **Test fixtures** — TSV 문자열 vs typed row
6. **50 scenarios** — 50개 summary awk case → unmaintainable

---

## Alternatives Considered

### A. JSONL only (one file per run)

- 장점: stdlib, `tail -f`, CI artifact friendly
- 단점: every validation full scan; no index; 50 scenarios × N runs → slow postmortem

### B. TSV (legacy compatible)

- 장점: 레거시 import 쉬움
- 단점: awk summary 재도입 위험, ADR 0001 Python 전면과 상충

### C. PostgreSQL / MySQL

- 장점: enterprise scale
- 단점: PoC lab DB 운영 부담, appliance dependency — overkill

### D. SQLite primary + JSONL export

- 장점: SQL aggregate, indexed, in-memory test, zero ops; export for audit
- 단점: single-writer semantics (WAL로 완화); not distributed

### E. Embedded LMDB / DuckDB

- 장점: analytics
- 단점: stdlib 아님, 추가 dependency — Phase 1 simplicity 우선

---

## Decision

**SQLite를 1차 Event Store로 사용한다.**

| Role | Storage |
|------|---------|
| Runtime SOT | `~/.dsp/runs/<run_id>/events.db` |
| Tests | `:memory:` SQLite |
| Audit export | `events.jsonl` (derivative, post-run) |
| Legacy import | Optional TSV→SQLite tool (Phase 2) |

**PRAGMA:** `journal_mode=WAL`, `synchronous=NORMAL`

**Schema:** `events` table + indexes on `(run_id)`, `(run_id, scenario)`, `(run_id, scenario, status)`

**Validation metrics:** SQL `COUNT` / `json_extract(evidence, '$.field')` — manifest-driven query templates, not per-scenario hardcoded SQL in core (MetricDef abstraction).

---

## Consequences

### Positive

- ValidationEngine single code path for 1 or 50 scenarios
- `dsp validate --run-id` O(log n) with indexes
- pytest fixture: insert rows → aggregate — no string awk
- 3-year run history: SQL query across runs (Phase 3 reporting)

### Negative

- SQLite file corruption risk (rare) → run-level isolation, export JSONL backup
- Very high volume (100K+ events/run) 시 tuning 필요 — current cap ~15K OK
- Agent must not embed scenario-specific SQL in core engine

### Neutral

- JSONL remains human audit path, not SOT
- Event schema version in `schema_meta` table
- Cloud SIEM export = adapter, not store replacement

---

## References

- [EVENT_STORE_SPEC.md](../../EVENT_STORE_SPEC.md)
- [ADR 0002](./0002-event-store-as-sot.md)
- Legacy: `stellar_poc_event_sot.sh` TSV + awk
