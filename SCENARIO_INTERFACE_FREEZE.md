# Detection Scenario Platform — Scenario Interface Freeze

**문서 버전:** 1.0.0 (Phase 0.5 — **FROZEN**)  
**상태:** Official Scenario contract — no implementation in this document

---

## 1. Freeze Declaration

The `Scenario` protocol defined herein is the **only** supported extension point for traffic/behavior generation.  
Changes require ADR + `scenario_interface_version` bump (currently `1.0.0`).

---

## 2. Official Contract (Conceptual)

```python
# FROZEN INTERFACE — documentation only

scenario_interface_version = "1.0.0"


class Scenario(Protocol):
    @classmethod
    def scenario_id(cls) -> str: ...

    def prepare(self, ctx: RunContext, targets: TargetSet) -> None: ...

    def execute(self, ctx: RunContext, targets: TargetSet) -> None: ...

    def summarize(self, ctx: RunContext) -> ScenarioSummary: ...


# NOT part of Scenario — owned by platform:
#   ValidationEngine.validate(run_id, scenario_id) -> ValidationResult
#   ReportingEngine.generate(run_id, results) -> Report
```

---

## 3. Scenario Lifecycle (Frozen)

```
REGISTERED ──► PREPARING ──► EXECUTING ──► EXECUTED ──► [Validation external]
                  │              │                         │
                  ▼              ▼                         ▼
              SKIPPED        ABORTED                  VALIDATED
                  │              │                         │
                  └──────────────┴─────────────────────────┘
                                          │
                                          ▼
                                    SUMMARIZING (summarize())
```

| State | Entered when | Exited when |
|-------|--------------|-------------|
| REGISTERED | Plugin Loader ACTIVE | Runner selects scenario |
| PREPARING | `prepare()` called | prepare returns or raises |
| SKIPPED | prepare/target check fails | terminal — `scenario_skipped` event |
| EXECUTING | `execute()` called | execute returns or raises |
| ABORTED | unhandled exception in execute | `scenario_aborted` event |
| EXECUTED | execute completes normally | ValidationEngine starts |
| VALIDATED | ValidationEngine completes | Reporting uses result |
| SUMMARIZING | `summarize()` called | returns ScenarioSummary |

---

## 4. Method Responsibilities

### 4.1 `scenario_id() -> str`

| Rule | |
|------|--|
| MUST match `manifest.yaml` `id` | |
| MUST match directory name | |
| MUST be stable (not config-dependent) | |

### 4.2 `prepare(ctx, targets) -> None`

**Purpose:** Preconditions, config resolution, non-traffic setup.

| Allowed | Forbidden |
|---------|-----------|
| Read manifest defaults + RunConfig | Network I/O that generates detection traffic |
| Validate targets against `supported_targets` | Return success/failure bool |
| Emit `scenario_prepared` event (info) | Call ValidationEngine |
| Raise `ScenarioSkipError` (platform exception) | Mutate ValidationResult |

**On skip:** Runner catches `ScenarioSkipError`, writes `scenario_skipped` event, does NOT call `execute()`.

### 4.3 `execute(ctx, targets) -> None`

**Purpose:** Generate traffic/behavior; append events only.

| Allowed | Forbidden |
|---------|-----------|
| Append events via `ctx.event_store.append()` | Return bool / decision enum |
| Use `dsp/protocols/` libraries | Parse stdout for metrics |
| Emit `scenario_started` at start | Call `validate()` |
| Emit `scenario_completed` at end | Set planned/attempted counters off-store |
| Raise exceptions (Runner → `scenario_aborted`) | Print SUCCESS markers for validation |

**Return type:** `None` only. Always.

### 4.4 `summarize(ctx) -> ScenarioSummary`

**Purpose:** Human-readable metrics for report enrichment.

| Allowed | Forbidden |
|---------|-----------|
| Query `ctx.event_store` for this run+scenario | Parse log files |
| Return metric dict | Declare success/failure |
| Add `notes: list[str]` for operator hints | Duplicate ValidationEngine logic as decision |

```python
@dataclass
class ScenarioSummary:
    scenario_id: str
    metrics: dict[str, int | float | str]
    event_count: int
    notes: list[str]
```

---

## 5. Ownership Boundaries (Frozen)

| Concern | Owner | NOT Scenario |
|---------|-------|--------------|
| Traffic generation | Scenario.execute() | — |
| Event SOT writes (traffic) | Scenario.execute() | — |
| Success/failure decision | **ValidationEngine** | Scenario |
| Threshold definition | **manifest.validation_profile** | hardcoded in execute |
| Report structure | **ReportingEngine** | Scenario |
| Report decision row | **ValidationResult** | summarize() |
| Target discovery | **TargetProvider** | Scenario |
| CIDR enforcement | **TargetProvider + Runner** | Scenario |
| Timeout enforcement | **Runner** (wall clock) | Scenario (may respect deadline) |
| Detection confirmation | **DetectionAdapter** (Phase 3+) | Scenario |
| Plugin discovery | **Plugin Loader** | Scenario |

---

## 6. Error Handling (Frozen)

| Error type | Handler | Event | Scenario continues? |
|------------|---------|-------|---------------------|
| `ScenarioSkipError` | Runner | `scenario_skipped` | next scenario |
| `SafetyViolationError` | Runner | run `config_error` | **abort run** |
| Generic exception in `prepare` | Runner | `scenario_aborted` | next scenario (default) |
| Generic exception in `execute` | Runner | `scenario_aborted` | next scenario (default) |
| Event store write failure | Runner | run `aborted` | **abort run** |

Scenario MUST NOT swallow exceptions to fake success — re-raise or let propagate.

---

## 7. Cancellation Behavior (Frozen)

| Signal | Behavior |
|--------|----------|
| Run wall-clock timeout | Runner sets cancelled flag; execute checks `ctx.cancelled` between batches |
| SIGINT (operator) | Graceful: complete current event batch, `scenario_aborted`, run `aborted` |
| Per-scenario timeout | `manifest.safety.max_duration_sec` — Runner enforces; execute cooperates |

Scenario `execute()` SHOULD poll `ctx.cancelled` in loops (DNS batches, HTTP requests).  
Runner MUST NOT kill threads abruptly without `scenario_aborted` event.

---

## 8. Timeout Expectations (Frozen)

| Timeout | Default | Enforced by |
|---------|---------|-------------|
| Whole run | 600s (configurable) | Runner |
| Per scenario | `safety.max_duration_sec` | Runner |
| Per protocol op | executor internal (e.g. 5s socket) | executor via protocols lib |

Manifest `max_duration_sec` is **contract** — Runner kills scenario phase, not whole run (unless last scenario).

---

## 9. Validation Ownership (Frozen)

```
Scenario ──writes──► Event Store
                         │
ValidationEngine ◄──reads──┘
        │
        ▼
ValidationResult (decision, reason, metrics)
```

- Scenario **never** imports ValidationEngine
- Tests **never** define alternate validation path
- `validation_profile` in manifest is sole threshold source

---

## 10. Reporting Ownership (Frozen)

```
ValidationResult ──┐
                   ├──► ReportingEngine ──► Report
Event Store ───────┘      (samples only)
ScenarioSummary ──► optional enrichment section
```

- Report **primary table** from ValidationResult only
- ScenarioSummary is **supplementary** — cannot override decision
- stdout / debug.log: appendix only, labeled "Non-SOT Debug"

---

## 11. RunContext (Frozen surface)

Scenario receives read-mostly context:

| Field | Scenario may read | Scenario may write |
|-------|-------------------|-------------------|
| `run_id` | yes | no |
| `target_net` | yes | no |
| `event_store` | via append | append only |
| `config` | yes | no |
| `dry_run` | yes | no |
| `cancelled` | yes | no |
| `deadline` | yes | no |

---

## 12. Executor Module Boundary

| Layer | File | Contract |
|-------|------|----------|
| Scenario | `scenario.py` | Scenario protocol — orchestrates prepare/execute/summarize |
| Executor | `executor.py` | `run(ctx, targets, config) -> None` — protocol I/O only |

Executor MUST NOT implement Scenario protocol. Scenario calls executor.

---

## 13. Anti-Patterns (Frozen prohibition)

| Pattern | Status |
|---------|--------|
| `execute() -> bool` | **Forbidden** |
| `validate()` on Scenario class | **Forbidden** |
| Vendor if/else in executor | **Forbidden** — use detection_mappings |
| stdout SUCCESS markers | **Forbidden** |
| Direct SQLite access bypassing EventStore API | **Forbidden** |

---

## 14. Versioning

| Version | Meaning |
|---------|---------|
| `scenario_interface_version: 1.0.0` | prepare/execute/summarize signatures |
| `manifest.version` | implementation semver per plugin |

Adding optional method to Scenario (e.g. `teardown()`) → interface `1.1.0` with default no-op in base.

---

## 15. Related Documents

- [SCENARIO_MANIFEST_SPEC.md](./SCENARIO_MANIFEST_SPEC.md)
- [PLUGIN_DISCOVERY_SPEC.md](./PLUGIN_DISCOVERY_SPEC.md)
- [EVENT_SCHEMA_FREEZE.md](./EVENT_SCHEMA_FREEZE.md)
- [SCENARIO_FRAMEWORK_SPEC.md](./SCENARIO_FRAMEWORK_SPEC.md)
- [SKILL_SPEC.md](./SKILL_SPEC.md) §4
