# Spec 009 — Snapshot Runtime (Reserved)

> Binds to: constitution §5, §6, M-5, M-15, M-16, P-14. Cross-cuts
> spec 008 (scenarios) and spec 011 (operational safety).
> **Status: Reserved. No runtime code permitted yet.**

## 1. Goal

Define the **snapshot/revert lifecycle** for lab VMs so attack
scenarios can run, leave evidence, and then be rewound to a known
good state. Snapshots MUST preserve VM consistency, MUST be
inventory-scoped, and MUST be observable.

## 2. Architecture

Snapshot operations live in a dedicated L2 script:

```
xdr-lab-snapshot-manager.sh   (future)
  invoked by aella_cli snapshot <verb> (spec 005)
  uses virsh snapshot-* primitives
  emits structured logs to /opt/xdr-lab/logs/snapshot-manager.log
```

Snapshot strategy: **internal qcow2 snapshots** via
`virsh snapshot-create-as --disk-only` (with appropriate flags)
**or** `virsh snapshot-create-as` for full domain snapshots. The
choice per VM is declarative (see §3.1).

```
/opt/xdr-lab/runtime/
  ├── <vm>-runtime.qcow2          (running disk, internal snapshots)
  └── <vm>-snapshots.json         (sidecar metadata: id, created, label, parent)
```

The sidecar is the lab's authoritative snapshot index for human
operators; the libvirt store is the technical truth.

## 3. Component Responsibilities

### 3.1 L4 — declarative state (proposed)

Add to `lab-vms.json::vms.<name>`:

```
"snapshot_policy": {
  "mode": "domain" | "disk_only",
  "max_retained": 5,
  "label_prefix": "auto"
}
```

`mode` choices:

- `"domain"` — `virsh snapshot-create-as` (memory + disk); slower
  but resumes exactly. Required for VMs running stateful
  scenario engines.
- `"disk_only"` — `virsh snapshot-create-as --disk-only`;
  faster, requires VM be quiesced or accept disk-only revert
  semantics.

If absent: default `disk_only` with `max_retained: 3`.

### 3.2 L2 — `xdr-lab-snapshot-manager.sh` (future)

Verbs:

- `take <vm> [--label <label>]`        — create a new snapshot
- `list <vm|all>`                       — list snapshots and labels
- `revert <vm> <snapshot_id_or_label>` — revert to a snapshot
- `delete <vm> <snapshot_id_or_label>` — delete a snapshot
- `prune <vm>`                          — enforce `max_retained`
- `validate <vm>`                       — sanity check sidecar vs
                                          libvirt state

Each verb:

- Validates `<vm>` is in `lab-vms.json::vms`.
- Validates the snapshot id/label exists for revert/delete
  before issuing destructive commands.
- Emits structured logs (`snapshot_take_begin`,
  `snapshot_take_end`, `snapshot_revert_begin`,
  `snapshot_revert_end`, etc.).
- Updates the sidecar atomically (write to
  `<vm>-snapshots.json.tmp` then `mv`).

### 3.3 L1 — `aella_cli snapshot …` (future)

```
aella_cli snapshot take    <vm> [--label LABEL]
aella_cli snapshot list    <vm|all>
aella_cli snapshot revert  <vm> <snap_id_or_label>
aella_cli snapshot delete  <vm> <snap_id_or_label>
aella_cli snapshot prune   <vm>
aella_cli snapshot validate <vm>
```

Per spec 005 conventions.

## 4. Operational Assumptions

- qcow2 is the only supported disk format for lab VMs.
- Sufficient free space exists under `/opt/xdr-lab/runtime/` for
  the configured `max_retained` snapshots per VM.
- The guest OS is either running (for `domain` snapshots) or
  shut off (for `disk_only` taken offline) at the time of the
  snapshot. The manager MUST refuse a `domain` snapshot when
  memory snapshot is impossible (live migration unsupported,
  etc.) and explain why.

## 5. Snapshot Lifecycle

```
take:
  ├─ assert vm in inventory
  ├─ assert vm defined (virsh dominfo)
  ├─ pick mode from snapshot_policy
  ├─ generate id (UTC timestamp) + label
  ├─ virsh snapshot-create-as …
  ├─ append to sidecar
  └─ enforce max_retained (delete oldest auto labels)

revert:
  ├─ assert vm in inventory and defined
  ├─ resolve snapshot by id or label
  ├─ confirm operator intent (no auto-revert without explicit flag in CLI)
  ├─ virsh snapshot-revert <vm> <snap>
  ├─ post-revert: log domain state (running / shut off)
  └─ update sidecar.last_reverted_to = snap

delete:
  ├─ assert vm and snap exist
  ├─ virsh snapshot-delete <vm> <snap>
  └─ update sidecar

prune:
  ├─ list auto-labeled snapshots
  ├─ keep newest max_retained
  └─ delete the rest

validate:
  ├─ list libvirt snapshots for vm
  ├─ list sidecar snapshots
  ├─ report differences (libvirt has snap that sidecar doesn't, vice versa)
  └─ exit non-zero if differences exist
```

## 6. VM Consistency Guarantees

- Snapshots are taken **atomically** per VM. Multi-VM
  "consistent group" snapshots are out of scope for the
  current spec (would require coordinated quiescing and is not
  reliable without guest cooperation).
- A successful `take` MUST leave the VM in the same libvirt
  domain state it had before the call (running → running,
  shut off → shut off).
- A successful `revert` MUST leave the VM in a documented
  state. For `domain` mode that means "exactly as snapshotted
  including RAM". For `disk_only` mode that means the VM is
  shut off and started fresh from the snapshotted disk.
- Half-applied snapshots (libvirt returned non-zero,
  intermediate qcow2 layer present) MUST be detected by
  `validate` and surfaced to the operator. The manager does
  NOT auto-repair; it logs and instructs.

## 7. Pre/Post Scenario Workflow (interaction with spec 008)

- Spec 008 runner calls
  `xdr-lab-snapshot-manager.sh take <vm> --label "scenario-<id>-pre"`
  for every target before the engine adapter runs.
- Spec 008 runner calls
  `xdr-lab-snapshot-manager.sh take <vm> --label "scenario-<id>-post"`
  after the engine adapter (even on failure) for forensics.
- Operator-initiated `aella_cli scenario revert <id>` calls
  `xdr-lab-snapshot-manager.sh revert <vm> "scenario-<id>-pre"`
  per target.

## 8. Rollback Strategy

- For deploy-time rollback: see spec 002 §6 / §7. Snapshots are
  not used to recover from a failed deploy because the deploy
  may itself create the very disk a snapshot would reference.
- For scenario rollback: use `revert` to a `scenario-<id>-pre`
  label.
- For arbitrary rollback: operator names the label or id;
  `validate` first to confirm the snapshot exists; then
  `revert`.

## 9. Failure Handling Philosophy

- `virsh snapshot-create-as` non-zero → propagate; sidecar is
  NOT updated (the atomic write only happens on success).
- `virsh snapshot-revert` non-zero → propagate; sidecar records
  the failure (`last_revert_failed_at`, `last_revert_failed_snap`).
- Sidecar corrupt or unreadable → `validate` reports; manager
  refuses destructive verbs until operator repairs or replaces
  the sidecar. The libvirt store remains authoritative.
- `max_retained` violated due to manual deletion outside the
  manager → `prune` reconciles on next call.

## 10. Recovery Philosophy

- **Snapshot store corruption.** Operator runs
  `aella_cli snapshot validate <vm>`; the report names the
  divergence. Remediation is manual `virsh snapshot-delete`
  followed by sidecar rebuild. The manager does NOT auto-purge.
- **VM cannot revert (libvirt error).** Operator inspects
  `vm-manager.log` and `snapshot-manager.log`. If the qcow2
  backing chain is broken, the path is destroy + redeploy
  (spec 002) plus a fresh snapshot baseline.
- **Disk full during snapshot.** `virsh` reports the failure;
  the lab does NOT auto-prune to make space (constitution
  §11 / safety). Operator runs `prune` or `delete` explicitly.

## 11. Forbidden Implementation Patterns

- Auto-revert without explicit operator command. Even on
  scenario failure, revert is initiated by `scenario revert`,
  not by the engine adapter (spec 008).
- Deleting snapshots from libvirt without updating the sidecar
  in the same code path. They MUST be consistent.
- Calling `virsh snapshot-delete <vm> --all` or any
  pattern-based mass delete (constitution P-14 spirit). Prune
  iterates explicitly.
- Snapshot operations on VMs not in `lab-vms.json::vms`
  (constitution M-16). Inventory scope is mandatory.
- Storing snapshots outside `/opt/xdr-lab/runtime/` or
  libvirt's managed location for the lab.
- Snapshot files committed to the package or to git.

## 12. Future Extensibility Guidance

- A future "named baseline" feature (operator-blessed clean
  starting points) MUST be modelled as labeled snapshots with a
  protected prefix (e.g. `baseline-*`) that `prune` never
  deletes.
- Multi-VM coordinated snapshots (e.g. a victim + attacker
  pair) MAY be added as a separate `aella_cli snapshot
  group-take <group_id>` verb operating on a declared group in
  `lab-vms.json`.
- External snapshot export (image rebake from a known good
  state) is out of scope and would require a new spec.

## 13. Validation Philosophy (for future implementation)

When this spec moves from Reserved to Adopted, validation MUST
confirm:

1. `take` is idempotent in the sense that calling it twice
   produces two distinct snapshots, and neither produces a
   broken qcow2 chain.
2. `revert` against a non-existent snapshot fails fast and does
   NOT touch the VM.
3. `revert` followed by `take` produces a snapshot that itself
   reverts cleanly.
4. `prune` never deletes the most recent snapshot.
5. `validate` returns non-zero whenever sidecar and libvirt
   diverge.
6. Snapshot operations on `sensor-vm` are permitted only when
   `snapshot_policy.mode` is explicitly set; the default
   policy SHOULD be cautious (disk_only with small
   max_retained) because sensor reverts may discard collected
   telemetry.
