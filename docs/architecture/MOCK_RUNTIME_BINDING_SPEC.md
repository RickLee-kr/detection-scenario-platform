# Mock Runtime Binding — Architecture Spec

**문서 버전:** 1.0.0  
**상태:** Phase X+3 — lifecycle simulation (no execution)  
**Date:** 2026-06-06

---

## 1. Purpose

Phase X+3는 **MockProviderRuntime**을 통해 `ProviderRuntimeContract`와 Provider Family를 연결한다. Runtime lifecycle API를 **시뮬레이션**하되, 실제 실행·네트워크·transport·EventSync·Event Store 접근은 하지 않는다.

```
GenericWebshellProvider
    attach_runtime() / get_runtime()
        ↓
MockProviderRuntime (ProviderRuntimeContract)
    deterministic state transitions
    metadata-only artifact/bundle operations
```

---

## 2. Runtime Lifecycle

### State Transition Diagram

```
CREATED
    ↓  connect()
CONNECTING
    ↓
CONNECTED
    ↓  disconnect()
DISCONNECTED
    ↓  close_remote_session()
CLOSED

ERROR — supported via SessionError on invalid transitions
```

| Operation | Valid From | Result State |
|-----------|------------|--------------|
| `create_remote_session()` | — | CREATED |
| `connect()` | CREATED | CONNECTED (via CONNECTING) |
| `disconnect()` | CONNECTED | DISCONNECTED |
| `close_remote_session()` | DISCONNECTED | CLOSED |
| `upload_artifact()` | CONNECTED session | metadata returned |
| `download_artifact()` | CONNECTED session | metadata returned |
| `download_event_bundle()` | CONNECTED session | metadata returned |
| `healthcheck()` | any | `True` |
| `cleanup()` | any | clears sessions |

---

## 3. Mock Failure Modes

`MockRuntimeConfiguration`:

| Flag | Effect |
|------|--------|
| `simulate_connection_failure` | `connect()` → `MockConnectionError` |
| `simulate_upload_failure` | `upload_artifact()` → `MockUploadError` |
| `simulate_download_failure` | `download_artifact()` → `MockDownloadError` |
| `simulate_bundle_failure` | `download_event_bundle()` → `MockBundleError` |

All default `False`. Invalid state transitions raise `SessionError`.

---

## 4. Provider-Runtime Relationship

| Method | Behavior |
|--------|----------|
| `attach_runtime(runtime)` | Store reference only — no auto-connect |
| `get_runtime()` | Return attached runtime or `None` |
| `get_runtime_capabilities()` | All `True` when runtime attached; all `False` otherwise |

JSP/PHP/ASPX family identity unchanged. No auto-creation of runtime.

---

## 5. Why Execution Is Still Absent

1. **Metadata-only operations** — upload/download return `RuntimeArtifact` / `RuntimeBundleReference` records; no filesystem I/O.
2. **No transport** — `MockProviderRuntime` never calls `WebshellTransport`.
3. **No EventSyncBridge** — bundle operations return reference metadata only.
4. **No Event Store** — no event writes or reads.
5. **Execution = Validation = Reporting** — lifecycle simulation enables future binding without breaking platform principles.

---

## 6. Future Transport Integration

```
Phase X+3  MockProviderRuntime (this document) — simulation
     ↓
Phase X+4  Transport-Backed Runtime
     • Real runtime impl invokes WebshellTransport behind contract
     ↓
Phase X+5  EventSyncBridge Wiring
     • download_event_bundle() → Event Store
     ↓
Phase X+6  RunManager Integration
     • lifecycle orchestration
```

---

## 7. Package Layout

```
dsp/execution/providers/runtime/mock/
├── __init__.py
├── mock_runtime.py        # MockProviderRuntime
├── mock_models.py         # MockRuntimeConfiguration
└── mock_exceptions.py     # MockRuntimeError hierarchy
```

---

## 8. Explicitly Forbidden (Phase X+3)

- HTTP requests, transport method calls
- JSP/PHP/ASPX command execution
- EventSyncBridge invocation, Event Store writes
- RunManager / Scenario / Validation / Reporting integration

---

## 9. Event Store and RunManager Isolation

| Principle | Phase X+3 Status |
|-----------|------------------|
| Event Store = Only Source Of Truth | Unchanged — no Event Store access |
| RunManager isolation | No RunManager imports or hooks |
| Factory / Registry | Unchanged behavior |
