# ASPX Provider Adapter — Architecture Spec

**문서 버전:** 1.0.0  
**상태:** Phase X+1H — mock-first adapter (no execution)  
**Date:** 2026-06-06

---

## 1. Purpose

Phase X+1H는 **ASPX Webshell Provider Adapter**를 도입하여 webshell provider family를 완성한다. JSP(X+1E), PHP(X+1F), Generic Base(X+1G) 위에 ASPX identity adapter를 추가하되 **실행·IIS·Windows·네트워크·transport 호출은 하지 않는다**.

```
WebshellProviderBase
        ↓
GenericWebshellProvider
        ↓
┌─────────────────────┐
│ JspWebshellProvider │
├─────────────────────┤
│ PhpWebshellProvider │
├─────────────────────┤
│ AspxWebshellProvider│ ← Phase X+1H
└─────────────────────┘
```

**Mock-First 원칙:** ASPX adapter 존재 ≠ ASPX 실행 가능. Capability는 GenericWebshellProvider에서 상속된 intent만 선언한다.

---

## 2. Provider Identity

| Attribute | Value |
|-----------|-------|
| `provider_type` | `"aspx"` |
| `provider_name` | ASPX Webshell Provider |
| `provider_version` | `1.0.0` |
| `session_class` | `AspxProviderSession` |

Family adapter는 위 identity와 session class만 선언한다. Windows/IIS/PowerShell 동작 없음.

---

## 3. Provider Responsibilities

`AspxWebshellProvider`는 `GenericWebshellProvider`에서 다음을 **상속**한다.

| Responsibility | Source |
|----------------|--------|
| Configuration validation | `GenericWebshellProvider` |
| Capability declaration (intent only) | `GenericWebshellProvider` |
| Session creation via `session_class` | `GenericWebshellProvider` |
| Transport reference storage | `GenericWebshellProvider` |
| Metadata with `provider_version` | `GenericWebshellProvider` |

ASPX-specific code: class attributes only (`provider.py` ~20 lines).

---

## 4. Provider Boundaries (Explicitly Forbidden)

| Forbidden | Reason |
|-----------|--------|
| `execute()` | Execution belongs to future Contract binding |
| `upload()` / `download()` | File transfer deferred |
| `cleanup()` / `healthcheck()` | Deferred to future phases |
| `transport.send_*()` | No HTTP in mock-first phase |
| WinRM / PowerShell / cmd.exe | No Windows execution |
| IIS integration | No platform-specific runtime |
| EventSyncBridge invocation | Event Store via bridge only (future) |
| RunManager / Scenario / Validation / Reporting | Provider layer isolated |

**금지 패턴 (플랫폼 전역):** stdout parsing, grep validation, log/report reconstruction, console success inference.

---

## 5. Generic Inheritance Model

```python
class AspxWebshellProvider(GenericWebshellProvider):
    provider_type = "aspx"
    provider_name = "ASPX Webshell Provider"
    session_class = AspxProviderSession
    provider_version = ASPX_PROVIDER_VERSION
```

Session:

```python
@dataclass
class AspxProviderSession(GenericWebshellSession):
    provider_version: str = ASPX_PROVIDER_VERSION
    # new() / from_dict() with aspx defaults
```

Exception:

```python
class AspxProviderError(GenericWebshellProviderError):
    """Identity-only exception base."""
```

---

## 6. Why ASPX Provider Is Intentionally Execution-Free

1. **Execution = Validation = Reporting** — adapter declares intent; execution populates Event Store via EventSyncBridge in later phases.
2. **Scenario = Execution Agnostic** — scenarios must not depend on ASPX/IIS specifics at this layer.
3. **Complete family structure first** — JSP, PHP, ASPX share GenericWebshellProvider before Contract binding.
4. **No platform assumptions** — ASPX identity does not imply Windows, IIS, or .NET runtime at provider layer.

---

## 7. Factory and Registry

| Entry point | Behavior |
|-------------|----------|
| `create_webshell_provider("jsp")` | `JspWebshellProvider` |
| `create_webshell_provider("php")` | `PhpWebshellProvider` |
| `create_webshell_provider("aspx")` | `AspxWebshellProvider` |
| `registry.register_provider("aspx", AspxWebshellProvider)` | Manual registration |

No auto-registration. No global singleton.

---

## 8. Package Layout

```
dsp/execution/providers/webshell/aspx/
├── __init__.py
├── provider.py          # AspxWebshellProvider
├── aspx_models.py       # AspxProviderSession
└── aspx_exceptions.py   # AspxProviderError
```

---

## 9. Future Roadmap

```
Phase X+1H  ASPX Provider Adapter (this document) — mock-first
     ↓
Phase X+1I  Contract Binding (JSP / PHP / ASPX)
     • WebshellContract integration
     • transport.send_*() behind Contract methods
     ↓
Phase X+1J  EventSyncBridge Wiring
     • Remote events → Event Store (sole source of truth)
     ↓
Phase X+1K  RunManager Integration
     • create_execution_provider("webshell") selects family
```

---

## 10. Event Store and RunManager Isolation

| Principle | Phase X+1H Status |
|-----------|-------------------|
| Event Store = Only Source Of Truth | Unchanged — no events produced |
| RunManager isolation | No RunManager imports or hooks |
| JSP/PHP behavior | Unchanged — GenericWebshellProvider untouched |

---

## 11. Intentionally Unimplemented Methods

The following **do not exist** on `AspxWebshellProvider`:

- `execute()`, `upload()`, `download()`, `cleanup()`, `healthcheck()`
- Transport invocation
- EventSyncBridge invocation
- RunManager / Scenario / Validation / Reporting hooks
- IIS / WinRM / PowerShell integration
