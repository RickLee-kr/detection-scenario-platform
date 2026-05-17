# Skill — Snapshot Management

Operational memory for any task that touches the (future) snapshot
manager. Governed by spec 009. **Status: spec is Reserved; no
runtime code may exist yet.** Read before drafting
`xdr-lab-snapshot-manager.sh` or any `aella_cli snapshot …`
subcommand.

## Hard rules

- Snapshots are **inventory-scoped**: every operation refers to a
  `<vm>` in `lab-vms.json::vms` and a snapshot id/label that
  belongs to it (M-16).
- VM consistency MUST be preserved (M-15): take/revert leave the
  VM in a documented libvirt state (running → running for
  `domain` mode; shut off → shut off; or, for `disk_only`, the
  documented disk-only semantics).
- No auto-revert. Revert is operator-initiated (constitution §11
  forbids implicit destructive defaults; spec 008 forbids engine
  adapters initiating revert).
- No `virsh snapshot-delete <vm> --all` and no
  pattern-based mass-delete (constitution P-14 spirit). `prune`
  iterates explicitly.
- Snapshots are NEVER committed to the package or to git.

## Storage layout

```
/opt/xdr-lab/runtime/
  ├── <vm>-runtime.qcow2          (libvirt-managed internal snapshots)
  └── <vm>-snapshots.json         (operator-facing sidecar metadata)
```

Sidecar shape (minimum):

```json
{
  "vm": "windows-victim",
  "snapshots": [
    {
      "id": "2026-05-12T07:00:00Z",
      "label": "scenario-foo-pre",
      "mode": "domain",
      "created_ts": "2026-05-12T07:00:00Z",
      "parent": null
    }
  ],
  "last_reverted_to": null,
  "last_revert_failed_at": null
}
```

Sidecar updates MUST be atomic: write to
`<vm>-snapshots.json.tmp` then `mv` over the original.

## Verb invariants

- `take <vm> [--label LABEL]`
  - Mode chosen from `lab-vms.json::vms.<vm>.snapshot_policy.mode`
    (default `disk_only`).
  - Refuses if libvirt rejects the mode (e.g. memory snapshot
    impossible).
  - Updates sidecar ONLY on success.
- `revert <vm> <snap_id_or_label>`
  - Resolves to a real libvirt snapshot before issuing
    `snapshot-revert`.
  - Logs domain state before/after.
  - Records `last_reverted_to`.
- `delete <vm> <snap_id_or_label>`
  - Validates target exists first.
  - Updates sidecar in the same code path.
- `prune <vm>`
  - Acts only on **auto-labeled** snapshots
    (`label_prefix=="auto"` policy).
  - Never deletes the newest snapshot.
  - Never deletes a `baseline-*` (future operator-blessed) entry.
- `validate <vm>`
  - Read-only set comparison between libvirt and sidecar.
  - Returns non-zero on any divergence.

## Logging (spec 012)

- `snapshot_take_begin` / `snapshot_take_end` /
  `snapshot_take_failed` with `vm`, `snap_id`, `label`, `mode`.
- `snapshot_revert_begin` / `snapshot_revert_end` /
  `snapshot_revert_failed`.
- `snapshot_delete_begin` / `snapshot_delete_end`.
- `snapshot_validate_diverged details=…`.

## Scenario interaction (spec 008)

When the scenario runner exists, it calls:

- `snapshot take <vm> --label "scenario-<id>-pre"` per target,
  before the engine adapter.
- `snapshot take <vm> --label "scenario-<id>-post"` per target,
  after the engine adapter — even on engine failure (preserve
  forensics).

The scenario runner does NOT initiate revert.

## When you would otherwise be tempted to…

- **…wrap revert into `scenario run` "auto-rollback on failure":**
  stop. Revert is operator-initiated (`aella_cli scenario
  revert`).
- **…`virsh snapshot-delete <vm> --all` to clean up:** stop.
  Iterate explicitly and update the sidecar each time.
- **…store snapshots under `/tmp` or elsewhere:** stop. They
  live in libvirt's managed location for the lab plus the
  sidecar under `/opt/xdr-lab/runtime/`.
- **…delete the most recent snapshot in `prune`:** stop. Always
  retain the newest.

## Recovery patterns

- **Sidecar corrupt →** `validate` reports; operator inspects
  libvirt with `virsh snapshot-list <vm>` and rebuilds the
  sidecar from that listing. The manager refuses destructive
  verbs until reconciled.
- **Broken qcow2 backing chain →** destroy + redeploy
  (spec 002), then take a fresh baseline snapshot.
- **Disk full during snapshot →** operator `prune` or `delete`
  explicitly; the manager does NOT auto-prune to make space.

## Related specs and skills

- Spec 002 (KVM runtime — provides the domains being
  snapshotted), spec 008 (scenarios — primary consumer of
  snapshots), spec 009 (primary), spec 011 (safety), spec 012
  (logging).
- Companion skills: `kvm-runtime-skill.md`,
  `attack-scenario-skill.md`, `appliance-cli-skill.md`.
