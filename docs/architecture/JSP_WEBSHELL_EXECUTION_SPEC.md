# JSP Webshell Execution (W2A)

**Status:** Implemented  
**Scope:** JSP command/upload/download via existing provider/runtime/transport stack

## Flow

```
JspWebshellProvider
    → JspWebshellRuntime
    → RealHttpTransport (or MockHttpTransport in tests)
    → shell.jsp
```

## JSP Shell Format

| Operation | HTTP | Payload |
|-----------|------|---------|
| Command (small) | GET | `shell.jsp?cmd=whoami` |
| Command (large) | POST | `cmd=whoami` (`application/x-www-form-urlencoded`) |
| Upload | POST multipart | `remote_path` + `file` fields (transport contract) |
| Download | GET | `?remote_path=/path/to/file` (transport contract) |

Command arguments are joined: `cmd=echo hello world`.

## Execution Result Rules

`CommandResult.execution_metadata` contains transport fields only:

- `transport_status`, `transport_method`, `transport_response_size`, `delivery_only`

HTTP 200 means **transport delivery succeeded**, not command or attack success. Response body is **not** parsed into stdout/stderr.

## Limitations

- Upload/download use the same `webshell_url` as commands (no separate `upload.jsp` endpoint yet).
- Response HTML is not parsed; family-specific output extraction is out of scope.

## Out of Scope

PHP, ASPX, Remote Scenario Runner, CLI provider selection, detection/validation/correlation logic.
