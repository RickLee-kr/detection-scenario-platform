# Live Run Playbook — First Real CALDERA Adversary Run

Operator playbook for the **first end-to-end live adversary run** on the XDR
Lab Appliance. This document complements `docs/real-environment-bringup.md`
and `docs/caldera-integration.md` with a single ordered procedure, expected
artifacts, and a troubleshooting matrix. It does **not** change IP/port
contracts, schemas, or CLI behavior.

**Authoritative stack:** Ubuntu 24.04 → KVM/libvirt → **Open vSwitch `br0`**
→ **`ovs-net`** (`<virtualport type='openvswitch'/>`) → CALDERA → Sandcat →
Atomic Red Team (guest validation) → `runtime/state` + JSONL tracking.

**Policy:** English-only operational text; no fake success paths; no
automatic SIEM/EDR verdicts (manual operator review only).

---

## 0. Scope and assumptions

- CALDERA server is reachable from the appliance host at
  `config/caldera-lab.json::base_url`.
- API key is available via `XDR_CALDERA_API_KEY` and/or `api_key_file` (see
  `docs/caldera-integration.md` §3).
- `source config/paths.sh` and `XDR_BASE` / `XDR_ROOT` point at the active tree
  (repository or `/opt/xdr-lab`).

---

## 1. Environment preparation

| Step | Action | Pass criteria |
| --- | --- | --- |
| 1.1 | Host packages and groups per `README.md` §3 | `virsh`, `ovs-vsctl`, `aella_cli` usable |
| 1.2 | **`br0`** present as OVS bridge; `10.10.10.1/24` on host policy | `ovs-vsctl br-exists br0` |
| 1.3 | **`ovs-net`** active | `virsh net-info ovs-net` → `Active: yes` |
| 1.4 | Deploy/start lab VMs | `aella_cli lab deploy all` (idempotent); `aella_cli lab start all` as needed |
| 1.5 | Golden reverse-NAT | `aella_cli lab access` + `aella_cli lab nat verify` exit 0 |
| 1.6 | VM health | `aella_cli lab validate all` exit 0 when guests are ready |

---

## 2. CALDERA startup verification

Follow `docs/caldera-integration.md` §2.0 (systemd / manual / compose per your
topology).

| Step | Command / check | Pass criteria |
| --- | --- | --- |
| 2.1 | `systemctl status caldera.service` (if systemd install) | `active (running)` when applicable |
| 2.2 | HTTP probe | `curl` to `${base_url}/api/agents` with `KEY` header → `200` (or `401` proves path alive, key wrong) |
| 2.3 | UI | Browser login; **Plugins** shows `sandcat`, `stockpile`, and `atomic` if you rely on ART-backed abilities |
| 2.4 | Appliance batch | `aella_cli lab scenario bootstrap validate` | Exit 0 |

---

## 3. API key verification

| Step | Action | Pass criteria |
| --- | --- | --- |
| 3.1 | `export XDR_CALDERA_API_KEY='…'` or set `api_key_file` in `caldera-lab.json` | Key non-empty for non-dry deploy/run paths |
| 3.2 | `aella_cli lab scenario list` | HTTP success; merged scenario table prints |
| 3.3 | Optional direct probe | Same as §2.2; `200` confirms key alignment with `api_key_red` |

If key is missing, non-dry `scenario run` and `agent deploy` hit **preflight
exit 2** with `fatal_reason` such as `api_key_missing` in
`runtime/state/caldera.json::agent_deploy_last` (see
`docs/operator-troubleshooting-matrix.md`).

---

## 4. Adversary UUID validation

| Step | Action | Pass criteria |
| --- | --- | --- |
| 4.1 | CALDERA UI or REST: list adversaries | UUID copied for your lab-safe profile |
| 4.2 | Map UUID | `config/caldera-lab.json::scenarios.<scenario_id>.adversary_id` **or** pack `caldera.adversary_id` (pack wins when non-empty) |
| 4.3 | `aella_cli lab scenario list` | Target row shows **non-empty** merged `adversary_id` |
| 4.4 | `aella_cli lab scenario run <id> --snapshot-before --dry-run` | No `missing_adversary_id` block; preflight readable |

Repo packs may keep `adversary_id: null`; the **merged** value must still be
non-empty before live `scenario run` (constitution: no fake success).

---

## 5. Sandcat check-in validation

| Step | Action | Pass criteria |
| --- | --- | --- |
| 5.1 | `aella_cli lab scenario pack validate` | Zero errors |
| 5.2 | `aella_cli lab scenario atomic validate` | Exit 0 (guest ART readiness) |
| 5.3 | `aella_cli lab scenario agent deploy` (optional `--dry-run` first) | Bootstrap files under `runtime/caldera-agent/` |
| 5.4 | `aella_cli lab scenario agent status` | Expected roles `true` where required |
| 5.5 | CALDERA UI → Agents | `last_seen` fresh; paws match `agent_vm_map` substrings |

Windows without SSH may require manual `bootstrap-windows.ps1` per
`docs/caldera-integration.md` §5.4.

---

## 6. Snapshot-before workflow

| Step | Action | Pass criteria |
| --- | --- | --- |
| 6.1 | `aella_cli lab snapshot list` | Baseline understanding of existing snapshots |
| 6.2 | Optional manual | `aella_cli lab snapshot create pre-live-recon` (dry-run then live) |
| 6.3 | Live run flag | `aella_cli lab scenario run <id> --snapshot-before` creates batch name `pre-scenario-<UTC>` (see `docs/caldera-integration.md` §7) |
| 6.4 | On failure | `snapshot_before_failed` in JSONL; operation **not** created |

---

## 7. Mirror validation

| Step | Action | Pass criteria |
| --- | --- | --- |
| 7.1 | `aella_cli lab mirror apply` | Scoped mirror on **OVS `br0`** (spec 007) |
| 7.2 | `aella_cli lab mirror verify` | Exit 0 |
| 7.3 | Engine refresh | `bash "${XDR_LAB_MANAGER:-$XDR_BASE/scripts/xdr-lab-vm-manager.sh}" mirror status` |
| 7.4 | Optional | `aella_cli lab mirror traffic` — probe path (sensor SSH + host probe) |

Inspect `runtime/state/mirror.json`: `consistent: true`,
`mirror_exists: true`, `output_port_matches_sensor: true` when engine reports
success.

---

## 8. First recon execution (live)

**Minimum sequence:**

```bash
source config/paths.sh
export XDR_CALDERA_API_KEY='…'   # if not using api_key_file

aella_cli lab scenario pack validate
aella_cli lab scenario bootstrap validate
aella_cli lab scenario atomic validate
aella_cli lab scenario list
aella_cli lab scenario agent deploy
aella_cli lab scenario agent status
aella_cli lab mirror apply && aella_cli lab mirror verify
aella_cli lab scenario run recon --snapshot-before --dry-run
aella_cli lab scenario run recon --snapshot-before
aella_cli lab scenario status --human
# When finished observing:
aella_cli lab scenario stop
```

Replace `recon` with your `scenario_id` if different.

---

## 9. Expected `runtime/state` changes

| File | Expected change during/after live run |
| --- | --- |
| `scenario.json` | `status` transitions; `last_live_run` populated after submit; `last_history` updated on stop; optional `snapshot_before_name` |
| `caldera.json` | `active_caldera_operation_id` / `active_caldera_operation_name` during run; cleared or updated after `scenario stop` per server behavior |
| `snapshots.json` | New batch snapshot name when `--snapshot-before` succeeds |
| `mirror.json` | Refreshed when mirror verbs run; not necessarily rewritten on every `scenario run` |
| `nat.json` | Unchanged unless `nat verify` / `nat status` run |

Deep field reference: `docs/runtime-state-inspection.md`.

---

## 10. Expected JSONL events

Primary log: `logs/caldera-orchestration.jsonl` (append-only, JSON per line).

Typical **live** sequence (illustrative; exact counts vary):

1. `scenario_preflight_started` → `scenario_preflight_warning` (0..n) →
   `scenario_preflight_completed` or `scenario_preflight_failed`
2. On success: `scenario_run_ready`
3. `snapshot_before_requested` → `snapshot_before_created` or
   `snapshot_before_failed`
4. `scenario_live_run_started` → `scenario_operation_started` (dry + live
   patterns per `docs/caldera-integration.md` §9.3)
5. `scenario_live_run_submitted` (includes CALDERA operation id)
6. `scenario_post_run_review_recommended`
7. After `scenario stop`: `scenario_live_run_completed` or failure/stop
   counterparts

Inspect:

```bash
tail -n 200 logs/caldera-orchestration.jsonl | jq -r '.event'
jq -c 'select(.event | test("scenario_live_run|snapshot_before|preflight"))' \
  logs/caldera-orchestration.jsonl | tail -n 30
```

---

## 11. Expected CALDERA UI behavior

- **Operations:** New operation appears with the name printed in stdout JSON
  (`operation_name`).
- **Timeline:** Abilities move across agents that are **live** (Sandcat).
- **Agents:** Hosts show `last_seen` advancing during the run.
- **Finish:** After `scenario stop`, UI moves toward finished/cancelled state;
  if not, use UI/API completion per `docs/operational-recovery.md` §3.

---

## 12. Post-run cleanup

| Step | Action | Notes |
| --- | --- | --- |
| 12.1 | `aella_cli lab scenario stop` | Finishes CALDERA operation when id known |
| 12.2 | `aella_cli lab scenario status --human` | Post-run review block |
| 12.3 | Optional | `aella_cli lab scenario telemetry last` — manual checklist only |
| 12.4 | Optional | `aella_cli lab scenario agent remove` — removes matched agents from CALDERA |
| 12.5 | Evidence | Follow `docs/runtime-evidence-collection.md` before truncating logs |

---

## 13. Revert workflow

When `snapshot_before_result` indicates success and you need disk rewind:

```bash
aella_cli lab snapshot list
# Use the exact name recorded in scenario.json last_live_run / snapshot_before_name:
aella_cli lab snapshot revert <snapshot_name>
aella_cli lab status all
aella_cli lab validate all
```

`scenario stop` does **not** auto-revert disks (`docs/caldera-integration.md`
§7).

---

## 14. Troubleshooting matrix (quick)

| Symptom | First checks | Deep reference |
| --- | --- | --- |
| CALDERA HTTP failures | `bootstrap validate`, `curl` probes | `docs/caldera-integration.md` §2.0, §9.0 |
| `blocked` / adversary | `scenario list` merged UUID | §4 above; `docs/caldera-integration.md` §4.0 |
| Agents false | `agent deploy`, `host_substrings` | §5; `docs/caldera-integration.md` §5.6 |
| No mirror traffic | `mirror verify`, `mirror.json` | §7; spec 007 |
| Snapshot block | JSONL `snapshot_before_failed`, disk space | `docs/operational-recovery.md` §4 |
| Operation orphan | `scenario stop`, UI finish | `docs/operational-recovery.md` §3 |

Full matrix: **`docs/operator-troubleshooting-matrix.md`**.

---

## 15. Related documents

- `docs/caldera-integration.md` — CALDERA authority, JSONL catalog, state shapes
- `docs/runtime-evidence-collection.md` — evidence bundle workflow
- `docs/runtime-state-inspection.md` — JSON field interpretation
- `docs/real-environment-bringup.md` — first live lab sequence
- `docs/environment-sanity-checklist.md` — full sanity + §12 live recon
- `docs/release-candidate-checklist.md` — RC sign-off
- `docs/operational-recovery.md` — ordering matrix for failures
