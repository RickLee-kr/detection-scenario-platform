# Spec 012 — Runtime Logging

> Binds to: constitution §7, M-8. Cross-cuts every other spec.

## 1. Goal

Define the **logging contract** between the appliance and its
operator (and, downstream, any SIEM). Logs are the project's
primary observability surface; their shape and stability are part
of the appliance contract.

## 2. Architecture

```
L1 (Python: aella_cli)
   └─ logger "aella_cli" (stderr)
        - JSON-friendly records emitted via LOG.info("structured_log", extra={...})
        - @log_command decorator: command_enter / command_exit
        - shell_cmd_exec: shell_cmd_exec / shell_cmd_exec_failed
        - handler errors: handler_runtime_error / lab_invalid_vm / lab_manager_missing
        - inventory parse: lab_config_read_failed

L2 (Bash: /opt/xdr-lab/scripts/*.sh)
   └─ log_structured <LEVEL> <message>   (writes JSON line to a per-script log)
        /opt/xdr-lab/logs/vm-manager.log         (xdr-lab-vm-manager.sh)
        /opt/xdr-lab/logs/ovs-manager.log        (future, spec 007)
        /opt/xdr-lab/logs/nat-manager.log        (future, spec 010)
        /opt/xdr-lab/logs/snapshot-manager.log   (future, spec 009)
        /opt/xdr-lab/logs/scenario-runner.log    (future, spec 008)
```

Downstream:

- Operator inspects stderr for L1 events and tail the files
  under `/opt/xdr-lab/logs/` for L2 events.
- A future log shipper (rsyslog/journald → SIEM) can ingest
  both streams; the JSON shape MUST remain stable enough for
  schema-on-read parsing.

## 3. Component Responsibilities

### 3.1 L1 — Python structured logging

- `_configure_logging()` installs a single root stream handler
  with `INFO` level. The aella_cli logger is also `INFO`.
- Records are emitted by `LOG.info("structured_log",
  extra={...})`. The `extra` payload carries:
  - `event`  — required, snake_case verb (e.g. `command_enter`,
              `shell_cmd_exec`, `handler_runtime_error`,
              `lab_invalid_vm`).
  - other fields specific to the event.
- `@log_command` MUST wrap every handler. It emits:
  - `command_enter`  — fields: `event`, `command`.
  - `command_exit`   — fields: `event`, `command`,
                       `duration_sec` (rounded to 4 decimals).
- `shell_cmd_exec` MUST emit:
  - `shell_cmd_exec` on entry — fields: `event`, `argv` (list).
  - `shell_cmd_exec_failed` on `check=True` failure — fields:
    `event`, `argv`, `rc`, `stderr_preview` (bounded to 2000
    chars).
- Errors from `main` MUST emit `handler_runtime_error` with
  `error` (`str(exc)`).

L1 MUST NOT emit unstructured `print()` to stderr from inside a
handler. The exception is `_emit_streams` which forwards child
output verbatim — that is data, not log.

### 3.2 L2 — Bash structured logging

Every L2 script MUST provide (or share via a future common
include):

```bash
log_structured() {
  local level="$1"
  shift
  python3 - "${level}" "$*" <<'PY' >>"${LOGD}/<script-name>.log"
import json, sys, datetime
level, msg = sys.argv[1], sys.argv[2]
rec = {
    "ts": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    "level": level,
    "msg": msg,
}
print(json.dumps(rec, ensure_ascii=False))
PY
}
```

Today's `xdr-lab-vm-manager.sh` follows exactly this shape.
Future scripts MUST follow it.

Rules:

- `level` is one of `DEBUG`, `INFO`, `WARN`, `ERROR`.
- `msg` is a single line. Multi-token data MUST be encoded as
  space-separated `key=value` pairs (e.g.
  `deploy_vm_begin vm=windows-victim type=windows`). Quote
  values that may contain spaces.
- The first token of `msg` is the event name (mirrors L1's
  `event` field) so parsers can pivot on it.
- Lines are appended to `${LOGD}/<script-name>.log`. The script
  ensures `${LOGD}` exists via `mkdir -p` at startup.
- Logs are **not rotated by the script**. Rotation is operator-
  side (logrotate config in the appliance image). The script
  MUST tolerate the file being rotated under it.

### 3.3 Cross-cutting: event taxonomy

Each spec defines its own events, but the **lifecycle pattern**
is uniform:

- `<verb>_begin` — about to mutate.
- `<verb>_end`   — mutation succeeded.
- `<verb>_failed` — mutation failed.
- `<verb>_idempotent_<state>` — no-op path; describe the state.
- `<verb>_skip_<reason>` — per-target skip in a batch.

Examples from the current runtime (preserved):

- `deploy_vm_begin`, `deploy_vm_end`,
  `deploy_vm_idempotent_exists`, `deploy_vm_virt_install`,
  `deploy_vm_network_hints`.
- `download_vm_image_begin`, `download_vm_image_end`.
- `start_vm`, `stop_vm`, `destroy_vm`.
- `start_skip_missing`.
- `validate_sensor_deployment virsh_ok|virsh_missing|ping_ok|
  …_ping_failed`.
- `cli action=… target=… nodownload=…`.

Future scripts MUST register their event names in their
respective specs (specs 007–010) so the taxonomy stays
auditable.

## 4. Operational Assumptions

- The operator can read stderr from `aella_cli` (or capture it
  via a wrapper).
- The operator can read `/opt/xdr-lab/logs/` (mode 0644 files,
  the script's umask is 022).
- Time is UTC. Hosts maintain accurate time via NTP/chrony.

## 5. Runtime Flow

```
aella_cli lab deploy windows-victim
  L1 stderr ← 2026-05-12T07:00:01 INFO structured_log
              extra={event=command_enter, command=cmd_lab_deploy}
  L1 stderr ← 2026-05-12T07:00:01 INFO structured_log
              extra={event=shell_cmd_exec, argv=[…/xdr-lab-vm-manager.sh, deploy, windows-victim]}

  L2 vm-manager.log ← {"ts":"2026-05-12T07:00:01Z","level":"INFO","msg":"cli action=deploy target=windows-victim nodownload=0"}
  L2 vm-manager.log ← {"ts":"…","level":"INFO","msg":"deploy_vm_begin vm=windows-victim type=windows"}
  L2 vm-manager.log ← {"ts":"…","level":"INFO","msg":"deploy_vm_virt_install vm=windows-victim"}
  L2 vm-manager.log ← {"ts":"…","level":"INFO","msg":"deploy_vm_network_hints vm=windows-victim internal_ip=10.10.10.30 nat={…}"}
  L2 vm-manager.log ← {"ts":"…","level":"INFO","msg":"deploy_vm_end vm=windows-victim"}

  L1 stderr ← 2026-05-12T07:00:33 INFO structured_log
              extra={event=command_exit, command=cmd_lab_deploy, duration_sec=31.7421}
```

## 6. Deployment Logs (M-7 / M-8)

- Every `deploy` produces, at minimum, a `deploy_vm_begin`,
  one of {`deploy_vm_end`, `deploy_vm_idempotent_exists`}, and
  a network-hints record.
- Image download produces matching `_begin` / `_end` events.
- Sensor-specific events are documented in spec 004 §5 and
  §3.4.

## 7. Runtime Logs

- `start_vm`, `stop_vm`, `destroy_vm` produce a single-line
  event with `vm=<name>` and, on skip, a `_skip_<reason>`
  event.
- `status` produces no log (read-only).

## 8. Mirror Logs (spec 007)

When implemented, `xdr-lab-ovs-manager.sh` MUST emit:

- `mirror_enable_begin`, `mirror_enable_end`,
  `mirror_disable_begin`, `mirror_disable_end`.
- `mirror_port_discovered vm=… iface=…`.
- `mirror_source_added vm=… iface=…`,
  `mirror_source_removed vm=… iface=…`,
  `mirror_source_present vm=… iface=…`.
- `mirror_verify_ok` / `mirror_verify_failed details=…`.

## 8a. Reverse-NAT Logs (spec 010)

The read-only Golden-Image validator (current implementation; see
spec 010 §14) emits via `xdr-lab-vm-manager.sh nat <verify|status>`:

- `cli action=nat sub=<verify|status> state_path=…` — L2 router
  entry (mirrors the `mirror` dispatch shape).
- `nat_verify_begin state_path=…` /
  `nat_verify_ok state_path=…` /
  `nat_verify_failed iptables_readable=… masquerade_present=…
   forward_present=… web_console_listen=… missing=[…]` — same fields;
   additionally emits a short **stderr** remediation block (Golden
   contract recap + per-defect hints); the structured log line is
   unchanged for SIEM parsers.
- `nat_status_begin state_path=…` /
  `nat_status_end state_path=…` /
  `nat_status_refresh_failed state_path=…` (best-effort refresh
  failure; the prior `nat.json` is still printed).
- `nat_helper_missing path=…` — `nat_state.py` not installed.

When the future mutating manager from spec 010 §3.2 ships, it
introduces `nat_enable_begin`/`_end`, `nat_disable_begin`/`_end`,
`nat_port_collision external=… vms=[…]`, and
`nat_service_unknown service=… vm=…`. The verify/status events
above MUST remain stable so SIEM parsers do not regress.

## 9. Scenario Logs (spec 008)

When implemented, `xdr-lab-scenario-runner.sh` MUST emit:

- `scenario_run_begin id=… engine=…`.
- `scenario_preflight_ok id=…` / `scenario_preflight_failed
  id=… reason=…`.
- `snapshot_pre_taken id=… vm=… snap=…`.
- `engine_step_begin id=… step=…` /
  `engine_step_end id=… step=… result=…`.
- `snapshot_post_taken id=… vm=… snap=…`.
- `scenario_run_end id=… result=ok|failed`.

## 10. Future SIEM Export Philosophy

- The JSON shape `{ts, level, msg}` for L2 and the Python
  logger's `extra` dict for L1 are both **forward-compatible**
  with a flattening export. A future shipper translates them
  into a uniform schema; the project does NOT build that
  shipper.
- `msg` in L2 uses `event_name key=value …` so a SIEM
  parser can pivot on the first token.
- Field names MUST be stable. Renaming `vm` to `vm_name` is a
  breaking change requiring a spec amendment and a coordinated
  shipper update.
- Operators MAY add a sidecar tool that wraps `aella_cli` and
  re-emits L1 events to journald with explicit fields. That is
  out of scope for this project.

## 11. Failure Handling Philosophy

- Logging MUST NEVER fail the operation. If `log_structured`
  cannot write (disk full, permission), the script tolerates
  it (best-effort append) and continues. The operator's
  out-of-band monitoring catches the symptom.
- L1 MUST NOT raise from inside `@log_command` or
  `shell_cmd_exec` due to logging failure. Logging exceptions
  are swallowed silently by the standard library's logging
  config.

## 12. Recovery Philosophy

- A corrupt log file is operator-recovered (rotate it out;
  `xdr-lab-vm-manager.sh` will recreate it on next write).
- Lost L2 logs do not break the system; L1 stderr still
  carries the high-level trail. Operators are encouraged to
  capture stderr too (e.g. `aella_cli … 2>&1 | tee -a
  /var/log/aella-cli.log`).

## 13. Forbidden Implementation Patterns

- `print(...)` debug output in committed L1 code paths.
- Unstructured `echo "..."` log lines in L2 outside of `usage`
  and verbatim operator-facing help text.
- Logging plaintext credentials, tokens, or guest passwords
  (constitution P-8).
- Inserting log fields that include unbounded user input
  without truncation (see `stderr_preview` cap at 2000 chars).
- Mutating log files in place (`sed -i` etc.). Logs are
  append-only.
- Replacing the JSON envelope with key-value plaintext "for
  readability". The envelope is the contract.

## 14. Validation Philosophy

A logging-related change is valid only if:

1. Every existing event name continues to appear with the same
   shape (field names, level).
2. New events follow the `_begin`/`_end`/`_failed` pattern
   where applicable.
3. No event name is reused with a different schema.
4. `aella_cli --help` works without writing to any log path.
5. Logs remain JSON-parseable line-by-line for L2 and
   `extra`-parseable for L1.
6. `stderr_preview` truncation rule is preserved.
