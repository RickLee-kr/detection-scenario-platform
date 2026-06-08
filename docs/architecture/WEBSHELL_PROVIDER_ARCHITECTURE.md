# Webshell Execution Provider — Architecture

**문서 버전:** 1.0.0  
**상태:** Design only — no implementation  
**Date:** 2026-06-06  
**Phase:** X+1 (Webshell Provider — architecture)

---

## 1. Purpose

Webshell Execution Provider는 **Execution Mode B**를 구현한다. DSP Host는 orchestration·Event Store·Validation·Reporting을 담당하고, **트래픽 생성은 원격 webshell host**에서 발생한다.

```
DSP Host
  ↓
WebshellExecutionProvider
  ↓
Remote Webshell Host
  ↓
Traffic Generation (remote process)
  ↓
Event Synchronization
  ↓
Event Store (DSP Host — authoritative SOT)
  ↓
Validation (unchanged)
  ↓
Reporting (unchanged)
```

**핵심 불변식:**

- 시나리오 코드는 local / webshell / ssh / agent를 알지 못한다.
- Event Store schema·API·Validation·Reporting은 변경하지 않는다.
- Path Equality: `Execution Path = Validation Path = Reporting Path`

---

## 2. Placement in Execution Provider Framework

```
RunManager
  → create_execution_provider("webshell")
  → WebshellExecutionProvider.prepare(ExecutionContext)
  → for each scenario:
        WebshellExecutionProvider.execute(...)
            → WebshellTransport (healthcheck, upload, execute)
            → Remote Executor Stub (scenario bundle)
            → EventSyncBridge (remote bundle → ctx.event_store)
  → WebshellExecutionProvider.cleanup(ExecutionContext)
  → ValidationEngine (unchanged)
  → ReportingEngine (unchanged)
```

| Layer | Responsibility |
|-------|----------------|
| `WebshellExecutionProvider` | Mode B lifecycle, stub staging, event sync orchestration |
| `WebshellContract` | Family-agnostic transport interface (contract only) |
| `WebshellFamilyAdapter` | JSP / PHP / ASPX / Generic HTTP dialect |
| `RemoteExecutorStub` | Minimal runtime on victim — runs scenario executor, buffers events |
| `EventSyncBridge` | Downloads/imports remote event bundle into local Event Store |

---

## 3. Webshell Contract (Interface — No Implementation)

Webshell family adapter는 아래 **contract only** 인터페이스를 구현한다. DSP core와 시나리오는 이 contract에만 의존한다.

```python
# CONCEPTUAL ONLY — documentation, not runtime code

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class WebshellHealthResult:
    reachable: bool
    family_detected: str | None      # "jsp" | "php" | "aspx" | "generic"
    latency_ms: float
    error: str | None = None


@dataclass
class WebshellExecuteResult:
    exit_code: int | None
    stdout: str
    stderr: str
    http_status: int
    duration_ms: float
    transport_used: str              # "GET" | "POST" | "multipart"
    error: str | None = None


@dataclass
class WebshellTransferResult:
    success: bool
    remote_path: str
    bytes_transferred: int
    error: str | None = None


class WebshellContract(Protocol):
    """Family-agnostic webshell transport — scenario-agnostic."""

    def healthcheck(self) -> WebshellHealthResult:
        """Verify webshell reachability and detect family if possible."""

    def execute(self, command: str, *, timeout_sec: float) -> WebshellExecuteResult:
        """Run shell command on remote host via webshell."""

    def upload(self, local_file: Path, remote_path: str) -> WebshellTransferResult:
        """Upload file from DSP Host to remote host."""

    def download(self, remote_file: str, local_dest: Path) -> WebshellTransferResult:
        """Download file from remote host to DSP Host."""

    def cleanup(self) -> None:
        """Remove staged artifacts per lab policy (best-effort)."""

    def capture_stdout(self, result: WebshellExecuteResult) -> str:
        """Normalize stdout from family-specific response wrapping."""

    def capture_stderr(self, result: WebshellExecuteResult) -> str:
        """Normalize stderr from family-specific response wrapping."""
```

### 3.1 Contract Rules

| Rule | Detail |
|------|--------|
| Scenario isolation | Contract methods MUST NOT reference scenario IDs or protocol logic |
| No validation | Return values are transport outcomes only — not S2 decisions |
| stdout/stderr | Used for transport diagnostics and event bundle retrieval — **not** validation input (ADR 0004) |
| cleanup | Policy-driven; lab may retain artifacts for forensics |

---

## 4. Supported Webshell Families

### 4.1 JSP Webshell

| Aspect | Detail |
|--------|--------|
| **Authentication model** | HTTP Basic, custom header token, session cookie, or none (lab-only) |
| **Command execution** | `cmd` / `command` parameter via GET or POST; often wrapped in `Runtime.exec()` → `/bin/sh -c` |
| **Upload support** | Multipart POST to dedicated upload endpoint, or base64-in-body to write endpoint |
| **Download support** | `cat` via execute + response body, or dedicated download servlet |
| **Expected response format** | HTML wrapper with command output embedded; may include `<pre>` blocks; exit code often appended as marker line (`__EXIT_CODE:N`) |
| **Limitations** | Servlet container timeout; WAF may strip shell metacharacters; large stdout truncated by container buffer; no native UDP socket from JSP without JNI |

### 4.2 PHP Webshell

| Aspect | Detail |
|--------|--------|
| **Authentication model** | POST password field, cookie session, or IP allowlist (lab) |
| **Command execution** | `system()`, `shell_exec()`, `passthru()`, or backtick via `cmd` parameter |
| **Upload support** | `$_FILES` multipart, or base64 decode-to-file |
| **Download support** | `readfile()` endpoint or execute `cat` / `base64` pipeline |
| **Expected response format** | Plain text or minimal HTML; PHP warnings may prefix output |
| **Limitations** | `disable_functions` may block exec; `open_basedir` restricts paths; `max_execution_time`; no raw UDP without extensions |

### 4.3 ASPX Webshell

| Aspect | Detail |
|--------|--------|
| **Authentication model** | ViewState + cookie, custom auth header, or none (lab) |
| **Command execution** | `ProcessStartInfo` via `cmd.exe /c` or PowerShell `-Command` |
| **Upload support** | Multipart upload handler, or base64 body write |
| **Download support** | File read handler or PowerShell `Get-Content` / compressed base64 |
| **Expected response format** | HTML/ASPX page with output in literal control or comment block |
| **Limitations** | AppPool identity restrictions; AMSI/Defender on victim; Windows path semantics; UDP requires different tooling |

### 4.4 Generic HTTP Command Shell

| Aspect | Detail |
|--------|--------|
| **Authentication model** | Configurable: none, Bearer token, custom header, cookie |
| **Command execution** | Arbitrary parameter name (`cmd`, `c`, `exec`) — detected at healthcheck |
| **Upload support** | Adapter-specific; may fall back to base64 chunk pipeline |
| **Download support** | Adapter-specific; may fall back to execute+capture |
| **Expected response format** | Plain text preferred; adapter normalizes via `capture_stdout()` |
| **Limitations** | Lowest common denominator — feature flags per instance; family detection may fail |

### 4.4 Family Selection

```
healthcheck()
  → detect Content-Type, response markers, parameter echo
  → select JspFamilyAdapter | PhpFamilyAdapter | AspxFamilyAdapter | GenericFamilyAdapter
  → cache in ExecutionContext.execution_metadata["webshell_family"]
```

---

## 5. Transport Models

### 5.1 GET Execution

| Aspect | Detail |
|--------|--------|
| Use case | Short commands, healthcheck probes |
| Encoding | URL-encoded `cmd` parameter |
| Size limit | ~2–8 KB effective (proxy/server dependent) |
| Idempotency | Unsafe for state-changing commands — lab policy may forbid |

### 5.2 POST Execution

| Aspect | Detail |
|--------|--------|
| Use case | Default for command execution |
| Encoding | `application/x-www-form-urlencoded` or `multipart/form-data` |
| Size limit | Higher than GET; still bounded by server `max_post_size` |
| Timeout | Separate connect vs read timeout |

### 5.3 Multipart Upload

| Aspect | Detail |
|--------|--------|
| Use case | Remote executor stub, scenario bundle, large scripts |
| Fields | File part + optional metadata (path, mode) |
| Verification | Post-upload `wc -c` or hash check via execute |

### 5.4 Chunked Upload

| Aspect | Detail |
|--------|--------|
| Use case | Payloads exceeding single POST limit |
| Strategy | Split into N chunks; append/base64-decode on remote; reassemble |
| Integrity | Per-chunk SHA256 + final file hash verification |
| Reference | Legacy `stellar_poc.sh` chunk patterns |

### 5.5 Timeout Handling

| Tier | Default | Use |
|------|---------|-----|
| `healthcheck` | 10s | Reachability |
| `quick` | 15s | Size probes, small cat |
| `normal` | 25s | Standard execute |
| `long` | 300s | Scenario executor run, large download |

Timeout expiry → transport error meta event (`webshell_timeout`); **not** validation bypass.

### 5.6 Large Payload Handling

| Condition | Strategy |
|-----------|----------|
| Command < 4 KB | Single POST |
| Command 4–64 KB | Chunked upload to temp script, execute script |
| File > 64 KB | Chunked upload + gzip optional |
| Event bundle > 400 KB | gzip + base64 pipeline (legacy pattern) |

### 5.7 Retry Strategy

| Error class | Retry | Backoff |
|-------------|-------|---------|
| HTTP 5xx | Yes | 1s, 2s, 4s (max 3) |
| HTTP 429 | Yes | Respect Retry-After |
| Connection reset | Yes | 2s (max 2) |
| HTTP 4xx (auth) | No | Fail fast — config error |
| Timeout | No | Surface as transport failure |

### 5.8 Error Handling

| Error | Provider action | Validation impact |
|-------|-----------------|-------------------|
| Webshell unreachable | `execution_prepare_failed` meta event; skip scenario | No traffic events → existing fail-fast rules |
| Upload failed | `webshell_upload_failed` meta event; abort scenario | Partial or zero traffic events |
| Execute failed | `webshell_execute_failed` meta event | Depends on events synced |
| Sync failed | `execution_sync_failed` meta event | Validation sees only synced events |
| Partial sync | `execution_sync_partial` meta event + evidence | Threshold may fail — correct behavior |

---

## 6. Event Synchronization Model

### 6.1 Problem

Remote host에서 트래픽이 생성되면, Event Store(SOT)는 DSP Host에 있다. Remote executor가 기록한 events를 **동일 schema**로 local store에 반영해야 Path Equality가 유지된다.

### 6.2 Option A — Remote Returns Structured Events

Remote executor가 HTTP response body에 JSON event array를 직접 반환.

```
execute_scenario → remote stub runs → stub returns JSON events inline
                  → provider parses → ctx.event_store.append() each
```

| Criterion | Assessment |
|-----------|------------|
| Reliability | Medium — HTTP response size limits truncate high-volume scenarios (dns_tunnel) |
| Performance | Good for small runs — single round-trip |
| Security | Medium — events in HTTP logs, WAF inspection |
| Complexity | Low transport, high stub design (must serialize in-response) |

### 6.3 Option B — Raw Output Reconstruction

Remote가 stdout/text만 반환; DSP가 regex/parser로 events 재구성.

```
execute → capture stdout → DSP EventReconstructor → append
```

| Criterion | Assessment |
|-----------|------------|
| Reliability | **Low** — fragile parsing, schema drift risk |
| Performance | Poor for volume scenarios |
| Security | Low — stdout may leak in logs |
| Complexity | High — violates ADR 0004 spirit; duplicate validation path risk |

**Rejected** as primary model.

### 6.4 Option C — Remote Event Bundle Download

Remote executor가 victim-side JSONL/JSON bundle 파일에 events 기록; provider가 download 후 import.

```
execute → remote stub writes /tmp/dsp_events_<run_id>.jsonl
       → provider download(bundle)
       → EventSyncBridge.validate_schema + append each
       → optional remote cleanup
```

| Criterion | Assessment |
|-----------|------------|
| Reliability | **High** — proven in legacy stellar_poc remote blob fetch |
| Performance | Good — gzip/base64 for large bundles; decoupled from HTTP response size |
| Security | Better — bundle file permissions on victim; TLS in transit |
| Complexity | Medium — stub + sync bridge; schema validator required |

### 6.5 Recommendation

**Primary: Option C (Remote Event Bundle Download)**

| Rationale | Detail |
|-----------|--------|
| Path Equality | Import path uses same Event schema validator as local append |
| Volume | dns_tunnel, port_sweep 등 high-event scenarios 지원 |
| Legacy alignment | `stellar_poc.sh` remote file blob pattern formalized |
| ADR 0004 | stdout is transport diagnostic only — not reconstruction source |

**Supplementary: Option A for meta events only**

Healthcheck, sync status, small lifecycle markers may inline in execute response. Traffic events MUST use Option C.

### 6.6 EventSyncBridge Flow (Conceptual)

```
1. RemoteExecutorStub opens bundle path (JSONL, one Event per line)
2. Scenario executor runs on remote — append to bundle (same Event fields)
3. Stub finalizes bundle (close, fsync, write manifest sidecar)
4. Provider download(bundle) → local temp
5. EventSyncBridge:
     for each line:
       validate against Event schema
       ctx.event_store.append(event)
6. Record execution_metadata: events_synced, bytes, duration_ms
7. On validation failure of any line → execution_sync_failed, skip invalid lines with audit log
```

### 6.7 Sync Failure Policy

| Policy | Behavior |
|--------|----------|
| Zero events synced after execute | Scenario lifecycle events only; validation applies SOT_EMPTY rules |
| Partial sync | Append valid events; meta event records count mismatch |
| Duplicate run_id/scenario_id | Idempotent append prohibited — bridge rejects duplicates |

---

## 7. Security Model

### 7.1 Allowed Commands (Lab Envelope)

| Category | Allowed |
|----------|---------|
| Scenario executor invocation | `python3 /tmp/dsp_stub/<run_id>/executor.py` |
| File size/hash verification | `wc -c`, `sha256sum`, `test -f` |
| Network tools (scenario-driven) | `curl`, `dig`, `nc`, `python3 -c` (via stub only) |
| Cleanup | `rm -f` on staged paths under `/tmp/dsp_stub/` |
| Diagnostics | `uname`, `id`, `which python3` (healthcheck) |

### 7.2 Forbidden Commands

| Category | Forbidden |
|----------|-----------|
| Destructive | `rm -rf /`, `mkfs`, disk wipe |
| Persistence | `crontab`, systemd unit install, registry run keys |
| Lateral movement | Arbitrary SSH/RDP to non-lab hosts |
| Exfiltration | Upload to non-lab URLs |
| Privilege escalation | `sudo`, SUID exploitation outside lab scope |
| Shell injection | Unsanitized operator input in command string |

Command allowlist enforced in `WebshellExecutionProvider` **before** transport dispatch — not in scenario code.

### 7.3 Credential Handling

| Rule | Detail |
|------|--------|
| Storage | RunConfig / env / secrets file — never in scenario manifests |
| Logging | Credentials redacted in all logs and meta events |
| Rotation | Lab credentials rotated per engagement policy |
| TLS | HTTPS required for production lab; HTTP lab-only with explicit opt-in flag |

### 7.4 Safe Mode Guarantees

| Guarantee | Mechanism |
|-----------|-----------|
| Lab-only targets | Target Provider + webshell URL allowlist |
| Dry-run | No remote dispatch; synthetic meta events only |
| Explicit opt-in | `--execution-provider webshell` required — never default |
| Rate limits | Max commands/minute, max upload bytes/run |
| Timeout caps | Hard ceiling on long tier |

### 7.5 Upload Restrictions

| Restriction | Value |
|-------------|-------|
| Max single file | 10 MB (configurable) |
| Allowed extensions | `.py`, `.sh`, `.json`, `.jsonl`, `.tar.gz` |
| Destination paths | `/tmp/dsp_stub/<run_id>/` only |
| Overwrite | Only within run-scoped directory |

### 7.6 Execution Restrictions

| Restriction | Detail |
|-------------|--------|
| Working directory | `/tmp/dsp_stub/<run_id>/` |
| Environment | Minimal — `DSP_RUN_ID`, `DSP_SCENARIO_ID`, `DSP_TARGET_NET` |
| Concurrent runs | One active stub per run_id on victim |
| User context | Whatever webshell runs as — documented in report metadata |

### 7.7 Audit Requirements

| Event | Recorded |
|-------|----------|
| Every webshell execute | Meta event: `webshell_command_dispatched` (command hash, not plaintext if sensitive) |
| Upload/download | Meta event: path, bytes, outcome |
| Sync | Meta event: events_synced, bundle hash |
| Auth failure | Meta event: `webshell_auth_failed` |
| Policy violation | Meta event: `webshell_policy_denied` |

Audit events use `stage=execution_provider`, `source=webshell` — excluded from scenario validation thresholds unless manifest explicitly declares (default: excluded).

---

## 8. Execution Context Extensions

Future `ExecutionContext.provider_config` / `execution_metadata` fields for webshell mode. **Define only — not implemented.**

```python
# CONCEPTUAL — extensions to ExecutionContext.provider_config

@dataclass
class WebshellProviderConfig:
    provider_type: str = "webshell"           # always "webshell"
    webshell_url: str                         # required
    authentication_mode: str                  # "none" | "basic" | "bearer" | "cookie" | "custom_header"
    headers: dict[str, str]                   # optional custom headers
    cookies: dict[str, str]                   # optional session cookies
    request_method: str                       # "POST" | "GET" | "auto"
    upload_capability: bool                   # detected at healthcheck
    download_capability: bool                 # detected at healthcheck
    timeout_sec: float                        # default 25.0
    retry_policy: dict[str, Any]              # max_retries, backoff_sec, retry_on_5xx
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `provider_type` | `str` | Yes | `"webshell"` |
| `webshell_url` | `str` | Yes | Full URL to webshell endpoint |
| `authentication_mode` | `str` | Yes | Auth strategy |
| `headers` | `dict` | No | Custom HTTP headers |
| `cookies` | `dict` | No | Session cookies |
| `request_method` | `str` | No | Default POST; auto-select by payload size |
| `upload_capability` | `bool` | No | Set by healthcheck |
| `download_capability` | `bool` | No | Set by healthcheck |
| `timeout_sec` | `float` | No | Per-request timeout |
| `retry_policy` | `dict` | No | Retry configuration |

`execution_metadata` populated at runtime:

| Field | Set by | Purpose |
|-------|--------|---------|
| `webshell_family` | healthcheck | jsp / php / aspx / generic |
| `traffic_origin_host` | prepare | Remote victim IP/hostname |
| `remote_stub_path` | prepare | Staged executor path |
| `event_bundle_path` | execute | Remote JSONL path |
| `events_synced` | sync | Count appended to Event Store |
| `bundle_sha256` | sync | Integrity verification |

---

## 9. Remote Executor Stub (Conceptual)

Minimal runtime staged on victim — **not scenario code**.

```
/tmp/dsp_stub/<run_id>/
  executor.py          # Scenario-specific logic (transmitted bundle)
  event_buffer.jsonl   # Option C sync target
  manifest.json        # run_id, scenario_id, schema_version
  run.sh               # Wrapper: python3 executor.py
```

Stub responsibilities:

1. Set env vars (`DSP_RUN_ID`, `DSP_SCENARIO_ID`, `DSP_TARGET_NET`)
2. Invoke scenario executor with local TargetSet resolution
3. Append events to `event_buffer.jsonl` using **identical Event schema**
4. Exit with code; write sidecar status file

Scenario source remains on DSP Host; provider transmits **executor bundle** only.

---

## 10. Capability Matrix (Scenario × Webshell)

| Scenario | Local | Webshell | Notes |
|----------|-------|----------|-------|
| dns_tunnel | Yes | Conditional | Raw UDP/53 may need DNS relay on victim |
| dga | Yes | Yes | DNS queries from victim |
| http_followup | Yes | Yes | HTTP client from victim — ideal Mode B |
| ssh_failure | Yes | Yes | SSH client from victim |
| sql_injection | Yes | Yes | HTTP from victim |
| smb_login_failure | Yes | Conditional | SMB tools must exist on victim |
| port_sweep | Yes | Yes | Requires nmap/nc on victim |
| ldap_enumeration | Yes | Conditional | LDAP client on victim |
| kerberos_failure | Yes | Conditional | krb5 tools on victim |

`supports_scenario()` returns False when victim lacks required tools — Runner skips with `execution_provider_unsupported` meta event.

---

## 11. Anti-Patterns

| Anti-pattern | Why forbidden |
|--------------|---------------|
| Scenario imports webshell module | Execution-agnostic violation |
| Validation reads webshell stdout | ADR 0004 |
| Separate Event schema for remote | Path equality break |
| Default provider = webshell | Mode A must remain default |
| `dns_tunnel_webshell` duplicate scenario | One scenario, many providers |

---

## 12. Related Documents

- [EXECUTION_PROVIDER_FRAMEWORK.md](./EXECUTION_PROVIDER_FRAMEWORK.md)
- [EXECUTION_MODEL_SPEC.md](./EXECUTION_MODEL_SPEC.md)
- [WEBSHELL_PROVIDER_RISK_ANALYSIS.md](./WEBSHELL_PROVIDER_RISK_ANALYSIS.md)
- [WEBSHELL_PROVIDER_IMPLEMENTATION_PLAN.md](./WEBSHELL_PROVIDER_IMPLEMENTATION_PLAN.md)
- [ADR 0006 — Execution Provider Architecture](../adr/0006-execution-provider-architecture.md)
- [ADR 0007 — Webshell Execution Provider Architecture](../adr/0007-webshell-execution-provider-architecture.md)
