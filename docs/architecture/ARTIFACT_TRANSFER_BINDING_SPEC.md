# Artifact Transfer Binding — Architecture Spec

**문서 버전:** 1.0.0  
**상태:** Phase X+5 — artifact transfer (no command execution)  
**Date:** 2026-06-06

---

## 1. Purpose

Phase X+5는 `TransportBackedRuntime`에 **artifact transfer boundary**를 추가한다. X+4에서 `upload_artifact()` / `download_artifact()`는 `RuntimeCapabilityError`만 반환했다. 이번 단계는 `transport.send_upload()`와 `transport.download()`를 사용하되, **명령 실행·EventSyncBridge·Event Store 접근은 하지 않는다**.

---

## 2. Upload Flow

```
RuntimeSession (CONNECTED)
    ↓
upload_artifact(session, artifact)
    ↓ validate CONNECTED state
transport.send_upload(request, local_path, remote_path)
    ↓
RuntimeArtifact (transfer_status=uploaded, transfer_metadata from response)
```

---

## 3. Download Flow

```
RuntimeSession (CONNECTED)
    ↓
download_artifact(session, artifact)
    ↓ validate CONNECTED state
transport.download(request, remote_path=artifact.remote_path)
    ↓
RuntimeArtifact (transfer_status=downloaded, size_bytes=len(body))
```

---

## 4. Runtime State Requirements

| Operation | Required State | Error |
|-----------|----------------|-------|
| `upload_artifact()` | CONNECTED | `TransportStateError` |
| `download_artifact()` | CONNECTED | `TransportStateError` |
| `download_event_bundle()` | — | Still `RuntimeCapabilityError` |

---

## 5. Transport Boundaries

### Allowed

| Runtime Method | Transport Call |
|----------------|----------------|
| `connect()` | `healthcheck()` |
| `healthcheck()` | `healthcheck()` |
| `upload_artifact()` | `send_upload()` |
| `download_artifact()` | `download()` |

### Forbidden

| Transport Method | Status |
|------------------|--------|
| `send_get()` | Never called |
| `send_post()` | Never called |

---

## 6. Failure Handling

| Condition | Exception |
|-----------|-----------|
| Session not CONNECTED | `TransportStateError` |
| Transport timeout | `TransportConnectionError` |
| Transport error / rejected response | `TransportCapabilityError` |
| Event bundle (unchanged) | `RuntimeCapabilityError` |

No generic `Exception` swallowing.

---

## 7. RuntimeArtifact Extensions

Backward-compatible fields added:

| Field | Description |
|-------|-------------|
| `transfer_status` | e.g. `uploaded`, `downloaded` |
| `created_at` | Transfer timestamp |
| `transfer_metadata` | Transport response metadata |

---

## 8. Future Command Execution Separation

```
Phase X+5  Artifact transfer (this document) — send_upload / download
     ↓
Phase X+6  EventSyncBridge wiring — download_event_bundle()
     ↓
Phase X+7  Command execution — send_get / send_post (events → Event Store)
     ↓
Phase X+8  RunManager orchestration
```

Command execution remains intentionally absent. File transfer does not imply webshell command semantics.

---

## 9. Event Store and RunManager Isolation

| Principle | Phase X+5 Status |
|-----------|------------------|
| Event Store = Only Source Of Truth | Unchanged — no Event Store writes |
| EventSyncBridge | Untouched |
| RunManager / Scenario / Validation / Reporting | Not integrated |
| Provider family / Factory / Registry | Unchanged |

---

## 10. Mock Transport Compatibility

All tests use `MockHttpTransport` modes: `SUCCESS`, `TIMEOUT`, `AUTH_FAILURE`, `HTTP_5XX`. No real network I/O.
