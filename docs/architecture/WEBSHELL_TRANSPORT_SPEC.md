# Webshell Transport Layer Specification

**문서 버전:** 1.0.0  
**상태:** Implemented (Phase X+1B — transport infrastructure only)  
**Date:** 2026-06-06

---

## 1. Purpose

Webshell Transport Layer는 JSP/PHP/ASPX family provider가 사용할 **HTTP request/response 추상화**를 제공한다. 본 Phase는 transport infrastructure만 구현한다.

**Out of scope (X+1B):**

- JSP / PHP / ASPX execution
- Remote traffic generation (live HTTP)
- Provider registration
- RunManager integration
- Event synchronization
- Scenario / Validation / Reporting changes

---

## 2. Package Structure

```
dsp/execution/webshell/transport/
├── __init__.py
├── base.py           # WebshellTransport ABC + security validation
├── models.py         # TransportRequest, TransportResponse
├── http_transport.py # MockHttpTransport (tests only)
├── retry.py          # RetryPolicy
├── timeout.py        # TimeoutProfile presets
└── errors.py         # Transport exception hierarchy
```

---

## 3. Transport Responsibilities

| Responsibility | Owner |
|----------------|-------|
| HTTP GET/POST mechanics | `WebshellTransport` implementations |
| Multipart upload envelope | `send_upload()` |
| Download response handling | `download()` |
| Reachability probe | `healthcheck()` |
| Pre-flight security validation | `validate_*_transport()` helpers |
| Retry / timeout policy models | `RetryPolicy`, `TimeoutProfile` |

Transport Layer는 **HTTP mechanics만** 처리한다. Command parsing, family detection logic, event sync는 provider phase에서 구현한다.

---

## 4. WebshellTransport Interface

```python
class WebshellTransport(ABC):
    def send_get(self, request: TransportRequest) -> TransportResponse: ...
    def send_post(self, request: TransportRequest) -> TransportResponse: ...
    def send_upload(self, request, *, local_path, remote_path) -> TransportResponse: ...
    def download(self, request, *, remote_path) -> TransportResponse: ...
    def healthcheck(self, request: TransportRequest) -> TransportResponse: ...
```

**Rules:**

- Methods MUST NOT reference scenario IDs, run IDs, or validation state
- Return values are transport outcomes — not validation decisions (ADR 0004)
- No provider-specific command encoding in this layer

---

## 5. Request Lifecycle

```
Provider builds TransportRequest
        │
        ▼
validate_transport_request() / validate_upload_transport() / validate_download_transport()
        │  (WebshellSecurityPolicy)
        ▼
WebshellTransport.send_*() / healthcheck()
        │  (optionally governed by RetryPolicy + TimeoutProfile)
        ▼
TransportResponse (status_code, headers, body, duration_ms, success)
```

1. **Build** — Provider constructs `TransportRequest` with URL, method, headers, body, timeout
2. **Validate** — Security helpers reject blocked URLs, forbidden paths, oversize uploads
3. **Dispatch** — Transport implementation issues HTTP operation (mock in X+1B tests)
4. **Return** — Normalized `TransportResponse` with timing metadata

---

## 6. Model Definitions

### 6.1 TransportRequest

| Field | Type | Default |
|-------|------|---------|
| `url` | `str` | required |
| `method` | `str` | `"GET"` |
| `headers` | `dict[str, str]` | `{}` |
| `cookies` | `dict[str, str]` | `{}` |
| `params` | `dict[str, str]` | `{}` |
| `body` | `bytes \| str \| None` | `None` |
| `timeout_seconds` | `float` | `25.0` |
| `metadata` | `dict` | `{}` |

Serialization: `to_dict()` / `from_dict()`.

### 6.2 TransportResponse

| Field | Type | Description |
|-------|------|-------------|
| `status_code` | `int` | HTTP status |
| `headers` | `dict[str, str]` | Response headers |
| `body` | `bytes` | Raw response body |
| `duration_ms` | `float` | Round-trip latency |
| `success` | `bool` | `200 <= status < 300` |
| `metadata` | `dict` | Transport diagnostics |

---

## 7. Retry Model

`RetryPolicy` — declarative policy only, no framework integration.

| Field | Default | Description |
|-------|---------|-------------|
| `max_retries` | `2` | Maximum retry attempts after initial call |
| `backoff_seconds` | `1.0` | Backoff between attempts |
| `retry_on_timeout` | `True` | Retry after timeout |
| `retry_on_http_5xx` | `True` | Retry on server errors |
| `retry_on_http_429` | `True` | Retry on rate limit |

`should_retry(attempt, status_code, timed_out)` evaluates retry eligibility. Provider implementations wire retry loops in a future phase.

---

## 8. Timeout Model

### 8.1 Timeout Profiles

| Profile | Connect (s) | Read (s) | Total (s) | Use case |
|---------|-------------|----------|-----------|----------|
| `fast` | 5 | 10 | 15 | Healthcheck, lightweight GET |
| `normal` | 10 | 25 | 30 | Standard POST command dispatch |
| `large_transfer` | 15 | 120 | 180 | File download |
| `bulk_upload` | 20 | 300 | 600 | Large multipart upload |

### 8.2 Validation Helpers

| Helper | Raises |
|--------|--------|
| `validate_timeout_profile_name()` | `ValueError` on unknown profile |
| `validate_timeout_seconds()` | `ValueError` on non-positive or profile exceedance |
| `get_timeout_profile()` | Returns `TimeoutProfile` by name |

---

## 9. Security Validation

Transport validation wires `WebshellSecurityPolicy` before dispatch.

| Helper | Checks |
|--------|--------|
| `validate_transport_url()` | Blocked schemes (`file`, `gopher`, `data`), http/https only, safe-mode loopback block, custom URL patterns |
| `validate_transport_request()` | URL + positive timeout |
| `validate_upload_transport()` | Upload allowed, remote path allowlist, forbidden paths (`/etc/`, `/root/`, …), file exists, max size |
| `validate_download_transport()` | Download allowed, remote path allowlist |

Raises `WebshellTransportValidationError` with `rule` attribute. Reuses existing `WebshellSecurityPolicy` helpers (`validate_upload_allowed`, `validate_remote_path_allowed`, etc.).

---

## 10. Error Model

```
WebshellError
└── WebshellTransportError
    ├── WebshellTransportTimeoutError
    ├── WebshellTransportRetryExhaustedError
    └── WebshellTransportValidationError
```

| Exception | Context attributes |
|-----------|-------------------|
| `WebshellTransportTimeoutError` | `url`, `timeout_seconds` |
| `WebshellTransportRetryExhaustedError` | `url`, `attempts`, `last_status_code` |
| `WebshellTransportValidationError` | `rule` |

---

## 11. Mock HTTP Transport

`MockHttpTransport` — unit tests only, no network I/O.

| Mode | Behavior |
|------|----------|
| `SUCCESS` | Configurable 2xx response (default 200) |
| `TIMEOUT` | Raises `WebshellTransportTimeoutError` |
| `HTTP_5XX` | Returns 503, `success=False` |
| `HTTP_429` | Returns 429, `success=False` |
| `AUTH_FAILURE` | Returns 401, `success=False` |

Records all calls in `calls` list for assertion.

---

## 12. Future Provider Integration

### Phase X+1C — Event Synchronization

- Provider uses `download()` transport for remote JSONL bundle retrieval
- No transport interface changes

### Phase X+1D — JSP Reference Provider

- `JspFamilyAdapter` implements `WebshellContract`, composes `WebshellTransport`
- Live `UrllibHttpTransport` (or equivalent) replaces `MockHttpTransport`
- `RetryPolicy.should_retry()` wired into dispatch loop
- `TimeoutProfile` selected per operation type

### Implementation checklist

1. Call `validate_*_transport()` before every dispatch
2. Select `TimeoutProfile` by operation (`fast` for healthcheck, `bulk_upload` for upload)
3. Use `TransportRequest` / `TransportResponse` — never leak raw urllib objects
4. Never append validation decisions — transport outcomes only
5. Keep transport independent from RunManager, scenarios, Event Store

---

## 13. Related Documents

- [WEBSHELL_CONTRACT_SPEC.md](./WEBSHELL_CONTRACT_SPEC.md)
- [WEBSHELL_TRANSPORT_REVIEW.md](./WEBSHELL_TRANSPORT_REVIEW.md)
- [WEBSHELL_PROVIDER_ARCHITECTURE.md](./WEBSHELL_PROVIDER_ARCHITECTURE.md)
- [ADR 0007 — Webshell Execution Provider Architecture](../adr/0007-webshell-execution-provider-architecture.md)
