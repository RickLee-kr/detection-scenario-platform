# Skill — KVM Runtime

Operational memory for any future Cursor / contributor task that
touches the KVM runtime. **Read before editing
`packaging/opt/xdr-lab/scripts/xdr-lab-vm-manager.sh` or any
sibling deploy script.** Governed by spec 002.

## Hard rules

- Never call `virsh` / `virt-install` / `qemu-img` from Python
  (`appliance_cli.py`). They belong in L2 only.
- Never put `virt-install` in a path that mutates an already-defined
  domain. Existence is checked via `virsh dominfo` and the
  idempotent branch returns without touching libvirt.
- Never auto-create `br0`. If `br0` is missing, `die` with a
  structured log.
- Never mutate base images under `/opt/xdr-lab/images/<vm>/`. Only
  the runtime copy under `/opt/xdr-lab/runtime/<vm>-runtime.qcow2`
  is mutable.
- Never iterate `virsh list --all | xargs virsh undefine`. Loops
  MUST iterate the lab inventory from `lab-vms.json`.

## Idempotent deploy pattern (canonical)

```bash
if vm_exists "$vm"; then
  log_structured INFO "deploy_vm_idempotent_exists vm=${vm}"
  apply_autostart "$vm"
  return 0
fi
```

Place this **after** materializing the runtime qcow2 (so a
defined-but-missing-disk state is healed) and **before**
`virt-install --import`.

## virt-install invariants

- `--import` only. No `--cdrom`/`--location`/`--pxe`.
- `--virt-type kvm`, `--noautoconsole`.
- `--network bridge=${bridge},model=virtio` where `${bridge}` comes
  from `lab-vms.json`.
- `--disk path=${RUN}/${vm}-runtime.qcow2,format=qcow2,bus=virtio`.
- `--autostart` flag is added iff `lab-vms.json::vms.<vm>.autostart`
  is truthy.

## VM lifecycle invariants

- `start`: refuse on undefined domain (`die`); treat "already
  running" as success.
- `stop`: best-effort (`virsh destroy` → fallback `virsh shutdown`);
  never raise on a domain that is already off.
- `destroy`: best-effort `virsh destroy`, then
  `virsh undefine --managed-save --snapshots-metadata` (fallback to
  plain `undefine`), then `rm -f` only the runtime qcow2 path.
- `status`: read-only, never mutate.

## Naming invariants

- VM name = `lab-vms.json::vms.<key>`. Lowercase ASCII + digits +
  hyphens; starts with a letter; 1–32 chars.
- Runtime disk filename = `<vm>-runtime.qcow2` (exactly).
- Domain name passed to virsh / virt-install = `<vm>` (exactly).

## Logging invariants

- Every external command is preceded by a `log_structured` line.
- Lifecycle events follow the `<verb>_begin` / `<verb>_end` /
  `<verb>_idempotent_<state>` / `<verb>_skip_<reason>` taxonomy
  (spec 012).
- Per-target loops in `<action> all` continue past per-VM failures
  with a `WARN` skip log; they MUST NOT abort the whole batch.

## When you would otherwise be tempted to…

- **…run `virsh undefine` over every domain to "clean up":** stop.
  Iterate `list_vms` (from `lab-vms.json`) instead.
- **…modify the base qcow2 to save disk:** stop. Use the runtime
  qcow2; the base is immutable post-download.
- **…recreate `br0` because it's missing:** stop. `die` with
  `br0_missing` and let the operator restore it.
- **…add a "force redeploy" flag that does `destroy` + `deploy`
  internally:** stop. Operator chains those two verbs explicitly.

## Related specs and skills

- Spec 001 (architecture), spec 002 (this skill's primary spec),
  spec 003 (image policy), spec 004 (sensor branch), spec 011
  (operational safety), spec 012 (logging).
- Companion skills: `sensor-deployment-skill.md`,
  `appliance-cli-skill.md`, `snapshot-management-skill.md`.
