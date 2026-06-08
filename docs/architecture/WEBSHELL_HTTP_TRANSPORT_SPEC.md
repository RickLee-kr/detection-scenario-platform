# Webshell Real HTTP Transport (W1)

**Status:** Implemented  
**Scope:** Production HTTP transport only — no provider execution, no detection inference

## Purpose

`RealHttpTransport` replaces live-network stubs with stdlib HTTP I/O while preserving the existing `WebshellTransport` contract.

## Components

| Component | Role |
|-----------|------|
| `RealHttpTransport` | `WebshellTransport` implementation with retry + timeout |
| `UrllibHttpBackend` | Default stdlib backend (urllib) |
| `HttpBackend` | Injectable protocol for unit tests |
| `MockHttpTransport` | Unchanged — tests only, no network |

## Operations

- `send_get` — GET with query params merged into URL
- `send_post` — POST with raw body
- `send_upload` — multipart POST (`remote_path` + file field)
- `download` — GET with `remote_path` query parameter
- `healthcheck` — delegates to `send_get`

## Error Mapping

| Condition | Exception / outcome |
|-----------|---------------------|
| Timeout | `WebshellTransportTimeoutError` |
| Retryable 5xx/429 exhausted | `WebshellTransportRetryExhaustedError` |
| HTTP 4xx / non-retryable | `TransportResponse` with `success=False` |
| Transport failure | `WebshellTransportError` |

## Out of Scope

- Command correlation, orchestration, validation runtime
- stdout/stderr parsing, grep validation, detection inference
- RunManager / Scenario / Event Store / Reporting changes

See [WEBSHELL_TRANSPORT_SPEC.md](./WEBSHELL_TRANSPORT_SPEC.md) for the base transport contract.
