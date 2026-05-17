# Operational Recovery — XDR Lab Appliance

Practical recovery flows for **scenarios**, **CALDERA agents**, **libvirt
state**, and **OVS mirror** drift. All steps preserve existing IP/port
contracts and schemas.

---

## 1. Recover from failed scenario runs

1. **Stop CALDERA side effects**  
   `aella_cli lab scenario stop`  
   Confirms HTTP finish where possible; review stderr summary and
   `runtime/state/scenario.json` (`last_live_run`, `stop_outcome`).

2. **Read structured history**  
   `tail -n 120 logs/caldera-orchestration.jsonl`  
   Filter for `scenario_live_run_failed`, `scenario_preflight_failed`, or
   warnings documented in `docs/caldera-integration.md` §9.

3. **Preflight again without mutations**  
   `aella_cli lab scenario run <NAME> --snapshot-before --dry-run`  
   Fix bootstrap, atomic, agent, or adversary UUID issues before retry.

4. **Guest hygiene**  
   If abilities left persistent artifacts, follow pack `cleanup_notes` and
   CALDERA UI operation logs; optionally redeploy agents (`lab scenario agent remove` then `deploy`).

5. **Disk rewind**  
   If `--snapshot-before` created a known-good point, see §5.

---

## 2. Recover from stale CALDERA agents

Symptoms: agents show `dead` / duplicate paws / wrong host facts in
`lab scenario agent status`.

1. **CALDERA UI** — remove or retire stale agents when safe.
2. **Guests** — stop Sandcat processes (`docs/caldera-integration.md` §10).
3. **Redeploy** — `aella_cli lab scenario agent remove` then
   `aella_cli lab scenario agent deploy`.
4. **Revalidate** — `lab scenario bootstrap validate` and `agent status`.

---

## 3. Recover from orphan CALDERA operations

Symptoms: UI shows running operation after CLI crash; `scenario.json`
references an operation id that never completed.

1. **Preferred** — `aella_cli lab scenario stop` (idempotent finish call
   when state is coherent).
2. **UI / API** — manually finish or delete the operation in CALDERA when
   the CLI cannot see the id (document the server-side action in your runbook).
3. **Local state** — inspect `runtime/state/scenario.json` and
   `runtime/state/caldera.json`; cross-check `last_history` timestamps.
   Do **not** hand-edit JSON unless you understand merge semantics
   described in `docs/caldera-integration.md`.

---

## 4. Restore snapshots

1. **List** — `aella_cli lab snapshot list` or `aella_cli lab snapshot list <vm>`
2. **Revert** — `aella_cli lab snapshot revert <name>` (batch) or `aella_cli lab snapshot revert <vm> <name>`  
   Expect brief domain restarts; verify with `lab status all` and
   `lab validate all`.
3. **Windows (`windows-victim`)** — uses **external disk-only** snapshots
   (UEFI/pflash). Revert stops the VM, points the domain back at frozen
   `root.qcow2`, restores `nvram/OVMF_VARS.fd` from
   `runtime/windows-victim/snapshots/<name>/`, and removes the overlay.
   Linux VMs keep **internal** libvirt snapshots.
4. **If revert fails** — capture `virsh snapshot-list <vm> --tree` on the
   failing domain, ensure sufficient disk space, then retry. For
   `windows-victim`, also check `jq '.per_vm["windows-victim"].manifest'`
   under `runtime/state/snapshots.json`. As a last resort, restore from
   backup qcow2 (out of band).

---

## 5. Clean runtime state safely

**Non-destructive refresh** (preferred first steps):

- `aella_cli lab mirror verify` and `aella_cli lab nat verify`
- `bash "$XDR_LAB_MANAGER" mirror status` to refresh `mirror.json`
- `aella_cli lab scenario status --human` for narrative hints

**Destructive** (data loss on guest disks):

- `aella_cli lab stop <vm>` — power off only.
- `aella_cli lab destroy <vm>` — undefines domain and removes **runtime**
  qcow2 per engine rules (`docs/skills/kvm-runtime-skill.md`).
- `aella_cli lab cleanup` — **stop + destroy all** inventory VMs.

**Never** manually delete base images under `${XDR_BASE}/images/<vm>/`
unless you intend to re-download.

---

## 6. Ordering matrix (quick reference)

| Situation | First command | Typical follow-up |
| --- | --- | --- |
| Scenario hung | `lab scenario stop` | `scenario status --human`, JSONL tail |
| Agents wrong | `lab scenario agent remove` | `agent deploy`, `agent status` |
| Mirror empty | `aella_cli lab mirror verify` | `aella_cli lab mirror traffic`, `mirror status` (manager) |
| Guest corrupted | `lab snapshot revert <name>` | `lab validate <vm>` |
| Total reset | `lab cleanup` | `lab deploy all`, full checklist |

---

## 7. See also

- `docs/operational-maintenance.md` — cleanup vs stop semantics, retention.
- `docs/environment-sanity-checklist.md` — full validation pass.
- `docs/caldera-integration.md` — CALDERA-specific triage tables.
