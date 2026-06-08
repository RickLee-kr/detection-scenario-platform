# Webshell Contract — Architecture Review

**문서 버전:** 1.0.0  
**상태:** Phase X+1A review  
**Date:** 2026-06-06

---

## 1. Review Scope

Phase X+1A delivers `dsp/execution/webshell/` contract package only. This review verifies **no unintended coupling** to scenarios, RunManager, Event Store, Validation, or Reporting.

---

## 2. Findings Summary

| Check | Result | Notes |
|-------|--------|-------|
| Scenario imports webshell | **PASS** | Zero matches in `scenarios/` |
| RunManager dependency | **PASS** | RunManager imports `dsp.execution` only — not `webshell` |
| Event Store dependency | **PASS** | `webshell/` has no `event_store` imports |
| Validation dependency | **PASS** | No `validation` imports |
| Reporting dependency | **PASS** | No `reporting` imports |
| Factory enables webshell | **PASS** | `create_execution_provider("webshell")` still raises `NotImplementedError` |
| LocalExecutionProvider default | **PASS** | Unchanged |
| Runtime behavior change | **PASS** | No RunManager or orchestrator changes |

**Verdict:** Phase X+1A is framework-ready with zero runtime integration.

---

## 3. Import Boundary Analysis

### 3.1 Scenarios (`scenarios/`)

```
grep "webshell|dsp.execution" scenarios/ → No matches
```

All nine implemented scenarios remain execution-agnostic. No scenario module references webshell contract.

### 3.2 RunManager (`dsp/runner/run_manager.py`)

```python
from dsp.execution import ExecutionContext, create_execution_provider
```

RunManager uses Execution Provider Framework only. Webshell contract is not imported or wired.

### 3.3 Execution Provider Factory (`dsp/execution/factory.py`)

```python
FUTURE_PROVIDERS = frozenset({"webshell", "ssh", "agent"})
```

`webshell` remains in `FUTURE_PROVIDERS` — factory raises `NotImplementedError`. No change in X+1A.

### 3.4 Webshell Package Dependencies

`dsp/execution/webshell/` imports only:

| Module | Imports from |
|--------|--------------|
| `contract.py` | `webshell.models` |
| `models.py` | `webshell.capabilities` |
| `security.py` | `webshell.exceptions` |
| `capabilities.py` | stdlib only |
| `exceptions.py` | stdlib only |

**No imports from:** `event_store`, `validation`, `reporting`, `engine`, `runner`, `scenarios`.

---

## 4. Dependency Graph (X+1A)

```
dsp/execution/webshell/
  └── (self-contained)

dsp/runner/run_manager.py
  └── dsp/execution/  (unchanged)

scenarios/*
  └── dsp.engine, dsp.event_store, dsp.protocols  (unchanged)
```

Webshell contract is an **isolated leaf** injectable in Phase X+1D without scenario modifications.

---

## 5. Test Coverage (X+1A)

| Test file | Coverage |
|-----------|----------|
| `test_contract.py` | ABC abstract, stub implementation |
| `test_models.py` | Serialization roundtrips |
| `test_capabilities.py` | Capability declarations |
| `test_security.py` | Policy validation helpers |
| `test_exceptions.py` | Exception hierarchy |

No RunManager integration tests added — intentional for X+1A.

---

## 6. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Premature factory wiring | Factory unchanged; webshell still `NotImplementedError` |
| Scenario leak via executor | Scenarios never import webshell; enforced by review + CI grep |
| Security helpers mistaken for enforcement | Documented as validation-only in X+1A; wired in X+1B |
| Contract drift from architecture doc | `WEBSHELL_CONTRACT_SPEC.md` aligned with implementation |

---

## 7. Next Phase Gate (X+1B)

Before transport implementation:

1. Re-run this review after factory/RunManager changes
2. Confirm path equality test plan for event sync (X+1C)
3. Golden-file fixtures for family response parsing

---

## 8. Related Documents

- [WEBSHELL_CONTRACT_SPEC.md](./WEBSHELL_CONTRACT_SPEC.md)
- [WEBSHELL_PROVIDER_ARCHITECTURE.md](./WEBSHELL_PROVIDER_ARCHITECTURE.md)
- [WEBSHELL_PROVIDER_IMPLEMENTATION_PLAN.md](./WEBSHELL_PROVIDER_IMPLEMENTATION_PLAN.md)
