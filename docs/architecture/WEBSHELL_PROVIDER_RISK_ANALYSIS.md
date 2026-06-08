# Webshell Execution Provider — Risk Analysis

**문서 버전:** 1.0.0  
**상태:** Design only — no implementation  
**Date:** 2026-06-06

---

## 1. Purpose

WebshellExecutionProvider 구현 전 **기술·보안·운영 리스크**를 식별하고 완화 전략을 문서화한다. 본 Phase는 architecture only — runtime 변경 없음.

---

## 2. JSP Compatibility

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| HTML response wrapping | Medium | Command output embedded in HTML; parsing fails | `JspFamilyAdapter.capture_stdout()` — marker-based extraction; golden-file tests per container |
| Servlet timeout | High | Long scenario runs killed by Tomcat | Tier `long` timeout; chunked execution for volume scenarios |
| `Runtime.exec` shell wrapping | Medium | Metacharacter stripping | Raw cmd style detection at healthcheck; payload encoding layer |
| No UDP socket | High | dns_tunnel raw UDP may fail | `supports_scenario()` false without relay; document DNS relay fallback |
| WAF/ModSecurity | Medium | Command parameters blocked | Lab WAF disable policy; encoded payload variants |
| Charset mismatch | Low | Non-UTF8 output corrupts JSONL | Explicit charset header; binary-safe base64 for bundles |

**Overall JSP compatibility:** Medium — viable for HTTP/TCP scenarios; DNS UDP requires relay or skip.

---

## 3. PHP Compatibility

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| `disable_functions` | High | `system`, `exec`, `shell_exec` disabled | Healthcheck probes available functions; skip if none |
| `open_basedir` | Medium | Upload/write outside allowed paths | Restrict stub path to `/tmp`; healthcheck write probe |
| `max_execution_time` | High | Scenario truncated mid-run | `set_time_limit` in stub if permitted; else chunk scenario |
| PHP warnings in output | Medium | Pollute stdout capture | `capture_stdout()` strips warning prefixes |
| Version fragmentation | Low | PHP 5.x vs 8.x syntax | Stub targets Python3 primary; PHP as bootstrap only |

**Overall PHP compatibility:** Medium-High for Linux victims with permissive PHP config; preflight healthcheck essential.

---

## 4. ASPX Compatibility

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| Windows vs Linux semantics | High | Path, shell, tool differences | Separate stub variants; scenario capability matrix |
| AppPool identity | Medium | Limited filesystem/network access | Healthcheck as AppPool user; document permissions |
| AMSI/Defender | High | Executor script blocked | Lab policy: exclusion for `/tmp/dsp_stub/`; signed stub option (future) |
| PowerShell vs cmd | Medium | Command wrapping differences | `AspxFamilyAdapter` detects shell; consistent wrapper |
| ViewState overhead | Low | Large POST bodies | Prefer POST for execute; minimize ViewState-dependent flows |

**Overall ASPX compatibility:** Medium — Windows victim scenarios only; higher operational setup cost.

---

## 5. Response Parsing

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| Family misdetection | Medium | Generic adapter used incorrectly | Multi-probe healthcheck; manual override in config |
| Exit code marker missing | Medium | Cannot determine remote exit status | Convention: `__EXIT_CODE:N` suffix; legacy stellar_poc pattern |
| Binary output | Low | Corrupts text parsers | Base64/gzip pipeline for downloads |
| Response truncation | High | Incomplete event bundle | Post-download size/hash verification vs remote `wc -c` |
| HTML entity encoding | Medium | `&lt;` corrupts JSON | Decode HTML entities in `capture_stdout()` |
| Concurrent response mixing | Low | Session confusion | Cookie/session isolation per run_id |

**Parsing strategy:** Golden-file test matrix per family × sample webshell; never parse stdout for validation.

---

## 6. Network Latency

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| Per-command RTT | High | N commands × latency for volume scenarios | Batch commands in single script; minimize round-trips |
| Upload throughput | Medium | Large stub slow on high-latency link | gzip compression; chunked upload |
| Sync download delay | Medium | Event bundle wait after execute | Poll remote file existence with backoff |
| TLS handshake overhead | Low | Repeated connections | HTTP keep-alive / session reuse where safe |
| Proxy timeout | Medium | Corporate proxy kills long POST | Configurable timeout tiers; document proxy limits |

**Latency budget (guideline):**

| Scenario class | Max acceptable overhead vs local |
|----------------|----------------------------------|
| Low volume (ssh_failure) | 2–5× |
| Medium (http_followup) | 3–10× |
| High (dns_tunnel) | 10–30× — may require relay or local fallback |

---

## 7. Event Synchronization

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| Partial bundle write | High | Crash mid-scenario leaves incomplete JSONL | Stub writes atomically (temp + rename); sync validates line-by-line |
| Schema version mismatch | Medium | Remote stub older than DSP | Bundle manifest includes `schema_version`; reject on mismatch |
| Duplicate append | Medium | Re-run sync double-counts | Bridge idempotency key per event UUID |
| Clock skew | Low | Timestamp ordering in Event Store | Preserve remote timestamps; document in metadata |
| Zero events synced | High | Silent remote failure | `execution_sync_failed` meta event; validation applies SOT_EMPTY |
| Large bundle memory | Medium | OOM on DSP Host import | Stream JSONL line-by-line; size cap per run |

**Recommended sync model:** Option C (bundle download) — see [WEBSHELL_PROVIDER_ARCHITECTURE.md §6](./WEBSHELL_PROVIDER_ARCHITECTURE.md).

---

## 8. Security Risks

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| Command injection | **Critical** | Operator/config input in command string | Parameterized commands; allowlist; no string concat from untrusted input |
| Credential leakage | **Critical** | URL/token in logs, reports | Redaction in all outputs; secrets via env only |
| Arbitrary file upload | **Critical** | Upload outside stub directory | Path restriction `/tmp/dsp_stub/<run_id>/` |
| Webshell URL exposure | High | Report/evidence contains full URL | Hash or redact query params in reports |
| MITM on HTTP | High | Lab HTTP without TLS | HTTPS default; explicit `--allow-insecure-http` flag |
| Persistent backdoor | **Critical** | Stub left on victim | Mandatory cleanup policy; audit log of staged files |
| Lateral movement | **Critical** | Scenario executor reaches non-lab hosts | Target Provider lab allowlist; network segmentation |

---

## 9. Operational Risks

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| Webshell unavailable mid-run | High | Victim rebooted, WAF blocked | Preflight healthcheck; fail with clear meta event |
| Wrong family adapter | Medium | Commands silently fail | Healthcheck family detection + manual override |
| Operator misconfiguration | Medium | Wrong URL, expired cookie | Config validation at `prepare()`; CONFIG_ERROR exit |
| Debug difficulty | Medium | Remote failure opaque | Transport meta events with exit code, HTTP status, duration |
| Lab cleanup incomplete | Medium | Disk fill on victim | cleanup() with manifest of staged paths |
| Scenario × family matrix gaps | Low | Operator expects unsupported combo | `supports_scenario()` + clear skip reason in report |
| Regression vs local parity | Medium | Remote run produces different event counts | Path equality test suite per scenario × webshell family |

---

## 10. Risk Summary Matrix

| Area | Overall Risk | Go/No-Go |
|------|--------------|----------|
| JSP compatibility | Medium | Go with relay fallback for UDP |
| PHP compatibility | Medium | Go with healthcheck gates |
| ASPX compatibility | Medium-High | Go for Windows lab subset |
| Response parsing | Medium | Go with golden-file tests |
| Network latency | Medium-High | Go with batching + timeout tiers |
| Event synchronization | Medium | Go — Option C recommended |
| Security | **High** | Go **only** with lab envelope + opt-in |
| Operational | Medium | Go with runbook + audit events |

---

## 11. Pre-Implementation Requirements

Before Phase X+1 code:

1. Lab webshell instances (JSP, PHP, ASPX) available for golden-file testing
2. Safety Envelope document updated with webshell allowlist
3. Operator runbook: credential rotation, cleanup verification
4. Path equality test plan: local vs webshell dry-run parity per scenario

---

## 12. Related Documents

- [WEBSHELL_PROVIDER_ARCHITECTURE.md](./WEBSHELL_PROVIDER_ARCHITECTURE.md)
- [WEBSHELL_PROVIDER_IMPLEMENTATION_PLAN.md](./WEBSHELL_PROVIDER_IMPLEMENTATION_PLAN.md)
- [ADR 0007 — Webshell Execution Provider Architecture](../adr/0007-webshell-execution-provider-architecture.md)
