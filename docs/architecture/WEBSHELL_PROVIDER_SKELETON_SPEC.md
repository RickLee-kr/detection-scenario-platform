# Webshell Provider Skeleton — Architecture Spec

**문서 버전:** 1.0.0  
**상태:** Phase X+1D — skeleton only (no execution)  
**Date:** 2026-06-06

---

## 1. Purpose

Phase X+1D는 **Provider Family Architecture**를 도입한다. Contract, Transport, EventSyncBridge는 이미 존재하며, 이번 단계는 그 위에 **family adapter skeleton**을 올린다.

**이번 단계에서 구현하지 않는 것:**

- JSP / PHP / ASPX 실제 실행
- command / shell 실행
- upload.jsp 통합
- 네트워크 통신, transport 호출
- EventSync 실행
- RunManager 통합

---

## 2. Layer Boundaries

```
┌─────────────────────────────────────────────────────────────┐
│  RunManager / Scenario (unchanged — no integration yet)      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Provider Layer (Phase X+1D)                                 │
│  dsp/execution/providers/webshell/                           │
│  • WebshellProviderBase                                      │
│  • ProviderRegistry / ProviderFactory                        │
│  • ProviderConfiguration / ProviderSession                     │
│  Responsibility: capability, session model, metadata only    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Contract Boundary (Phase X+1A)                              │
│  dsp/execution/webshell/contract.py                          │
│  • WebshellContract ABC                                      │
│  • WebshellCapabilities, command/transfer models             │
│  Responsibility: family-agnostic transport interface         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Transport Boundary (Phase X+1B)                             │
│  dsp/execution/webshell/transport/                           │
│  • HttpTransport, retry, timeout profiles                    │
│  Responsibility: HTTP envelope — no validation/reporting     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  EventSync Boundary (Phase X+1C)                             │
│  dsp/execution/webshell/event_sync/                          │
│  • EventSyncBridge                                           │
│  Responsibility: remote bundle → local Event Store import    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Event Store (sole source of truth — unchanged)              │
│  Validation / Reporting (unchanged)                          │
└─────────────────────────────────────────────────────────────┘
```

### 2.1 Provider Boundary

| In scope | Out of scope |
|----------|--------------|
| `provider_type`, `provider_name` | command execution |
| `get_capabilities()` | file upload/download |
| `create_session()` metadata | HTTP requests |
| `validate_configuration()` | EventSyncBridge calls |
| Registry / Factory wiring | RunManager hooks |

### 2.2 Contract Boundary

`WebshellContract`는 family adapter가 **향후** 구현할 transport 메서드를 정의한다. Provider skeleton은 Contract를 구현하지 않는다.

### 2.3 Transport Boundary

Transport layer는 HTTP envelope만 담당한다. Provider layer는 transport를 호출하지 않는다.

### 2.4 EventSync Boundary

`EventSyncBridge`는 remote event bundle을 local Event Store로 가져온다. Provider skeleton은 bridge를 호출하지 않는다.

**불변식:** Event Store = Only Source Of Truth. stdout parsing, grep validation, log reconstruction 금지.

---

## 3. Package Layout

```
dsp/execution/providers/webshell/
├── __init__.py
├── base_provider.py          # WebshellProviderBase
├── provider_models.py        # ProviderConfiguration, ProviderSession, ProviderCapabilities
├── provider_exceptions.py
├── provider_registry.py      # WebshellProviderRegistry
└── provider_factory.py       # create_webshell_provider()
```

---

## 4. Reserved Provider Identities

| `provider_type` | Status |
|-----------------|--------|
| `jsp` | Reserved — `NotImplementedError` |
| `php` | Reserved — `NotImplementedError` |
| `aspx` | Reserved — `NotImplementedError` |

`create_webshell_provider("jsp")` 등은 future compatibility를 위해 identity만 예약하고, 인스턴스를 반환하지 않는다.

---

## 5. Capability Model

`ProviderCapabilities` defaults (until real providers exist):

| Field | Default |
|-------|---------|
| `upload_supported` | `False` |
| `download_supported` | `False` |
| `execute_supported` | `False` |
| `event_sync_supported` | `False` |
| `transport_supported` | `False` |

---

## 6. Session Model

`ProviderSession` states:

| State | Meaning |
|-------|---------|
| `CREATED` | Session record allocated (no transport) |
| `CONNECTED` | Reserved for future transport binding |
| `CLOSED` | Session ended |
| `ERROR` | Session error metadata |

Phase X+1D에서는 `create_session()`이 `CREATED` 상태 record만 생성한다.

---

## 7. Future Roadmap

```
Phase X+1D  Provider Skeleton (this document)
     ↓
Phase X+1E  JSP Reference Provider
     • JspWebshellProvider implements WebshellProviderBase
     • Binds WebshellContract + HttpTransport
     • Enables factory for "jsp"
     ↓
Phase X+1F  PHP / ASPX Expansion
     • PhpWebshellProvider, AspxWebshellProvider
     ↓
Phase X+1G  RunManager Integration
     • create_execution_provider("webshell") wires provider family
     • EventSyncBridge populates Event Store after remote execution
```

각 family adapter는:

1. `WebshellProviderBase` — capability + session declaration
2. `WebshellContract` — transport dialect (execute/upload/download)
3. `EventSyncBridge` — post-execution event import

Validation과 Reporting은 Event Store만 읽으며 변경되지 않는다.

---

## 8. Acceptance Criteria (Phase X+1D)

- [x] Provider family architecture exists
- [x] Registry exists with duplicate protection
- [x] Factory exists; jsp/php/aspx → `NotImplementedError`
- [x] Session model and capability model exist
- [x] No actual execution, network, or RunManager integration
- [x] Existing tests pass; new provider tests pass
