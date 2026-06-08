# Detection Scenario Platform — Event Store Acceptance Specification

**문서 버전:** 1.0.0 (Phase 0.6)  
**상태:** Valid Event Store implementation criteria  
**References:** [EVENT_SCHEMA_FREEZE.md](./EVENT_SCHEMA_FREEZE.md), [EVENT_STORE_SPEC.md](./EVENT_STORE_SPEC.md), ADR 0002, ADR 0005

---

## 1. Purpose

Event Store는 DSP의 **유일한 Single Source of Truth (SOT)**이다.  
본 문서는 구현이 "유효한 Event Store"로 인정받기 위한 **필수·금지·증거** 기준을 정의한다.

Validation Engine과 Reporting Engine은 본 spec을 충족하는 Store 구현에만 연결할 수 있다.

---

## 2. Required Entities

Implementation MUST support the frozen entity model (`dsp_entity_model: 1.0.0`):

| Entity | Materialization | Required fields (minimum) |
|--------|-----------------|---------------------------|
| **Run** | `run.json` or `runs` table | run_id, event_schema_version, target_net, started_at, status, dry_run, requested_scenarios, config_snapshot, dsp_version |
| **ScenarioRun** | Derived row or lifecycle events | run_id, scenario_id, manifest_version, lifecycle_status |
| **Event** | `events` table | All columns per EVENT_SCHEMA_FREEZE §8 |
| **ValidationResult** | `validation.json` (derived cache) | Per §3.4 — not append input |
| **Report** | `report.md` + metadata | Per §3.5 — regenerable derivative |

Phase 1A minimum: **Run + Event** fully implemented; ScenarioRun derivable; ValidationResult/Report written by other engines but Store API must not block them.

---

## 3. Required Relationships

```
Run 1 ── * Event                 (FK: event.run_id → run.run_id)
Run 1 ── * ScenarioRun           (logical: one per requested scenario)
ScenarioRun 1 ── * Event         (filter: scenario_id)
ScenarioRun 1 ── 1 ValidationResult
Run 1 ── 1 Report                (regenerable)
```

### 3.1 Referential Integrity Rules

| Rule | Enforcement |
|------|-------------|
| Every Event MUST have valid `run_id` | FK or application check on append |
| Events MUST NOT use unknown `scenario_id` at run time (except `runner` stage meta) | Runner preflight |
| ValidationResult MUST reference scenario in run or skipped with `scenario_skipped` event | ValidationEngine |
| No Event references future run_id | append API scoped to open run |

### 3.2 Immutability Rules

| Rule | After `Run.status = completed` |
|------|----------------------------------|
| Event append | **Forbidden** |
| Event update | **Forbidden** |
| Event delete | **Forbidden** (within retention window) |
| aggregate / sample / export | **Allowed** (read-only) |

---

## 4. Persistence Requirements

### 4.1 Storage Backend

| Requirement | Specification |
|-------------|---------------|
| Primary backend | SQLite (stdlib `sqlite3`) per ADR 0005 |
| Per-run isolation | `~/.dsp/runs/<run_id>/events.db` (env override allowed) |
| WAL mode | Recommended for concurrent read during run |
| In-memory | `:memory:` MUST be supported for tests |
| JSONL | Optional **export only** — not primary SOT |

### 4.2 Schema

Frozen v1.0.0 columns (EVENT_SCHEMA_FREEZE §8):

```sql
CREATE TABLE events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_schema_version TEXT NOT NULL DEFAULT '1.0.0',
    run_id      TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    stage       TEXT NOT NULL DEFAULT 'main',
    event       TEXT NOT NULL,
    status      TEXT NOT NULL,
    target      TEXT NOT NULL DEFAULT '',
    artifact    TEXT NOT NULL DEFAULT '',
    evidence    TEXT NOT NULL DEFAULT '{}',
    source      TEXT NOT NULL DEFAULT 'local',
    exit_code   INTEGER,
    tags        TEXT NOT NULL DEFAULT '[]'
);
```

### 4.3 Required Indexes

| Index | Columns | Purpose |
|-------|---------|---------|
| idx_events_run | run_id | Run-scoped queries |
| idx_events_scenario | run_id, scenario_id | Per-scenario aggregate |
| idx_events_status | run_id, scenario_id, status | Metric filters |
| idx_events_event | run_id, scenario_id, event | Metric filters |

### 4.4 Required API Surface

| Method | Behavior |
|--------|----------|
| `open_run(run_id, metadata)` | Create run context + DB |
| `append(event)` | Insert row; assign id; validate schema |
| `aggregate(run_id, scenario_id, metric_defs)` | SQL aggregation per validation_profile |
| `count(run_id, scenario_id, filters)` | Fail-fast invariant support |
| `sample(run_id, scenario_id, limit)` | Reporting excerpts |
| `close_run()` | Mark run complete; read-only |
| `export_jsonl(path)` | Optional derivative |

**Forbidden:** Public API exposing raw UPDATE/DELETE on events.

---

## 5. Retention Requirements

Frozen policy (EVENT_SCHEMA_FREEZE §7):

| Artifact | Default retention | Location |
|----------|-------------------|----------|
| `events.db` | 90 days / last 500 runs | run directory |
| `manifest.snapshot.json` | Same as run | run directory |
| `validation.json` | Same as run | run directory |
| `report.md` | Same as run | run directory |
| `events.jsonl` | Optional on completion | run directory |
| `debug.log` | 30 days | run directory — **not SOT** |

Phase 1A: retention **policy documented**; prune command may defer to Phase 2.  
Phase 1A MUST: completed run immutability enforced regardless of prune.

---

## 6. Evidence Requirements

Valid Event Store claim MUST be backed by:

### 6.1 Unit Test Evidence

| Test | Proves |
|------|--------|
| append assigns monotonic id | Identity |
| append rejects forbidden status | Vocabulary |
| append rejects missing run_id | Integrity |
| aggregate count matches manual insert count | Metric correctness |
| completed run append raises | Immutability |
| distinct_artifact aggregate | Complex metric support |
| in-memory parity with file-backed | Test/production parity |

### 6.2 Integration Evidence

| Artifact | Content |
|----------|---------|
| Sample `events.db` | Lifecycle + traffic rows from dummy run |
| JSONL export | Row-for-row match with DB |
| aggregate output | Matches ValidationResult.metrics for same run |

### 6.3 Audit Trail

Each Event row MUST be independently auditable:

- `timestamp` UTC ISO-8601
- `source` ∈ {local, remote, dry_run, runner}
- `evidence` valid JSON object (default `{}`)
- `event_schema_version` = `"1.0.0"`

---

## 7. Recovery Expectations

| Scenario | Expected behavior |
|----------|-------------------|
| Crash mid-run (Run.status=running) | Run marked `aborted`; partial events preserved; validation may produce `failed` / `code_failure` |
| Corrupt events.db | Run fails validation open; error logged; no silent repair |
| Missing validation.json | Regenerate from Store + manifest via ValidationEngine |
| Missing report.md | Regenerate from Store + validation.json |
| Replay / import JSONL | New run_id; read-only import; no merge into completed run |
| Store write failure during execute | Runner aborts run per SCENARIO_INTERFACE_FREEZE §6 |

**No auto-healing** that mutates historical events.

---

## 8. Event Vocabulary Compliance

### 8.1 Allowed event.status (v1.0.0)

`info` | `sent` | `response` | `nxdomain` | `timeout` | `error` | `connection_refused` | `dns_failure`

### 8.2 Forbidden on Event.status

`success` | `failed` | `partial` | `skipped` → belong to ValidationResult / ScenarioRun only

### 8.3 Mandatory Lifecycle Events (executed scenario)

| event | status | stage |
|-------|--------|-------|
| scenario_started | info | executor |
| scenario_completed | info | executor |
| scenario_skipped | info | prepare |
| scenario_aborted | error | executor |

---

## 9. Acceptance Checklist

| ID | Criterion | Phase 1A |
|----|-----------|----------|
| ES-1 | SQLite per-run storage | Required |
| ES-2 | Frozen schema columns | Required |
| ES-3 | Append-only API | Required |
| ES-4 | aggregate() for validation | Required |
| ES-5 | sample() for reporting | Required |
| ES-6 | Indexes present | Required |
| ES-7 | Completed run read-only | Required |
| ES-8 | :memory: for tests | Required |
| ES-9 | JSONL export | Optional |
| ES-10 | prune command | Phase 2+ |

**Pass:** ES-1 through ES-8 all Required = Pass.

---

## 10. Invalid Implementations (Examples)

| Implementation | Why invalid |
|----------------|-------------|
| JSONL file as primary SOT without SQLite | ADR 0005 violation |
| In-memory dict only in production | No persistence / audit |
| Event UPDATE to fix counts | Immutability violation |
| Validation reads table other than `events` | Split SOT |
| Direct scenario SQL without EventStore API | Bypass / untestable |
| Global events.db for all runs | Isolation / retention risk |
| stdout tee as parallel event log | Dual path |

---

## 11. Related Documents

- [PATH_EQUALITY_VERIFICATION_SPEC.md](./PATH_EQUALITY_VERIFICATION_SPEC.md)
- [ARCHITECTURE_COMPLIANCE_CHECKLIST.md](./ARCHITECTURE_COMPLIANCE_CHECKLIST.md) §5
- [PHASE_1_ACCEPTANCE_CRITERIA.md](./PHASE_1_ACCEPTANCE_CRITERIA.md)
- [docs/adr/0002-event-store-as-sot.md](./docs/adr/0002-event-store-as-sot.md)
- [docs/adr/0005-sqlite-primary-storage.md](./docs/adr/0005-sqlite-primary-storage.md)
