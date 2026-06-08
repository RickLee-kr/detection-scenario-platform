# Transport Runtime Skeleton — Architecture Spec

**문서 버전:** 1.0.0  
**상태:** Phase X+4 — transport boundary integration (no execution)  
**Date:** 2026-06-06

---

## 1. Purpose

Phase X+4는 **TransportBackedRuntime**을 통해 Runtime ↔ Transport 경계를 검증한다. Mock runtime(X+3)은 transport 없이 lifecycle을 시뮬레이션했다. 이번 단계는 `transport.healthcheck()`만 허용하여 boundary를 확립하되, **명령 실행·artifact transfer·event bundle·EventSyncBridge 호출은 하지 않는다**.

```
GenericWebshellProvider
    attach_runtime(TransportBackedRuntime)
        ↓
TransportBackedRuntime
    connect() → transport.healthcheck() ONLY
    healthcheck() → transport.healthcheck()
        ↓
WebshellTransport (MockHttpTransport in tests)
```

---

## 2. Runtime State Diagram

```
CREATED
    ↓  create_remote_session()
    ↓  connect() [+ transport.healthcheck() if enabled]
CONNECTING
    ↓  success
CONNECTED
    ↓  failure → ERROR (+ TransportConnectionError)
    ↓  disconnect()
DISCONNECTED
    ↓  close_remote_session()
CLOSED
```

---

## 3. Allowed Transport Calls

| Runtime Method | Transport Call | Condition |
|----------------|----------------|-----------|
| `connect()` | `transport.healthcheck()` | `enable_healthcheck_on_connect=True` (default) |
| `healthcheck()` | `transport.healthcheck()` | Always when invoked |

**Only** `healthcheck()` is permitted. No other transport methods.

---

## 4. Forbidden Transport Calls

| Transport Method | Phase X+4 Status |
|------------------|------------------|
| `send_get()` | Never called |
| `send_post()` | Never called |
| `send_upload()` | Never called |
| `download()` | Never called |

Artifact/bundle operations raise `RuntimeCapabilityError` without transport invocation.

---

## 5. Blocked Runtime Operations

| Method | Behavior |
|--------|----------|
| `upload_artifact()` | `RuntimeCapabilityError`: "Artifact transfer not implemented" |
| `download_artifact()` | `RuntimeCapabilityError`: "Artifact transfer not implemented" |
| `download_event_bundle()` | `RuntimeCapabilityError`: "Event bundle download not implemented" |

No EventSyncBridge. No Event Store access.

---

## 6. Why Command Execution Is Intentionally Absent

1. **Boundary validation first** — prove runtime can delegate healthcheck before HTTP command semantics.
2. **Execution = Validation = Reporting** — command output must flow through Event Store via EventSyncBridge in later phases.
3. **Transport Agnostic** — runtime contract stable; transport mechanics isolated.
4. **Incremental risk** — healthcheck-only reduces accidental webshell execution during skeleton phase.

---

## 7. Configuration

`TransportRuntimeConfiguration`:

| Field | Default | Purpose |
|-------|---------|---------|
| `enable_healthcheck_on_connect` | `True` | Skip healthcheck on connect when `False` (testing/expansion) |

---

## 8. Exception Hierarchy

```
ProviderRuntimeError
└── TransportRuntimeError
    ├── TransportConnectionError
    ├── TransportCapabilityError
    └── TransportStateError
```

Connect healthcheck failure → session `ERROR` + `TransportConnectionError`.

---

## 9. Provider Integration

`GenericWebshellProvider.attach_runtime(TransportBackedRuntime)` — reference storage only. No auto-connect, auto-healthcheck, or runtime creation.

`get_runtime_capabilities()` → all `True` when runtime attached (unchanged from X+3).

---

## 10. Future Execution Roadmap

```
Phase X+4  TransportBackedRuntime skeleton (this document) — healthcheck only
     ↓
Phase X+5  Artifact Transfer Binding
     • upload_artifact / download_artifact via transport
     ↓
Phase X+6  EventSyncBridge Wiring
     • download_event_bundle() → Event Store
     ↓
Phase X+7  Command Execution Binding
     • send_get / send_post behind contract (events → Event Store)
     ↓
Phase X+8  RunManager Integration
```

---

## 11. Package Layout

```
dsp/execution/providers/runtime/transport/
├── __init__.py
├── transport_runtime.py       # TransportBackedRuntime
├── transport_models.py        # TransportRuntimeConfiguration
└── transport_exceptions.py    # TransportRuntimeError hierarchy
```

---

## 12. Event Store and RunManager Isolation

| Principle | Phase X+4 Status |
|-----------|------------------|
| Event Store = Only Source Of Truth | Unchanged — no Event Store access |
| RunManager isolation | No RunManager imports or hooks |
| Factory / Registry / JSP·PHP·ASPX identity | Unchanged |
