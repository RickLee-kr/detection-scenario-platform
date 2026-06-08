# Event Bundle Wiring — Architecture Spec

**문서 버전:** 1.0.0  
**상태:** Phase X+6 — event bundle transfer (no command execution)  
**Date:** 2026-06-06

---

## 1. Purpose

Phase X+6는 `TransportBackedRuntime`에 **event bundle transfer boundary**를 추가한다. X+5에서 artifact transfer(`send_upload` / `download`)가 구현되었다. 이번 단계는 `transport.download()`로 remote bundle을 수신하고 `EventSyncBridge.sync_bundle()`을 통해 Event Store에 append한다. **명령 실행·RunManager·Scenario·Validation·Reporting 통합은 하지 않는다**.

---

## 2. Event Bundle Download Flow

```
RuntimeSession (CONNECTED)
    ↓
download_event_bundle(session, bundle_ref)
    ↓ validate CONNECTED state
transport.download(request, remote_path=bundle_ref.remote_path)
    ↓ receive bundle bytes
write temp .jsonl path (bridge input only — no parsing in Runtime)
    ↓
event_sync_bridge.sync_bundle(bundle_path, event_store)
    ↓ validate + append (existing bridge logic)
Event Store
    ↓
RuntimeBundleReference (sync_status=synced, sync_metadata populated)
```

---

## 3. Runtime Constructor

```python
TransportBackedRuntime(
    transport,
    event_sync_bridge=None,
    event_store=None,
    ...
)
```

Dependencies are injected. No globals. No service locator.

`download_event_bundle()` requires both `event_sync_bridge` and `event_store`; otherwise `RuntimeCapabilityError`.

---

## 4. Runtime State Requirements

| Operation | Required State | Error |
|-----------|----------------|-------|
| `download_event_bundle()` | CONNECTED | `TransportStateError` |
| Missing bridge/store | — | `RuntimeCapabilityError` |

---

## 5. Transport Boundaries

### Allowed

| Runtime Method | Transport Call |
|----------------|----------------|
| `connect()` | `healthcheck()` |
| `healthcheck()` | `healthcheck()` |
| `upload_artifact()` | `send_upload()` |
| `download_artifact()` | `download()` |
| `download_event_bundle()` | `download()` |

### Forbidden

| Transport Method | Status |
|------------------|--------|
| `send_get()` | Never called |
| `send_post()` | Never called |

---

## 6. EventSync Boundaries

### Allowed

| Runtime Method | Bridge Call |
|----------------|-------------|
| `download_event_bundle()` | `sync_bundle(bundle_path, event_store)` |

### Forbidden in Runtime

| Responsibility | Owner |
|----------------|-------|
| Bundle parsing | EventSyncBridge |
| Event validation | EventSyncBridge |
| Event import / append | EventSyncBridge |

Runtime must **not** call `event_store.append()` directly.

---

## 7. Event Store Access Path

```
Runtime
    ↓ (delegates)
EventSyncBridge.sync_bundle()
    ↓ (only valid path)
Event Store.append()
```

**Forbidden:**

```
Runtime → Event Store   (direct append, SQL, repository)
```

Event Store remains the **only source of truth**. Events enter only through EventSyncBridge.

---

## 8. Failure Handling

| Condition | Exception |
|-----------|-----------|
| Session not CONNECTED | `TransportStateError` |
| Missing bridge or store | `RuntimeCapabilityError` |
| Transport timeout | `TransportConnectionError` |
| Transport error / rejected response | `TransportCapabilityError` |
| Event sync failure (`EventSyncError`) | `BundleDownloadError` |

No generic `Exception` swallowing.

---

## 9. RuntimeBundleReference Extensions

Backward-compatible fields added:

| Field | Description |
|-------|-------------|
| `sync_status` | e.g. `synced` |
| `sync_metadata` | `imported_count`, `skipped_count`, `bundle_metadata`, `transport_metadata` |

Existing fields (`bundle_id`, `remote_path`, `event_count`, `created_at`) unchanged.

---

## 10. Future Command Execution Separation

```
Phase X+5  Artifact transfer — send_upload / download
     ↓
Phase X+6  Event bundle wiring (this document) — download → EventSyncBridge
     ↓
Phase X+7  Command execution — send_get / send_post (events → Event Store)
     ↓
Phase X+8  RunManager orchestration
```

Command execution remains intentionally absent. Bundle import does not imply webshell command semantics.

---

## 11. RunManager and Scenario Isolation

| Principle | Phase X+6 Status |
|-----------|------------------|
| Event Store = Only Source Of Truth | Preserved — append only via EventSyncBridge |
| Execution = Validation = Reporting | Unchanged — no validation/reporting integration |
| RunManager / Scenario / Validation / Reporting / Detection | Not integrated |

---

## 12. Confirmation Checklist

- [x] `download_event_bundle()` implemented
- [x] `transport.download()` used for bundle bytes
- [x] `EventSyncBridge.sync_bundle()` used for import
- [x] Runtime never writes Event Store directly
- [x] CONNECTED state enforced
- [x] `send_get` / `send_post` still unused
- [x] Artifact transfer still works
- [x] Command execution does not exist in this phase
