# Runtime State Inspection — JSON Artifacts

Guide to interpreting **`runtime/state/*.json`** on the XDR Lab Appliance.
These files are **operator-facing derived state** (not a telemetry
pipeline). Paths honor `XDR_RUNTIME_STATE_DIR` when set; default is
`${XDR_ROOT}/runtime/state/`.

**Additive-only expectation:** New fields MAY appear across releases; do
not rely on absence of unknown keys. Do not hand-edit unless you understand
merge semantics (`docs/caldera-integration.md` §9.0a).

---

## 1. Common conventions

| Topic | Convention |
| --- | --- |
| Timestamps | Many fields use UTC with `Z` suffix (`*_utc`, `updated_utc`, `ts`) |
| Sorting | Writers typically use sorted object keys and 2-space indent |
| Booleans | JSON native `true` / `false` |
| Schema version | `caldera.json` may include `schema_version` for forward compatibility |

---

## 2. `scenario.json`

**Role:** Last-known scenario orchestration view: engine, status, agents
matrix, history, live-run snapshot, errors, telemetry review fields.

### 2.1 Frequently used keys

| Key | Meaning |
| --- | --- |
| `engine` | Typically `"caldera"` |
| `status` | `idle`, `running`, `starting`, `dry_run`, `stopped`, `failed`, `blocked`, … |
| `current_operation` / `scenario_name` | Active or last scenario id (e.g. `recon`) |
| `agents` | Map of lab role → boolean Sandcat match from last refresh |
| `last_error` | Human-readable last failure string or `null` |
| `last_history` | Summary of last completed session (durations, operation ids when present) |
| `last_live_run` | Structured block after live submit — operation id, preflight snapshot, telemetry snapshots |
| `telemetry_review_status` | Operator workflow signal (`not_set`, `pending_operator_review`, …) |
| `telemetry_review_notes` | Free-form operator notes (English) |
| `snapshot_before_name` | Libvirt batch snapshot label when `--snapshot-before` used |

### 2.2 Interpreting `status`

| status | Typical meaning |
| --- | --- |
| `blocked` | Preflight gate — often missing merged `adversary_id` |
| `failed` | HTTP/URL/401 or runtime exception paths |
| `running` | Operation submitted; awaiting `scenario stop` or server finish |
| `dry_run` | Last `scenario run --dry-run` completed without live PUT |

### 2.3 Troubleshooting usage

```bash
jq '{status,last_error,current_operation,agents,snapshot_before_name}' runtime/state/scenario.json
jq '.last_live_run' runtime/state/scenario.json
```

Pair with `aella_cli lab scenario status --human` for narrative hints.

---

## 3. `caldera.json`

**Role:** CALDERA server reachability, active operation echo, bootstrap /
atomic validate audit blocks, last agent deploy rollup.

### 3.1 Frequently used keys

| Key | Meaning |
| --- | --- |
| `base_url` | Configured REST base |
| `http_reachable` | Last probe saw HTTP success class |
| `last_probe_utc` | When reachability was tested |
| `active_caldera_operation_id` | String id when an operation is active/echoed |
| `active_caldera_operation_name` | Friendly operation name when present |
| `plugins` / `atomic_red_team` | **Operator memo** from `caldera-lab.json` (not authoritative for server) |
| `server_bootstrap` | Bootstrap validate snapshot + timestamps |
| `atomic_red_team_validate_last` | Last `atomic validate` report |
| `agent_deploy_last` | Exit code, `fatal_preflight`, `fatal_reason`, per-VM rows |
| `agent_matrix_last` | Same shape as `scenario.json::agents` after refresh |

### 3.2 `agent_deploy_last.fatal_reason` values (examples)

Includes `api_key_missing`, `caldera_unreachable` (and similar) — see
`docs/operator-troubleshooting-matrix.md`.

### 3.3 Troubleshooting usage

```bash
jq '{http_reachable,last_probe_utc,active_caldera_operation_id,active_caldera_operation_name,last_error}' runtime/state/caldera.json
jq '.agent_deploy_last' runtime/state/caldera.json
```

---

## 4. `mirror.json`

**Role:** OVS mirror reconciliation on **`br0`**: existence, output port,
consistency flags (spec 007).

### 4.1 Frequently used keys

| Key | Meaning |
| --- | --- |
| `bridge` | Expected OVS bridge (typically `br0`) |
| `mirror_name` | Named mirror object (e.g. `mirror-to-sensor`) |
| `mirror_exists` | Mirror row present in OVS |
| `sensor_vm` | Sensor domain name from inventory |
| `sensor_interface` | Discovered tap / vnet for sensor on `br0` |
| `output_port_name` | Mirror destination port |
| `output_port_matches_sensor` | Boolean consistency |
| `consistent` | **Aggregate** health for operator gating |
| `last_verified_time` | Last successful write / verify cycle |
| `last_applied_time` | When apply path last touched consistent state |

### 4.2 Troubleshooting usage

```bash
jq '{consistent,mirror_exists,output_port_name,sensor_interface,last_verified_time}' runtime/state/mirror.json
```

If `consistent` is `false`, run `aella_cli lab mirror verify` and read stderr
transcript; never use destructive OVS resets (constitution §11).

---

## 5. `nat.json`

**Role:** Golden reverse-NAT contract vs observed iptables / listener state
(`nat_state.py`).

### 5.1 Frequently used keys

| Key | Meaning |
| --- | --- |
| `consistent` | Overall pass/fail for documented DNAT map |
| `iptables_readable` | Could read iptables state |
| `dnat` | Expected vs observed rows (shape varies by version — treat additive) |
| `missing` | List or structured description of gaps |
| `ts` / `updated_utc` | Verification timestamp |

### 5.2 Troubleshooting usage

```bash
jq '{consistent,missing,ts}' runtime/state/nat.json
aella_cli lab nat verify 2>&1 | tee /tmp/nat-verify.txt
```

---

## 6. `snapshots.json`

**Role:** Libvirt snapshot batch catalog maintained by `snapshot_state.py`.

**Snapshot modes (auto-selected per domain):**

| VM type | Libvirt mode | Notes |
| --- | --- | --- |
| Linux / BIOS (e.g. `victim-linux`, `sensor-vm`) | **internal** | `virsh snapshot-create-as` (domain snapshot) |
| UEFI / pflash (e.g. `windows-victim`) | **external_disk** | `virsh snapshot-create-as --disk-only`; base `root.qcow2` stays read-only; overlay `root.<name>`; NVRAM copied under `runtime/<vm>/snapshots/<name>/` |

Internal qcow2 snapshots are **not supported** on pflash firmware; the manager detects `loader type='pflash'` and switches automatically.

### 6.1 Frequently used keys

| Key | Meaning |
| --- | --- |
| `per_vm` | Per-domain snapshot lists / metadata |
| `per_vm.<vm>.snapshot_policy` | `internal` or `external_disk` |
| `per_vm.<vm>.manifest` | External snapshot paths (overlay, base, nvram backup) |
| `last_batch` | Last batch operation summary when present |
| `history` | Optional bounded history |
| `updated_utc` | Last catalog refresh |

### 6.2 Troubleshooting usage

```bash
jq 'keys' runtime/state/snapshots.json
aella_cli lab snapshot list
aella_cli lab snapshot create windows-victim test-delete
aella_cli lab snapshot delete windows-victim test-delete
```

Cross-check `scenario.json::snapshot_before_name` exists here before revert.

---

## 7. Timestamp interpretation

- Prefer **UTC** when correlating JSONL `ts` with `scenario.json` / UI
  screenshots.
- CALDERA UI may display local timezone — convert explicitly in reports.
- `last_seen` on agents is server-relative; compare skew with appliance `date -u`.

---

## 8. Additive-only schema expectations

When upgrading packages or pulling new commits:

1. **Unknown keys** — log-only; do not fail manual `jq` pipelines if extra
   keys appear.
2. **Renamed removed keys** — should not happen without `schema_version` bump
   and release notes (`docs/packaging-guidance.md` §13).
3. **JSONL `event` names** — stable strings; new events arrive additively
   (constitution logging philosophy).

---

## 9. Related documents

- `docs/caldera-integration.md` §9 — canonical tables and JSONL catalog
- `docs/runtime-evidence-collection.md` — bundle workflow
- `docs/operator-troubleshooting-matrix.md` — failure codes
- `docs/specs/012-runtime-logging/spec.md` — logging governance
