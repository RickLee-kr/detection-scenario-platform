# Provider Runtime Contract — Architecture Spec

**문서 버전:** 1.0.0  
**상태:** Phase X+2 — contract definition (no execution)  
**Date:** 2026-06-06

---

## 1. Purpose

Phase X+2는 **Provider Runtime Contract**를 정의한다. JSP/PHP/ASPX provider family(Phase X+1)는 metadata, validation, session declaration만 가능했다. Runtime lifecycle API(`connect`, `upload_artifact`, `download_event_bundle` 등)는 존재하지 않았다.

이번 단계는 **Contract Definition Phase**이다:

- API surface 정의
- Runtime data models 정의
- Exception hierarchy 정의
- Runtime capability defaults (all `False`)

**실행·네트워크·transport·EventSync 호출 없음.**

---

## 2. Why Runtime Contract Exists

| Problem (X+1) | Solution (X+2) |
|---------------|----------------|
| Provider family exists but no lifecycle API | `ProviderRuntimeContract` defines standard methods |
| No shared runtime session model | `RuntimeSession` with explicit states |
| No artifact/bundle metadata types | `RuntimeArtifact`, `RuntimeBundleReference` |
| No runtime capability matrix | `RuntimeCapabilities` (defaults `False`) |

Provider family = **identity**. Runtime contract = **lifecycle API**. Future implementations will satisfy the contract without changing scenario or validation layers.

---

## 3. ProviderRuntimeContract Methods

| Method | Purpose | Phase X+2 Status |
|--------|---------|------------------|
| `connect()` | Establish runtime connection | Abstract — no impl |
| `disconnect()` | Tear down connection | Abstract — no impl |
| `create_remote_session()` | Create remote session | Abstract — no impl |
| `close_remote_session()` | Close remote session | Abstract — no impl |
| `upload_artifact()` | Upload artifact | Abstract — no impl |
| `download_artifact()` | Download artifact | Abstract — no impl |
| `download_event_bundle()` | Download event bundle ref | Abstract — no impl |
| `healthcheck()` | Verify reachability | Abstract — no impl |
| `cleanup()` | Release resources | Abstract — no impl |

All methods are `@abstractmethod` on `ProviderRuntimeContract`. Instantiating the ABC raises `TypeError`.

---

## 4. Runtime State Model

`RuntimeSessionState`:

| State | Description |
|-------|-------------|
| `CREATED` | Session record created (metadata only) |
| `CONNECTING` | Connection in progress (future) |
| `CONNECTED` | Active remote session (future) |
| `DISCONNECTED` | Connection torn down |
| `ERROR` | Error state |
| `CLOSED` | Session closed |

`RuntimeSession` fields: `session_id`, `provider_type`, `created_at`, `state`, `remote_identifier`.

---

## 5. Relationship to Provider Family

```
WebshellProviderBase / GenericWebshellProvider
    • metadata, validation, session declaration (X+1)
    • get_runtime_capabilities() → all False (X+2)

ProviderRuntimeContract (separate ABC)
    • connect / disconnect / upload / download / healthcheck / cleanup
    • Future: family-specific runtime implementations
```

`GenericWebshellProvider.get_runtime_capabilities()` returns all-`False` `RuntimeCapabilities`. No lifecycle execution. JSP/PHP/ASPX behavior unchanged except this optional exposure.

---

## 6. Relationship to Transport

| Layer | Responsibility |
|-------|----------------|
| `ProviderRuntimeContract` | Lifecycle API definition |
| `WebshellTransport` | HTTP mechanics (GET/POST/upload/download) |
| Future binding | Runtime impl invokes transport behind contract methods |

Transport layer is **not modified** in Phase X+2. Contract does not call transport.

---

## 7. Relationship to EventSyncBridge

| Principle | Phase X+2 |
|-----------|-----------|
| Event Store = Only Source Of Truth | Unchanged |
| Remote events via EventSyncBridge | Future — `download_event_bundle()` will delegate to bridge |
| Contract phase | `RuntimeBundleReference` metadata only; no bridge calls |

---

## 8. Runtime Capabilities

`RuntimeCapabilities` defaults (all `False`):

- `supports_connect`
- `supports_upload`
- `supports_download`
- `supports_event_bundle`
- `supports_healthcheck`
- `supports_cleanup`

Indicates **no runtime implementation** exists yet. Future phases set `True` when contract methods are implemented.

---

## 9. Exception Hierarchy

```
ProviderRuntimeError
├── ConnectionError
├── SessionError
├── ArtifactTransferError
├── BundleDownloadError
├── RuntimeCapabilityError
├── HealthcheckError
└── CleanupError
```

Identity and context fields only — no retry or transport logic.

---

## 10. Why Execution Is Intentionally Absent

1. **Execution = Validation = Reporting** — contract defines API; execution populates Event Store in later phases.
2. **Scenario = Execution Agnostic** — scenarios must not depend on runtime method internals.
3. **Separation of concerns** — define contract before JSP/PHP/ASPX runtime bindings.
4. **Testability** — ABC, models, and capability defaults testable without network.

---

## 11. Future Lifecycle Roadmap

```
Phase X+2  Provider Runtime Contract (this document) — definition only
     ↓
Phase X+3  Runtime Contract Binding (JSP / PHP / ASPX)
     • GenericWebshellProvider implements ProviderRuntimeContract
     • transport behind contract methods (mock-first)
     ↓
Phase X+4  EventSyncBridge Wiring
     • download_event_bundle() → Event Store
     ↓
Phase X+5  RunManager Integration
     • lifecycle orchestration via RunManager
```

---

## 12. Package Layout

```
dsp/execution/providers/runtime/
├── __init__.py
├── runtime_contract.py      # ProviderRuntimeContract (ABC)
├── runtime_models.py        # RuntimeSession, RuntimeArtifact, RuntimeBundleReference
├── runtime_exceptions.py    # ProviderRuntimeError hierarchy
└── runtime_capabilities.py  # RuntimeCapabilities
```

---

## 13. Event Store and RunManager Isolation

| Principle | Phase X+2 Status |
|-----------|------------------|
| Event Store = Only Source Of Truth | Unchanged — no events produced |
| RunManager isolation | No RunManager imports or hooks |
| Factory / Registry | Unchanged behavior |
