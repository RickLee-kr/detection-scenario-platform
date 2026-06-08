# Execution Provider — Architecture Decision Record

**문서 버전:** 1.0.0  
**상태:** Architecture only — no implementation  
**Date:** 2026-06-06

본 문서는 Execution Provider 도입 시 **경계 결정(boundary decisions)** 을 명시한다. 구현 착수 전 Agent·개발자는 본 레코드와 ADR 0006을 함께 읽는다.

---

## 1. Decision Summary

| Question | Decision |
|----------|----------|
| What runs locally? | Orchestration, Event Store, Validation, Reporting, default traffic generation |
| What runs remotely? | Traffic-generating process/socket (when Mode B selected) |
| What remains inside scenarios? | Protocol logic, event recording contract, lifecycle hooks |
| What belongs to execution providers? | Transport, remote dispatch, event sync, execution metadata |
| Event Store authority? | DSP Host local store — remote events synced in, same schema |
| Validation changes? | **None** — Event Store aggregate only |

---

## 2. What Runs Locally (DSP Host)

다음은 **항상 DSP Host**에서 실행된다:

| Component | Rationale |
|-----------|-----------|
| **Runner** | CLI, run lifecycle, config merge |
| **Scenario Engine** | Scenario dispatch order, skip/fail-fast policy |
| **Plugin Loader** | Scenario registry — scenarios are local Python modules |
| **Target Provider** | Lab target resolution (may probe network, but orchestration stays local) |
| **Execution Provider Registry** | Provider selection, default = local |
| **Event Store** | Authoritative SOT — append, query, aggregate |
| **Validation Engine** | Threshold application, fail-fast invariants |
| **Reporting Engine** | Report generation from ValidationResult + Event Store |
| **Detection Adapters** (future) | Vendor API poll from orchestrator |

### Mode A — Traffic generation also local

`LocalExecutionProvider` 선택 시 트래픽 생성 프로세스도 DSP Host에서 실행 (현재 Phase 1–5 동작).

### Mode B — Orchestration local, traffic remote

Provider가 remote host에서 executor를 구동하지만, **판정·저장·리포트는 로컬**.

---

## 3. What Runs Remotely (Mode B Only)

`WebshellExecutionProvider`, `AgentExecutionProvider`, `SSHExecutionProvider` 선택 시:

| Remote responsibility | Examples |
|----------------------|----------|
| Protocol I/O egress | UDP/53 DNS query from victim NIC |
| HTTP client origin | http_followup requests from compromised host |
| SSH client origin | ssh_failure auth attempts **from** remote (if scenario dispatched remotely) |
| Event buffer (temporary) | Remote-side event batch before sync |
| Optional executor stub | Minimal Python/shell stub dropped by webshell provider |

### NOT remote

| Component | Stays on DSP Host |
|-----------|-------------------|
| Validation | Always |
| Event Store primary | Always |
| Scenario Python source | Loaded locally; provider may **transmit** bundle, scenario repo stays on DSP |
| Reporting | Always |
| Target discovery policy | Target Provider on DSP Host |

---

## 4. What Remains Inside Scenarios

시나리오 플러그인(`scenarios/<id>/`)은 **execution-agnostic** 계약을 유지한다.

### Scenarios OWN

| Responsibility | Detail |
|----------------|--------|
| `prepare()` | Preconditions, config, non-traffic meta events |
| `execute()` | Protocol pattern — what packets/requests to send |
| `summarize()` | Event Store query for human metrics |
| `executor.py` | Protocol encode/decode, FQDN/URL generation |
| Event types | `query_sent`, `http_request_sent`, `auth_attempted`, … |
| manifest.validation | Threshold declarations |

### Scenarios MUST NOT contain

| Forbidden | Belongs to |
|-----------|------------|
| Webshell upload/bootstrap | WebshellExecutionProvider |
| SSH connect/session mgmt for execution transport | SSHExecutionProvider |
| Agent beacon/task API | AgentExecutionProvider |
| `if provider == "webshell"` branches | Execution Provider injection |
| Remote event schema variants | Event Store bridge |
| Validation thresholds per execution mode | Single manifest block for all modes |

### Scenario code mental model

> "I generate this traffic pattern and record these events. **How** my socket calls reach the wire is not my concern."

Provider may inject:

- Transport handle (local socket vs remote proxy)
- ExecutionContext metadata (for optional evidence fields)

---

## 5. What Belongs to Execution Providers

| Provider responsibility | Detail |
|------------------------|--------|
| Execution mode selection | Mode A vs Mode B for this run |
| Transport establishment | SSH session, webshell HTTP, agent channel |
| Remote executor dispatch | Stage + invoke scenario executor on remote |
| Event sync bridge | Remote buffer → `ctx.event_store.append()` |
| Capability matrix | `supports_scenario()` — e.g. webshell + raw UDP |
| Execution meta events | `execution_prepared`, `execution_sync_failed`, … |
| Teardown / cleanup | Session close, stub removal (policy-dependent) |
| Safety preflight | Remote host in lab allowlist, opt-in flags |

### Provider MUST NOT

| Forbidden | Reason |
|-----------|--------|
| Return validation decision | Validation Engine only |
| Parse stdout for success | ADR 0004 |
| Modify validation thresholds | manifest-only |
| Fork Event schema | Path equality |
| Embed scenario-specific protocol logic | Scenario plugin owns protocol |

---

## 6. How Event Store Remains Authoritative

### 6.1 Single SOT invariant (ADR 0002)

```
All traffic validation reads ONE Event Store on DSP Host.
```

Remote execution does not create a second validation path.

### 6.2 Event flow

```
[Remote host]  scenario executor appends to local buffer
       │
       │  provider.sync_events()
       ▼
[DSP Host]  EventStore.append(event)   ← same Event type, same fields
       │
       ▼
ValidationEngine.aggregate(run_id, scenario, metrics)
```

### 6.3 Schema parity

| Field | Local | Remote (after sync) |
|-------|-------|---------------------|
| `run_id` | ✓ | ✓ identical |
| `scenario` | ✓ | ✓ identical |
| `event` | ✓ | ✓ identical |
| `status` | ✓ | ✓ identical |
| `artifact` | ✓ | ✓ identical |
| `evidence` | ✓ | ✓ + optional provider metadata |

No `remote_*` event types for traffic. Meta events use `event: execution_*` namespace.

### 6.4 Sync failure semantics

| Condition | Event Store state | Traffic validation |
|-----------|-------------------|-------------------|
| Full sync success | Traffic events present | Normal threshold check |
| Partial sync | Some traffic events | Threshold on received count |
| Zero traffic events synced | Meta `execution_sync_failed` only | `failed` / `SOT_EMPTY_AFTER_EXECUTE` |
| Transport failed before execute | Meta `execution_transport_failed` | No traffic → `failed` or `skipped` |

Provider failure is recorded as meta events; **validation logic unchanged**.

---

## 7. How Validation Remains Unchanged

### 7.1 Validation Engine inputs

```
BEFORE Execution Provider:  EventStore + manifest.validation
AFTER  Execution Provider:  EventStore + manifest.validation   (identical)
```

No new parameters. No `execution_provider_id` in validate().

### 7.2 Threshold source

Single `manifest.validation` block per scenario — **not** per provider.

`dns_tunnel` success = `query_sent >= 1` whether local or webshell.

### 7.3 Fail-fast invariants

Existing codes apply unchanged:

- `SOT_EMPTY_AFTER_EXECUTE`
- `SOT_SENT_WITHOUT_ARTIFACT`
- `COUNTER_IMPOSSIBLE`
- `STDOUT_ONLY_REJECTED`

No provider-specific fail-fast codes in Validation Engine (provider errors → meta events + natural traffic failure).

### 7.4 Path equality

```
Execution Path = Validation Path = Reporting Path
```

Remote run test equivalence:

1. Run scenario via mocked remote provider
2. Events synced to Event Store
3. `validate(run_id)` — same function as local run
4. Report — same ValidationResult source

---

## 8. How Reporting Remains Unchanged

### 8.1 Primary table (unchanged)

Traffic validation table sourced from **ValidationResult only** — same columns, same rules.

### 8.2 Optional run metadata (additive)

Report header MAY include (informational, not decision):

```yaml
execution:
  mode: remote | local
  provider_id: webshell
  traffic_origin_host: 10.10.10.50
```

### 8.3 Forbidden reporting changes

| Forbidden | Reason |
|-----------|--------|
| Different success criteria for remote | Validation owns decision |
| stdout section as primary evidence | ADR 0004 |
| Provider health = scenario success | Orthogonal concerns |

---

## 9. Target Provider vs Execution Provider

| Dimension | Target Provider | Execution Provider |
|-----------|-----------------|-------------------|
| Question | Where does traffic **go**? | Where does traffic **originate**? |
| Example | DNS resolver 10.10.10.1 | Victim host 10.10.10.50 |
| Consumed by | Scenario (TargetSet) | Scenario Engine (via provider) |
| Mode A | Required | LocalExecutionProvider |
| Mode B | Required | Remote provider |

Both may reference same lab inventory with different roles (target endpoint vs execution host).

---

## 10. Compatibility Matrix (Conceptual)

| Scenario | Local | Webshell | Agent | SSH |
|----------|-------|----------|-------|-----|
| dns_tunnel | ✓ | △ relay | ✓ | ✓ |
| dga | ✓ | △ relay | ✓ | ✓ |
| http_followup | ✓ | ✓ | ✓ | ✓ |
| ssh_failure | ✓ | ✗ | ✓ | ✓ |
| sql_injection | ✓ | ✓ | ✓ | ✓ |

△ = provider documents limitation; `supports_scenario()` may return False without scenario change.

---

## 11. Implementation Gate Checklist

구현 Phase X 착수 전 확인:

- [ ] ADR 0006 Accepted
- [ ] EXECUTION_MODEL_SPEC.md reviewed
- [ ] EXECUTION_PROVIDER_SPEC.md reviewed
- [ ] No scenario modified for provider framework
- [ ] Event Store schema freeze respected
- [ ] Path equality test plan documented
- [ ] Safety envelope for remote providers documented

---

## 12. Related Documents

- [ADR 0006 — Execution Provider Architecture](../adr/0006-execution-provider-architecture.md)
- [EXECUTION_MODEL_SPEC.md](./EXECUTION_MODEL_SPEC.md)
- [EXECUTION_PROVIDER_SPEC.md](../../EXECUTION_PROVIDER_SPEC.md)
- [ARCHITECTURE_SPEC.md](../../ARCHITECTURE_SPEC.md)
- [SCENARIO_FRAMEWORK_SPEC.md](../../SCENARIO_FRAMEWORK_SPEC.md)
- [EVENT_STORE_SPEC.md](../../EVENT_STORE_SPEC.md)
- [ADR 0002 — Event Store as SOT](../adr/0002-event-store-as-sot.md)
- [ADR 0004 — No stdout Validation](../adr/0004-no-stdout-validation.md)
