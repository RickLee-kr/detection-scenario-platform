# Detection Scenario Platform — Event Store Specification

**문서 버전:** 0.1.0 (Phase 0)  
**상태:** Design only — no implementation

---

## 1. Purpose

Event Store는 DSP의 **유일한 Single Source of Truth (SOT)**이다.

- Validation Engine은 Event Store만 조회한다
- Reporting Engine은 Event Store만 조회한다
- stdout, grep, log file, overlap env는 SOT가 **아니다**

레거시 `state/events/*.tsv` + `build_module_summary_from_events` awk 패턴을 Python-native store로 진화시킨다.

---

## 2. Storage Backend Comparison

### 2.1 Evaluation Matrix

| Criterion | JSONL | SQLite |
|-----------|-------|--------|
| Append performance | Excellent (sequential write) | Excellent (WAL mode) |
| Query / aggregate | Poor (full scan) | Excellent (SQL, indexes) |
| Schema enforcement | Weak (convention only) | Strong (typed columns + JSON col) |
| Concurrent writers | Risky (file lock manual) | Good (WAL + transactions) |
| Human inspection | Excellent (`tail`, `jq`) | Good (sqlite3 CLI, export) |
| Test fixtures | Easy (copy file) | Easy (in-memory `:memory:`) |
| 3-year scale (10K runs) | Many large files | Compact, queryable |
| Dependency | stdlib only | stdlib `sqlite3` |
| Migration | Line-by-line version field | Schema version table |

### 2.2 Legacy Pain Points Addressed

| Legacy issue | JSONL alone | SQLite |
|--------------|-------------|--------|
| awk summary scripts | Still need scan | SQL `GROUP BY` |
| `sent>0 && event_count=0` detection | Manual | Constraint + count query |
| Per-module file split (dns/dga/http) | Multiple JSONL | Single table, `scenario` index |
| File lock (`flock`) | Required | Transaction |
| Cross-run contamination | Manual run_id filter | Indexed `run_id` |

### 2.3 Recommendation

**권장안: SQLite (primary) + JSONL export (optional)**

| Layer | Choice |
|-------|--------|
| **Runtime SOT** | SQLite per run: `~/.dsp/runs/<run_id>/events.db` |
| **Debug / CI artifacts** | Post-run export: `events.jsonl` |
| **Human audit** | `dsp export --run-id ... --format jsonl` |

**이유:**

1. Validation Engine의 aggregate가 핵심 — SQL이 awk/grep 대체
2. Fail-fast invariant가 count query — SQLite가 자연스러움
3. 3년 확장 시 run history 검색·비교 필요
4. stdlib `sqlite3`로 외부 의존 없음
5. JSONL export로 레거시 TSV의 "human readable" 장점 유지

**Phase 1 대안:** 개발 초기 in-memory SQLite + JSONL fixture import/export만으로도 충분.

**JSONL-only를 선택하지 않는 이유:** Validation/Reporting이 매번 full scan → 시나리오·run 증가 시 CI 및 ops 부담. 레거시 awk summary가 이미 "쿼리 언어 부재"로 복잡해진 전례.

---

## 3. Event Model

### 3.1 Core Event Schema

```python
@dataclass
class Event:
    # Identity
    id: int | None              # auto-increment (DB)
    event_schema_version: str  # "1.0.0"

    # Correlation
    run_id: str               # required, indexed
    timestamp: datetime       # UTC ISO-8601, indexed

    # Scenario dimensions
    scenario: str             # e.g. "dns_tunnel", indexed
    stage: str                # e.g. "executor", "prepare"
    event: str                # e.g. "query_sent", "http_response"
    status: str               # sent | response | nxdomain | error | info | ...

    # Target & artifact
    target: str               # IP, host:port, or URL host
    artifact: str             # FQDN, full URL, username, etc.

    # Evidence (structured)
    evidence: dict[str, Any] | str  # JSON preferred

    # Provenance
    source: str               # "local" | "remote" | "dry_run"
    exit_code: int | None     # subprocess only, else null

    # Optional
    tags: list[str]           # ["phase:nx", "dry_run"]
```

### 3.2 Field Rules

| Field | Required | Notes |
|-------|----------|-------|
| `run_id` | Yes | UUID v4 or `{timestamp}_{slug}` |
| `scenario` | Yes | matches manifest.id |
| `event` | Yes | verb_noun snake_case |
| `status` | Yes | controlled vocabulary (§3.3) |
| `timestamp` | Yes | server-generated default; override for replay |
| `target` | No | empty for meta events |
| `artifact` | No | empty for meta events |
| `evidence` | Recommended | validation metric extraction source |

### 3.3 Status Vocabulary

| Status | Meaning |
|--------|---------|
| `info` | Lifecycle meta (started, completed, skipped) |
| `sent` | Request/query dispatched |
| `response` | Response received (any code) |
| `nxdomain` | DNS NXDOMAIN |
| `timeout` | No response in window |
| `error` | Protocol/socket error |
| `connection_refused` | TCP refused |
| `dns_failure` | DNS resolution failed (HTTP context) |

**금지:** `success`, `failed` as event status — 판정은 Validation Engine only.

### 3.4 Example Events

**DNS Tunnel — query sent:**

```json
{
  "run_id": "20260605_abc123",
  "timestamp": "2026-06-05T13:20:00Z",
  "scenario": "dns_tunnel",
  "stage": "executor",
  "event": "query_sent",
  "status": "sent",
  "target": "10.10.10.20",
  "artifact": "idx-000042-JBSWY3DPFQQHO33S.dns-tunnel.com",
  "evidence": {
    "qtype": "A",
    "session": "sess-7f3a",
    "seq": 42,
    "label_length": 48,
    "bytes_encoded": 30
  },
  "source": "local"
}
```

**DGA — NXDOMAIN:**

```json
{
  "scenario": "dga",
  "event": "query_sent",
  "status": "nxdomain",
  "target": "10.10.10.20",
  "artifact": "xk9mq2.xdr.ooo",
  "evidence": {
    "phase": "nx",
    "base_domain": "xdr.ooo",
    "qtype": "A"
  }
}
```

**HTTP Follow-up:**

```json
{
  "scenario": "http_followup",
  "event": "http_response",
  "status": "response",
  "target": "10.10.10.20:443",
  "artifact": "https://10.10.10.20:443/admin",
  "evidence": {
    "method": "GET",
    "http_code": 403
  }
}
```

**Scenario lifecycle:**

```json
{
  "scenario": "dns_tunnel",
  "event": "scenario_started",
  "status": "info",
  "evidence": {"config_hash": "a1b2c3"}
}
```

---

## 4. SQLite Schema

### 4.1 DDL

```sql
CREATE TABLE schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO schema_meta VALUES ('event_schema_version', '1.0.0');

CREATE TABLE events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    timestamp   TEXT NOT NULL,          -- ISO-8601 UTC
    scenario    TEXT NOT NULL,
    stage       TEXT NOT NULL DEFAULT 'main',
    event       TEXT NOT NULL,
    status      TEXT NOT NULL,
    target      TEXT NOT NULL DEFAULT '',
    artifact    TEXT NOT NULL DEFAULT '',
    evidence    TEXT NOT NULL DEFAULT '{}',  -- JSON
    source      TEXT NOT NULL DEFAULT 'local',
    exit_code   INTEGER,
    tags        TEXT NOT NULL DEFAULT '[]'     -- JSON array
);

CREATE INDEX idx_events_run_id ON events(run_id);
CREATE INDEX idx_events_scenario ON events(run_id, scenario);
CREATE INDEX idx_events_status ON events(run_id, scenario, status);
CREATE INDEX idx_events_event ON events(run_id, scenario, event);
CREATE INDEX idx_events_timestamp ON events(timestamp);
```

### 4.2 PRAGMA Settings

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
```

### 4.3 Aggregate Query Examples

**DNS Tunnel — query_sent count:**

```sql
SELECT COUNT(*) AS query_sent
FROM events
WHERE run_id = ? AND scenario = 'dns_tunnel'
  AND event = 'query_sent' AND status = 'sent';
```

**DGA — nxdomain / resolvable:**

```sql
SELECT
  SUM(CASE WHEN status = 'nxdomain' THEN 1 ELSE 0 END) AS nxdomain,
  SUM(CASE WHEN status = 'response' THEN 1 ELSE 0 END) AS resolvable
FROM events
WHERE run_id = ? AND scenario = 'dga' AND event = 'query_sent';
```

**DGA — base_domain check:**

```sql
SELECT DISTINCT json_extract(evidence, '$.base_domain') AS base_domain
FROM events
WHERE run_id = ? AND scenario = 'dga'
  AND json_extract(evidence, '$.base_domain') IS NOT NULL;
```

**HTTP — attempted / responses:**

```sql
SELECT
  COUNT(*) AS attempted,
  SUM(CASE WHEN status = 'response' THEN 1 ELSE 0 END) AS responses
FROM events
WHERE run_id = ? AND scenario = 'http_followup'
  AND event IN ('http_request_sent', 'http_response');
```

---

## 5. JSONL Export Format

Post-run or streaming export for audit:

```jsonl
{"run_id":"...","timestamp":"...","scenario":"dns_tunnel","event":"query_sent",...}
```

| Field | Same as SQLite row (evidence as object, not string) |
| Export trigger | End of run, `dsp export`, CI artifact upload |
| Import | `dsp import --run-id ... events.jsonl` for replay validation |

---

## 6. EventStore API

### 6.1 Interface

```python
class EventStore(ABC):
    def open(self, run_id: str, path: Path) -> None: ...
    def append(self, event: Event) -> int: ...          # returns event id
    def append_batch(self, events: list[Event]) -> None: ...
    def count(self, query: EventQuery) -> int: ...
    def aggregate(self, spec: AggregateSpec) -> dict: ...
    def sample(self, query: EventQuery, limit: int) -> list[Event]: ...
    def export_jsonl(self, path: Path) -> None: ...
    def close(self) -> None: ...
```

### 6.2 EventQuery

```python
@dataclass
class EventQuery:
    run_id: str
    scenario: str | None = None
    event: str | None = None
    status: str | None = None
    stage: str | None = None
```

### 6.3 AggregateSpec

```python
@dataclass
class AggregateSpec:
    run_id: str
    scenario: str
    metrics: list[MetricDef]   # from manifest validation.metrics

@dataclass
class MetricDef:
    name: str                  # e.g. "query_sent"
    filter: EventQuery         # what rows to count
    extract: str | None        # json_extract path for evidence
```

Manifest-driven metrics → **Validation Engine code change 없이** 새 metric 추가 가능.

---

## 7. Legacy TSV Migration Mapping

레거시 참고용 (DSP는 TSV를 native로 사용하지 않음):

| Legacy TSV Column | DSP Field |
|-------------------|-----------|
| `timestamp` | `timestamp` |
| `run_id` | `run_id` |
| `module` | `scenario` |
| `stage` | `stage` |
| `target` | `target` |
| `action` | `event` |
| `artifact` | `artifact` |
| `status` | `status` |
| `exit_code` | `exit_code` |
| `evidence_value` | `evidence` (parsed from `\|` or JSON) |
| `source` | `source` |

**Import tool (Phase 2):** `dsp import-legacy-tsv dns_events.tsv` → SQLite for historical comparison.

---

## 8. Integrity & Fail-Fast

### 8.1 Invariants (enforced by Validation Engine + optional DB triggers)

| ID | Check |
|----|-------|
| INV-1 | `scenario_completed` exists after execute phase |
| INV-2 | Traffic event count > 0 OR explicit `scenario_skipped` |
| INV-3 | No `status IN ('success','failed')` in events table |
| INV-4 | All `target` IPs ∈ run's `target_net` (Target Engine pre-validates) |
| INV-5 | `responses <= attempted` for HTTP |

### 8.2 Empty Store Semantics

| State | Validation reason |
|-------|-------------------|
| DB file missing | `event_store_missing` |
| DB exists, 0 rows for scenario | `no_events_executed` |
| Header-only / meta only, 0 traffic | `no_traffic_events` |
| Traffic in DB, threshold fail | scenario-specific reason |

**레거시 교훈:** `sot_file_missing` vs `no_queries_executed` vs `base_domain=unknown` 구분 명확화.

---

## 9. Concurrency & Performance

| Concern | Policy |
|---------|--------|
| Single run | One SQLite file, one writer (Scenario Engine sequential default) |
| Parallel scenarios | WAL mode; single connection with transaction per append_batch |
| Expected volume | DNS tunnel ~15K events/run; DGA ~530; HTTP ~20 |
| Retention | Configurable: keep last N runs; archive JSONL to cold storage |
| Index maintenance | `run_id` + `scenario` sufficient for MVP |

---

## 10. Run Directory Layout

```
~/.dsp/runs/<run_id>/
├── events.db              # SOT
├── events.jsonl           # optional export
├── manifest.snapshot.json # resolved config
├── validation.json        # ValidationResult[]
├── report.md
└── debug.log              # NOT SOT
```

---

## 11. Testing Event Store

```python
# Fixture pattern — same store prod uses
def test_dns_tunnel_validation_threshold():
    store = EventStore(":memory:")
    store.open("test-run", ...)
    for i in range(1500):
        store.append(make_query_sent_event(i))
    result = ValidationEngine().validate("test-run", "dns_tunnel")
    assert result.decision == "success"
```

**금지:** mock validation bypassing EventStore  
**필수:** `test_stdout_rejection` — events=0 → must fail

---

## 12. Future Extensions

| Extension | Schema impact |
|-----------|---------------|
| Detection adapter events | New `scenario="detection"` or `source="stellar_api"` |
| Binary blobs (pcap ref) | `evidence.blob_ref` path, not in DB |
| Multi-tenant | `tenant_id` column |
| Event streaming | JSONL tail → Kafka (export sidecar) |

---

## 13. Related Documents

- [PROJECT_CHARTER.md](./PROJECT_CHARTER.md)
- [ARCHITECTURE_SPEC.md](./ARCHITECTURE_SPEC.md)
- [SCENARIO_FRAMEWORK_SPEC.md](./SCENARIO_FRAMEWORK_SPEC.md)
- [SKILL_SPEC.md](./SKILL_SPEC.md)
