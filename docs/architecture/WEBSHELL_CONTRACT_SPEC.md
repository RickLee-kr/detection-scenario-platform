# Webshell Contract Specification

**문서 버전:** 1.0.0  
**상태:** Implemented (Phase X+1A — contract only)  
**Date:** 2026-06-06

---

## 1. Purpose

Webshell Contract는 JSP/PHP/ASPX/Generic HTTP family adapter가 구현할 **stable transport interface**이다. 본 Phase는 contract·models·validation helpers만 제공한다.

**Out of scope (X+1A):**

- HTTP transport
- Remote execution
- File upload/download logic
- Event synchronization
- RunManager integration

---

## 2. Package Structure

```
dsp/execution/webshell/
├── __init__.py
├── contract.py       # WebshellContract ABC
├── models.py         # Session, Command, Result models
├── capabilities.py   # WebshellCapabilities
├── exceptions.py     # Exception hierarchy
└── security.py       # WebshellSecurityPolicy + validation helpers
```

---

## 3. WebshellContract Methods

```python
class WebshellContract(ABC):
    def healthcheck(self) -> WebshellHealthResult: ...
    def execute(self, command: str | WebshellCommand) -> WebshellCommandResult: ...
    def upload(self, local_file: Path, remote_path: str) -> WebshellTransferResult: ...
    def download(self, remote_path: str) -> WebshellTransferResult: ...
    def cleanup(self) -> None: ...
    def capture_stdout(self, result: WebshellCommandResult) -> str: ...
    def capture_stderr(self, result: WebshellCommandResult) -> str: ...
```

| Method | Responsibility |
|--------|----------------|
| `healthcheck()` | Reachability probe, family detection |
| `execute()` | Dispatch shell command (string or `WebshellCommand`) |
| `upload()` | Stage file on remote host |
| `download()` | Retrieve remote file content |
| `cleanup()` | Teardown staged artifacts |
| `capture_stdout()` | Normalize family-specific stdout wrapping |
| `capture_stderr()` | Normalize family-specific stderr wrapping |

**Rules:**

- Contract methods MUST NOT reference scenario IDs
- Return values are transport outcomes — not validation decisions (ADR 0004)
- stdout/stderr normalization is for transport diagnostics only

---

## 4. Model Definitions

### 4.1 WebshellSession

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | `str` | Unique session identifier |
| `provider_type` | `str` | Always `"webshell"` |
| `webshell_url` | `str` | Endpoint URL |
| `created_at` | `datetime` | Session open time |
| `last_activity` | `datetime` | Last transport operation |
| `capabilities` | `WebshellCapabilities` | Declared features |
| `metadata` | `dict` | Auth mode, family, etc. |

Serialization: `to_dict()` / `from_dict()`.

### 4.2 WebshellCommand

| Field | Type | Default |
|-------|------|---------|
| `command` | `str` | required |
| `timeout_seconds` | `float` | `25.0` |
| `working_directory` | `str \| None` | `None` |
| `environment` | `dict[str, str]` | `{}` |

### 4.3 WebshellCommandResult

| Field | Type | Description |
|-------|------|-------------|
| `success` | `bool` | Transport-level success |
| `exit_code` | `int \| None` | Remote exit code |
| `stdout` | `str` | Raw stdout |
| `stderr` | `str` | Raw stderr |
| `duration_ms` | `float` | Round-trip duration |
| `metadata` | `dict` | HTTP status, transport used, etc. |

### 4.4 WebshellHealthResult

| Field | Type | Description |
|-------|------|-------------|
| `reachable` | `bool` | Endpoint reachable |
| `latency_ms` | `float` | Probe latency |
| `family_detected` | `str \| None` | jsp / php / aspx / generic |
| `error` | `str \| None` | Probe failure reason |

### 4.5 WebshellTransferResult

| Field | Type | Description |
|-------|------|-------------|
| `success` | `bool` | Transfer success |
| `remote_path` | `str` | Remote file path |
| `bytes_transferred` | `int` | Bytes moved |
| `error` | `str \| None` | Failure reason |
| `metadata` | `dict` | Hash, content ref, etc. |

---

## 5. Capability Model

`WebshellCapabilities` — family adapter declares supported features:

| Field | Description |
|-------|-------------|
| `supports_execute` | Command execution |
| `supports_upload` | File upload |
| `supports_download` | File download |
| `supports_chunked_upload` | Large file chunk pipeline |
| `supports_get` | GET transport |
| `supports_post` | POST transport |
| `supports_authentication` | Auth headers/cookies |
| `family` | Detected family identifier |

Future `WebshellExecutionProvider` uses capabilities from `healthcheck()` to gate operations.

---

## 6. Security Model

`WebshellSecurityPolicy` — lab envelope definition (validation helpers only in X+1A):

| Field | Default | Description |
|-------|---------|-------------|
| `allow_execute` | `True` | Permit command dispatch |
| `allow_upload` | `True` | Permit uploads |
| `allow_download` | `True` | Permit downloads |
| `allowed_paths` | `/tmp/dsp_stub/` | Remote path prefix allowlist |
| `blocked_commands` | destructive patterns | Substring blocklist |
| `max_file_size_mb` | `10.0` | Upload size cap |
| `safe_mode` | `True` | Enable command blocklist |

### Validation Helpers (no runtime enforcement)

| Helper | Raises |
|--------|--------|
| `validate_execute_allowed()` | `WebshellSecurityViolation` |
| `validate_upload_allowed()` | `WebshellSecurityViolation` |
| `validate_download_allowed()` | `WebshellSecurityViolation` |
| `validate_command_allowed()` | `WebshellSecurityViolation` |
| `validate_remote_path_allowed()` | `WebshellSecurityViolation` |
| `validate_file_size_allowed()` | `WebshellSecurityViolation` |
| `validate_local_file_allowed()` | `WebshellSecurityViolation` |

Enforcement wiring occurs in Phase X+1B+ transport layer.

---

## 7. Exception Hierarchy

```
WebshellError
├── WebshellConnectionError
├── WebshellAuthenticationError
├── WebshellExecutionError
├── WebshellUploadError
├── WebshellDownloadError
└── WebshellSecurityViolation
```

Each specialized exception carries optional context attributes (`url`, `mode`, `command`, `rule`, etc.).

---

## 8. Future Provider Implementation Expectations

### Phase X+1B — Transport Layer

- `HttpTransport` implements HTTP GET/POST/multipart
- Family adapters (`JspFamilyAdapter`, etc.) implement `WebshellContract`
- Security helpers called before dispatch

### Phase X+1C — Event Synchronization

- `EventSyncBridge` uses `download()` for remote JSONL bundle
- No changes to contract interface

### Phase X+1D — JSP Reference Provider

- `WebshellExecutionProvider` composes `WebshellContract` + `ExecutionProvider`
- Factory enables `create_execution_provider("webshell")`

### Implementation checklist for family adapters

1. Implement all seven `WebshellContract` methods
2. Declare accurate `WebshellCapabilities` after healthcheck
3. Use `capture_stdout()` / `capture_stderr()` for HTML/PHP wrapping
4. Call security validation helpers before execute/upload/download
5. Never append validation decisions — transport outcomes only

---

## 9. Related Documents

- [WEBSHELL_PROVIDER_ARCHITECTURE.md](./WEBSHELL_PROVIDER_ARCHITECTURE.md)
- [WEBSHELL_CONTRACT_REVIEW.md](./WEBSHELL_CONTRACT_REVIEW.md)
- [WEBSHELL_PROVIDER_IMPLEMENTATION_PLAN.md](./WEBSHELL_PROVIDER_IMPLEMENTATION_PLAN.md)
- [ADR 0007 — Webshell Execution Provider Architecture](../adr/0007-webshell-execution-provider-architecture.md)
