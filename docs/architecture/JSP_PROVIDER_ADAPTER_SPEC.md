# JSP Provider Adapter — Architecture Spec

**문서 버전:** 1.0.0  
**상태:** Phase X+1E — mock-first adapter (no execution)  
**Date:** 2026-06-06

---

## 1. Purpose

Phase X+1E는 **JSP Webshell Provider Adapter**를 도입한다. Provider Skeleton(Phase X+1D) 위에 첫 번째 family adapter를 올리되, **실행·네트워크·transport 호출은 하지 않는다**.

이번 단계의 목표:

```
JspWebshellProvider
    ↓
WebshellContract (future binding)
    ↓
MockHttpTransport (constructor injection only)
    ↓
EventSyncBridge (future)
```

**Mock-First 원칙:** adapter 존재 ≠ 실행 가능. Capability는 intent만 선언한다.

---

## 2. Provider Responsibilities

`JspWebshellProvider` (`dsp/execution/providers/webshell/jsp/provider.py`)는 다음만 담당한다.

| Responsibility | Description |
|----------------|-------------|
| Provider metadata | `provider_type`, `provider_name`, `provider_version` |
| Configuration validation | `provider_type`, `transport_type`, `safe_mode`, `timeout_profile` |
| Capability declaration | Intent-only matrix (all `True` by default) |
| Session creation | `JspProviderSession` in `CREATED` state |
| Transport attachment | Constructor injection — reference stored only |

---

## 3. Provider Boundaries (Explicitly Forbidden)

다음은 **구현하지 않으며 호출하지 않는다.**

| Forbidden | Reason |
|-----------|--------|
| `execute()` | Execution belongs to future Contract binding |
| `upload()` / `download()` | File transfer deferred to Contract + Transport |
| `cleanup()` | Session teardown without transport |
| `healthcheck()` | Transport probing deferred |
| `transport.send_*()` | No HTTP in mock-first phase |
| `transport.healthcheck()` | No reachability probing |
| EventSync invocation | Event Store populated only via EventSyncBridge (future) |
| RunManager integration | Provider layer remains isolated |
| Scenario / Validation / Reporting | Execution-agnostic scenario model preserved |

**금지 패턴 (플랫폼 전역):**

- stdout parsing
- grep validation
- log reconstruction
- report reconstruction
- console output success inference

---

## 4. Transport Boundaries

| Layer | Responsibility |
|-------|----------------|
| `JspWebshellProvider` | Stores `WebshellTransport` reference from constructor |
| `WebshellTransport` | HTTP mechanics (GET/POST/upload/download/healthcheck) |
| `MockHttpTransport` | Unit-test stub — no live network I/O |

Provider는 transport를 **주입받기만** 하고 **절대 호출하지 않는다.**  
Transport는 provider 로직을 모른다. Contract가 future phase에서 둘을 조합한다.

---

## 5. Session Model

`JspProviderSession` extends `ProviderSession`:

| Field | Description |
|-------|-------------|
| `webshell_url` | Target JSP endpoint URL (metadata only) |
| `transport_type` | `http` or `https` |
| `provider_version` | Adapter version (`1.0.0`) |

Session은 `CREATED` 상태 record만 생성한다. Transport binding은 future phase.

---

## 6. Configuration Validation

`validate_configuration()` checks:

1. `provider_type == "jsp"`
2. `transport_type` exists and is in `VALID_TRANSPORT_TYPES`
3. `safe_mode` defined as `bool`
4. `timeout_profile` defined and in `VALID_TIMEOUT_PROFILES`

Invalid configuration raises `ProviderConfigurationError`.

---

## 7. Factory and Registry

| Entry point | Behavior |
|-------------|----------|
| `create_webshell_provider("jsp")` | Returns `JspWebshellProvider` |
| `create_webshell_provider("php")` | `NotImplementedError` |
| `create_webshell_provider("aspx")` | `NotImplementedError` |
| `registry.register_provider("jsp", JspWebshellProvider)` | Manual registration supported |

**No auto-registration. No global singleton provider instance.**

---

## 8. Why Adapter Exists Before Execution

1. **Separation of concerns** — metadata, validation, and session models stabilize before HTTP/Contract wiring.
2. **Testability** — factory, registry, and isolation tests run without network or Event Store side effects.
3. **Execution = Validation = Reporting** — adapter declares capability intent; actual execution populates Event Store via EventSyncBridge in later phases.
4. **Scenario = Execution Agnostic** — scenarios never depend on JSP-specific transport details at this layer.

---

## 9. Package Layout

```
dsp/execution/providers/webshell/jsp/
├── __init__.py
├── provider.py          # JspWebshellProvider
├── jsp_models.py        # JspProviderSession
└── jsp_exceptions.py    # JspProviderError hierarchy
```

---

## 10. Future Implementation Roadmap

```
Phase X+1E  JSP Provider Adapter (this document) — mock-first
     ↓
Phase X+1F  JSP Contract Binding
     • WebshellContract integration
     • transport.send_*() behind Contract methods
     • execute / upload / download implementation
     ↓
Phase X+1G  EventSyncBridge Wiring
     • Remote events → Event Store (sole source of truth)
     ↓
Phase X+1H  RunManager Integration
     • create_execution_provider("webshell") selects family
     ↓
Phase X+1I  PHP / ASPX Expansion
     • PhpWebshellProvider, AspxWebshellProvider
```

---

## 11. Event Store and RunManager Isolation

| Principle | Phase X+1E Status |
|-----------|-------------------|
| Event Store = Only Source Of Truth | Unchanged — no events produced |
| RunManager isolation | No RunManager imports or hooks |
| Execution Provider = Transport Agnostic | Transport injected, never invoked |

---

## 12. Intentionally Unimplemented Methods

The following methods **do not exist** on `JspWebshellProvider` in Phase X+1E:

- `execute()`
- `upload()`
- `download()`
- `cleanup()`
- `healthcheck()`
- Any EventSyncBridge invocation
- Any RunManager / Scenario / Validation / Reporting hooks
