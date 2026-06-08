# Generic Webshell Provider — Architecture Spec

**문서 버전:** 1.0.0  
**상태:** Phase X+1G — refactoring (no execution)  
**Date:** 2026-06-06

---

## 1. Purpose

Phase X+1G는 JSP(X+1E)와 PHP(X+1F) adapter에 중복된 mock-first 로직을 **GenericWebshellProvider**로 추출한다. ASPX 추가 전에 공통 기반을 확립하여 family adapter당 identity/session class만 선언하면 되도록 한다.

**Refactoring 원칙:** 동작 변경 없음. 실행·네트워크·transport·EventSync 기능 추가 없음.

---

## 2. Provider Inheritance Hierarchy

```
WebshellProviderBase (abstract skeleton)
    ↓
GenericWebshellProvider (shared mock-first adapter)
    ↓
├── JspWebshellProvider   (provider_type, provider_name, session_class only)
├── PhpWebshellProvider   (provider_type, provider_name, session_class only)
└── AspxWebshellProvider  (future — same pattern)
```

Session hierarchy:

```
ProviderSession
    ↓
GenericWebshellSession (webshell_url, transport_type, provider_version)
    ↓
├── JspProviderSession
├── PhpProviderSession
└── AspxProviderSession (future)
```

---

## 3. GenericWebshellProvider Responsibilities

| Responsibility | Location |
|----------------|----------|
| Configuration validation | `generic_provider.py` |
| Capability declaration (intent only) | `generic_provider.py` |
| Session creation via `session_class` | `generic_provider.py` |
| Transport reference storage | `generic_provider.py` |
| Metadata with `provider_version` | `generic_provider.py` |

**Explicitly forbidden (unchanged):**

- `execute()`, `upload()`, `download()`, `cleanup()`, `healthcheck()`
- Transport invocation
- EventSyncBridge invocation
- RunManager / Scenario / Validation / Reporting integration

---

## 4. JSP/PHP Specialization Model

Family adapters declare **only** class attributes:

| Class | `provider_type` | `provider_name` | `session_class` |
|-------|-----------------|-----------------|-----------------|
| `JspWebshellProvider` | `"jsp"` | JSP Webshell Provider | `JspProviderSession` |
| `PhpWebshellProvider` | `"php"` | PHP Webshell Provider | `PhpProviderSession` |

No duplicated validation, capability, or session-creation logic in family files.

---

## 5. Future ASPX Integration

ASPX adapter (future phase) requires only:

```python
class AspxWebshellProvider(GenericWebshellProvider):
    provider_type = "aspx"
    provider_name = "ASPX Webshell Provider"
    session_class = AspxProviderSession
    provider_version = ASPX_PROVIDER_VERSION
```

Plus `AspxProviderSession(GenericWebshellSession)` with ASPX-specific defaults in `new()` / `from_dict()`.

Factory update: add `"aspx"` to `_IMPLEMENTED_PROVIDER_TYPES` and factory branch.

**Phase X+1G does NOT implement AspxWebshellProvider.**

---

## 6. Refactoring Rationale

| Before (X+1E/F) | After (X+1G) |
|-----------------|--------------|
| ~110 lines × 2 providers (duplicate) | ~20 lines × 2 family stubs + ~100 lines shared |
| Validation copied per family | Single `validate_configuration()` |
| Capabilities copied per family | Single `get_capabilities()` |
| Session creation copied per family | Single `create_session()` via `session_class` |

Duplication reduction enables consistent behavior across JSP/PHP/future ASPX without copy-paste maintenance.

---

## 7. Adapter Boundaries

| Layer | Boundary |
|-------|----------|
| `GenericWebshellProvider` | Metadata, validation, session declaration |
| `WebshellTransport` | HTTP mechanics (never invoked in mock-first phase) |
| `WebshellContract` | Future binding between provider and transport |
| `EventSyncBridge` | Future remote event collection → Event Store |

Provider stores transport reference only. Event Store remains the sole source of truth — no events produced at this layer.

---

## 8. Factory and Registry (Unchanged Behavior)

| Entry point | Behavior |
|-------------|----------|
| `create_webshell_provider("jsp")` | `JspWebshellProvider` |
| `create_webshell_provider("php")` | `PhpWebshellProvider` |
| `create_webshell_provider("aspx")` | `NotImplementedError` |
| `registry.register_provider(...)` | Manual registration only |

---

## 9. Package Layout

```
dsp/execution/providers/webshell/common/
├── __init__.py
├── generic_provider.py      # GenericWebshellProvider
├── generic_models.py        # GenericWebshellSession
└── generic_exceptions.py    # GenericWebshellProviderError

dsp/execution/providers/webshell/jsp/
├── provider.py              # JspWebshellProvider (thin specialization)
└── jsp_models.py            # JspProviderSession extends GenericWebshellSession

dsp/execution/providers/webshell/php/
├── provider.py              # PhpWebshellProvider (thin specialization)
└── php_models.py            # PhpProviderSession extends GenericWebshellSession
```

---

## 10. Event Store and RunManager Isolation

| Principle | Phase X+1G Status |
|-----------|-------------------|
| Event Store = Only Source Of Truth | Unchanged |
| RunManager isolation | No RunManager imports or hooks |
| Execution = Validation = Reporting | Preserved — no execution added |
| Scenario = Execution Agnostic | Preserved |

---

## 11. Future Roadmap

```
Phase X+1G  Generic Webshell Provider (this document) — refactoring
     ↓
Phase X+1H  ASPX Provider Adapter — mock-first (thin specialization)
     ↓
Phase X+1I  Contract Binding
     ↓
Phase X+1J  EventSyncBridge Wiring
     ↓
Phase X+1K  RunManager Integration
```
