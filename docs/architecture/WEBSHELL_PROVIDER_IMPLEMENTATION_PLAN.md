# Webshell Execution Provider — Implementation Plan

**문서 버전:** 1.0.0  
**상태:** Planning only — no code  
**Date:** 2026-06-06

---

## 1. Purpose

WebshellExecutionProvider 구현 roadmap. **No code in this phase** — sub-phase별 deliverable, acceptance criteria, dependency만 정의.

---

## 2. Phase Overview

```
Phase X+1A  Webshell Contract
     ↓
Phase X+1B  Transport Layer
     ↓
Phase X+1C  Event Synchronization
     ↓
Phase X+1D  JSP Reference Provider
     ↓
Phase X+1E  PHP/ASPX Expansion
```

| Phase | Scope | Runtime impact |
|-------|-------|----------------|
| X+1A | Contract models, exceptions, config validation | None on scenarios |
| X+1B | HTTP transport, family adapters (skeleton) | None on scenarios |
| X+1C | Remote stub, EventSyncBridge | None on scenarios |
| X+1D | End-to-end JSP reference | Factory enables `webshell` |
| X+1E | PHP, ASPX, Generic adapters | Expanded family support |

---

## 3. Phase X+1A — Webshell Contract

### Deliverables

| Item | Location (planned) |
|------|-------------------|
| `WebshellContract` Protocol | `dsp/execution/webshell/contract.py` |
| Result dataclasses | `dsp/execution/webshell/models.py` |
| `WebshellProviderConfig` | `dsp/execution/webshell/config.py` |
| Exceptions | `dsp/execution/webshell/exceptions.py` |
| ExecutionContext extensions | Extend `dsp/execution/models.py` |
| Unit tests | `tests/execution/webshell/test_contract.py`, `test_config.py` |

### Acceptance Criteria

- [ ] Contract interface documented and type-checked (Protocol)
- [ ] `WebshellProviderConfig` validates required fields (`webshell_url`, `authentication_mode`)
- [ ] No changes to scenarios, Event Store, Validation, Reporting
- [ ] Factory still returns `NotImplementedError` for `"webshell"`

### Dependencies

- Execution Provider Framework (Phase X) — complete

---

## 4. Phase X+1B — Transport Layer

### Deliverables

| Item | Description |
|------|-------------|
| `HttpTransport` | GET/POST/multipart/chunked HTTP client |
| `RetryPolicy` | Configurable backoff, 5xx/429 handling |
| `TimeoutTier` | healthcheck / quick / normal / long |
| `ResponseNormalizer` | Base class for family adapters |
| Family adapter skeletons | JSP, PHP, ASPX, Generic — healthcheck + execute only |
| Golden-file fixtures | Sample responses per family in `tests/fixtures/webshell/` |
| Unit tests | `tests/execution/webshell/test_transport.py`, `test_*_adapter.py` |

### Acceptance Criteria

- [ ] `healthcheck()` detects family against fixture responses
- [ ] `execute()` returns normalized stdout/stderr with exit code marker
- [ ] `upload()` / `download()` work against mock HTTP server
- [ ] Chunked upload handles payloads > 64 KB
- [ ] Retry policy respects max attempts
- [ ] No scenario or Event Store changes

### Dependencies

- Phase X+1A complete

---

## 5. Phase X+1C — Event Synchronization

### Deliverables

| Item | Description |
|------|-------------|
| `RemoteExecutorStub` spec | Bundle layout, env vars, event buffer path |
| `StubPackager` | DSP-side: pack executor.py + manifest for upload |
| `EventSyncBridge` | Download JSONL → schema validate → append |
| `BundleValidator` | Line-by-line Event schema check, reject invalid |
| Meta events | `execution_sync_completed`, `execution_sync_failed`, `execution_sync_partial` |
| Integration tests | Mock remote bundle → local EventStore import |
| Path equality tests | Same events local vs imported → identical validation |

### Acceptance Criteria

- [ ] Option C sync model implemented
- [ ] Invalid JSONL lines skipped with audit; valid lines appended
- [ ] Duplicate event IDs rejected
- [ ] Partial sync recorded in meta event
- [ ] ValidationEngine produces identical results for equivalent local/remote event sets
- [ ] No Event Store schema changes

### Dependencies

- Phase X+1B complete (upload/download required)

---

## 6. Phase X+1D — JSP Reference Provider

### Deliverables

| Item | Description |
|------|-------------|
| `WebshellExecutionProvider` | Implements `ExecutionProvider` |
| `JspFamilyAdapter` | Full WebshellContract for JSP |
| `WebshellExecutionProvider.prepare/execute/cleanup` | Full lifecycle |
| Factory registration | `create_execution_provider("webshell")` enabled |
| CLI flags (optional) | `--execution-provider webshell`, `--webshell-url` |
| E2E test | dummy scenario via webshell against lab JSP (or mock) |
| Path equality E2E | dummy local vs webshell → same validation decision |

### Acceptance Criteria

- [ ] `create_execution_provider("webshell")` returns provider
- [ ] dummy scenario dry-run via mock webshell: validation success
- [ ] Artifacts: events.db, validation.json, report.md generated
- [ ] No scenario code modified
- [ ] LocalExecutionProvider remains default
- [ ] Security allowlist enforced (forbidden commands rejected)

### Dependencies

- Phase X+1C complete
- Lab JSP webshell or HTTP mock server

---

## 7. Phase X+1E — PHP/ASPX Expansion

### Deliverables

| Item | Description |
|------|-------------|
| `PhpFamilyAdapter` | Full WebshellContract |
| `AspxFamilyAdapter` | Full WebshellContract |
| `GenericFamilyAdapter` | Configurable parameter mapping |
| Family auto-detection refinement | Healthcheck probes |
| Scenario capability matrix tests | Per scenario × family skip/support |
| Risk mitigation tests | disable_functions, HTML wrapping, AMSI simulation |
| Documentation update | Operator runbook for multi-family lab |

### Acceptance Criteria

- [ ] http_followup E2E via PHP webshell (lab or mock)
- [ ] `supports_scenario()` correctly skips unsupported pairs
- [ ] Golden-file tests pass for all four families
- [ ] WEBSHELL_PROVIDER_RISK_ANALYSIS mitigations verified where testable
- [ ] No regression in local execution (all existing tests pass)

### Dependencies

- Phase X+1D complete
- Lab PHP and ASPX instances (or mocks)

---

## 8. Testing Strategy (Cross-Phase)

| Test type | Phase | Purpose |
|-----------|-------|---------|
| Contract unit tests | X+1A | Interface compliance |
| Transport unit tests | X+1B | HTTP edge cases |
| Sync integration tests | X+1C | Event import parity |
| JSP E2E | X+1D | End-to-end reference |
| Family matrix E2E | X+1E | Multi-family coverage |
| Path equality | X+1C+ | local ≡ webshell validation/report |

### Path Equality Test Pattern

```
1. Run scenario locally (dry_run or lab) → baseline artifacts
2. Run same scenario via webshell mock with identical event bundle
3. Assert validation.json decisions match
4. Assert report.md metrics match
5. Assert Event Store event counts match per scenario_id
```

---

## 9. Out of Scope (All Phases)

| Item | Reason |
|------|--------|
| SSH Execution Provider | Separate roadmap |
| Agent Execution Provider | Separate roadmap |
| Scenario code changes | Execution-agnostic invariant |
| Event Store schema changes | ADR 0002 |
| Validation threshold changes | Path equality |
| Production webshell deployment | Lab-only scope |
| WAF bypass research | Operator responsibility |

---

## 10. Estimated Sequencing

| Phase | Depends on | Suggested gate |
|-------|------------|----------------|
| X+1A | Phase X | Contract review |
| X+1B | X+1A | Transport mock tests green |
| X+1C | X+1B | Path equality unit tests green |
| X+1D | X+1C | JSP E2E + dummy parity |
| X+1E | X+1D | Multi-family matrix |

Phase numbers (X+1A–E) are placeholders — assign in [PHASE_ROADMAP.md](../../PHASE_ROADMAP.md) when scheduling.

---

## 11. Related Documents

- [WEBSHELL_PROVIDER_ARCHITECTURE.md](./WEBSHELL_PROVIDER_ARCHITECTURE.md)
- [WEBSHELL_PROVIDER_RISK_ANALYSIS.md](./WEBSHELL_PROVIDER_RISK_ANALYSIS.md)
- [EXECUTION_PROVIDER_FRAMEWORK.md](./EXECUTION_PROVIDER_FRAMEWORK.md)
- [ADR 0007 — Webshell Execution Provider Architecture](../adr/0007-webshell-execution-provider-architecture.md)
