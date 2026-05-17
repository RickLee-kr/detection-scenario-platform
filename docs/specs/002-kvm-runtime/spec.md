# Spec 002 — KVM Runtime

> Binds to: constitution §3, §5, §6, M-2, M-5, M-7, M-12, P-2, P-11,
> P-14. Refines L2 from spec 001.

## 1. Goal

Define the **KVM runtime lifecycle**: how the runtime layer (L2)
talks to libvirt/QEMU to create, start, stop, and destroy lab VMs in
a way that is idempotent, recoverable, and never reaches outside the
declared lab inventory.

This spec governs the existing `xdr-lab-vm-manager.sh` and any
future siblings that touch `virsh` / `virt-install` / `qemu-img`.

## 2. Architecture

L2 invokes three privileged tools:

- **`virt-install`** — one-shot domain creation from an existing
  base disk via `--import`. Never used to mutate an existing
  domain.
- **`virsh`** — lifecycle queries and operations:
  `dominfo`, `domifaddr`, `start`, `shutdown`, `destroy`,
  `undefine`, `autostart`, `list --all`.
- **`qemu-img`** — disk materialization: copy from L3 base into L5
  runtime, then `qemu-img resize` to `disk_size_gb`.

Every L2 invocation MUST be preceded by `require_cmd` so that
missing tooling produces a structured error rather than a cryptic
shell failure.

## 3. Component Responsibilities

### 3.1 Generic-VM deploy path

For VMs of type other than `sensor` (today: `windows`, `linux`,
generic test VMs), L2 MUST:

1. Verify the VM key exists in `lab-vms.json`.
2. Read `disk_filename`, `bridge`, `cpu`, `memory_mb`, `os_variant`,
   `autostart`, `disk_size_gb`.
3. Verify the base image exists at
   `/opt/xdr-lab/images/<vm>/<disk_filename>`. If missing →
   structured error pointing at `download <vm>`.
4. Materialize the runtime disk at
   `/opt/xdr-lab/runtime/<vm>-runtime.qcow2`:
   - If absent: copy from base.
   - If present: leave it (operator-managed state).
5. `qemu-img resize <runtime> <disk_size_gb>G`.
6. If `virsh dominfo <vm>` succeeds → **idempotent path**:
   reapply autostart, return success.
7. Else → run `virt-install --import` with virtio disk, virtio
   bridged NIC on `bridge`, declared os variant, `--virt-type kvm`,
   `--noautoconsole`, and `--autostart` iff configured.

### 3.2 Sensor-VM deploy path

Sensor deployment is described in spec 004. From the KVM-runtime
perspective, the sensor path:

- Bypasses `virt-install` (the modular sensor script owns the
  virsh-define step).
- Still produces a libvirt domain visible to `virsh dominfo
  sensor-vm`.
- Still goes through `apply_autostart` for consistency.

### 3.3 Start / Stop / Destroy

- `start`: refuse if the domain is not defined (no
  auto-deploy-on-start). Use `virsh start <vm>`. Treat
  "already running" as success.
- `stop`: try `virsh destroy <vm>` (forceful but quick) and fall
  back to `virsh shutdown <vm>`; both treated as best-effort. Do
  not raise if the domain is already off.
- `destroy`: tear down the domain and the runtime disk **only**:
  - `virsh destroy` (ignore "not running"),
  - `virsh undefine --managed-save --snapshots-metadata`
    (fallback to plain `virsh undefine`),
  - `rm -f /opt/xdr-lab/runtime/<vm>-runtime.qcow2`.
  Base images in L3 MUST NOT be removed by `destroy`.

### 3.4 Status

- `status all` → `virsh list --all`.
- `status <vm>` → `virsh dominfo <vm>` plus
  `virsh domifaddr <vm> --source agent` (best-effort).
- Status MUST NEVER mutate state.

## 4. Operational Assumptions

- libvirt + qemu-kvm + virt-install + qemu-utils are installed and
  the operator can use them without an extra `sudo` in the same
  shell that runs `aella_cli` (or the appliance is invoked under a
  service account in `libvirt`/`kvm` groups).
- Nested virtualization is enabled on the ESXi host so that
  `kvm-intel`/`kvm-amd` modules load with nesting support.
- The Open vSwitch bridge **`br0`** exists and is active for OVS
  before deploy; the **`ovs-net`** libvirt network references **`br0`**
  with `<virtualport type='openvswitch'/>`. L2 MUST NOT create or
  recreate **`br0`** (constitution P-11; spec 006 defines ownership).

## 5. Runtime Flow

```
deploy_vm <vm> [nodownload]
 ├─ assert L4 config present
 ├─ read type
 ├─ if sensor → deploy_sensor_vm (spec 004) + apply_autostart
 └─ else (generic):
     ├─ require_cmd virt-install / virsh / qemu-img
     ├─ assert L3 base image present
     ├─ materialize L5 runtime qcow2 (cp if missing)
     ├─ qemu-img resize
     ├─ if virsh dominfo <vm> succeeds → log idempotent + apply_autostart + return
     ├─ virt-install --import …
     └─ log deploy_vm_network_hints (internal_ip, nat map)
```

```
start_vm <vm>
 ├─ if !virsh dominfo <vm> → die "VM not defined"
 └─ virsh start <vm>   (treat "already running" as ok)
```

```
destroy_vm <vm>
 ├─ virsh destroy <vm>        (best-effort)
 ├─ virsh undefine <vm> --managed-save --snapshots-metadata
 │      || virsh undefine <vm>   (fallback)
 └─ rm -f /opt/xdr-lab/runtime/<vm>-runtime.qcow2
```

## 6. Failure Handling Philosophy

- Missing config → `die` early, exit 1, structured log
  `lab_config_read_failed` (L1) and/or `Missing config $CFG` (L2).
- Missing base qcow2 → `die` with a pointer to `download <vm>`.
- `virt-install` failure → log `deploy_vm_virt_install` then let
  `set -euo pipefail` propagate the non-zero exit. Do not
  half-clean.
- `virsh start` failure → `die`. Operator decides remediation.
- `virsh destroy/undefine` failures during `destroy_vm` are
  ignored (best-effort), because the goal is "tear down, idempotent"
  and partial pre-existing state is the common case.
- Sensor deploy script failure → propagate non-zero from
  `bash ./virt_deploy_modular_ds.sh …` to the caller (spec 004).

## 7. Recovery Philosophy

- **Stuck after `virt-install` failure.** Operator inspects
  `vm-manager.log` JSON, fixes the cause, re-runs `deploy <vm>`.
  The idempotent path takes over if the domain partially defined.
- **Bad runtime qcow2.** Operator runs `destroy <vm>`, then
  `deploy <vm>`.
- **Bad base image.** Operator runs `download <vm>` (or removes the
  file under `/opt/xdr-lab/images/<vm>/` and re-runs `download`),
  then `deploy`.
- **libvirt host reboot.** Domains with `autostart=true` come back
  automatically. The CLI surface is stateless across reboots.

## 8. VM Naming Conventions

- VM names are **the keys of `lab-vms.json::vms`**. They are also
  the `--name` argument to `virt-install` and the identifier passed
  to every `virsh` command.
- Naming rules:
  - Lowercase ASCII, digits, and hyphens only.
  - First character is a letter.
  - 1–32 characters.
  - Stable across releases — renaming a VM is a breaking change
    that requires re-deployment.
- Runtime disk file naming MUST be exactly
  `<vm>-runtime.qcow2` to keep the existing convention.

## 9. Autostart Philosophy

- Autostart is **declarative** in `lab-vms.json` (`autostart:
  true|false`).
- L2 reconciles autostart on every deploy (`apply_autostart`).
- Truthy values accepted: `True`, `true`, `1`. Anything else is
  treated as disabled.
- `virsh autostart` / `virsh autostart --disable` errors are
  swallowed (`|| true`) because they are not deploy-blocking; the
  structured log still reflects the reconciliation attempt.

## 10. qcow2 Handling Rules

- Base images live ONLY under `/opt/xdr-lab/images/<vm>/`.
- Runtime images live ONLY under `/opt/xdr-lab/runtime/`.
- L2 MUST NOT write to a base image after download.
- L2 MUST NOT delete a base image except via the dedicated
  `download` flow (where re-download overwrites the same path).
- `qemu-img resize` is only applied to runtime images (L5), not to
  base images (L3).
- `qemu-img convert` is NOT used by deploy. If a future feature
  needs format conversion, it MUST be added as a separate L2
  utility and gated behind an explicit subcommand.

## 11. Idempotent Deployment Handling

Idempotency is mandatory (M-5). The implementation pattern is:

```
if virsh dominfo "$vm" >/dev/null 2>&1; then
  log_structured INFO "deploy_vm_idempotent_exists vm=${vm}"
  apply_autostart "$vm"
  return 0
fi
```

Implementer rules:

- The existence check MUST come **after** disk materialization, so
  that a defined-but-missing-disk state is healed.
- Idempotent path MUST reconcile autostart and SHOULD NOT silently
  change any other property (CPU, memory, NIC) — config drift is
  surfaced via logging in a future enhancement, not applied
  silently.
- Idempotent path MUST be observable: it emits a distinct
  structured event (`deploy_vm_idempotent_exists`).

## 12. Future Extensibility Guidance

- A future "reconfigure" verb (CPU/memory live-edit) MUST be a
  separate subcommand, not a side-effect of `deploy`.
- A future "import existing domain" path MUST refuse to touch
  domains whose names are not in `lab-vms.json`.
- A future "clone" verb MUST allocate a new runtime qcow2 path
  with a different basename and MUST NOT collide with the
  `<vm>-runtime.qcow2` convention.

## 13. Forbidden Implementation Patterns

- Wholesale `virsh list --all | xargs virsh undefine` style
  cleanup loops (constitution P-14).
- Embedding `virt-install` flags in `appliance_cli.py`
  (constitution P-2).
- Auto-creating `br0` when missing (constitution P-11).
- Mutating base images in place (`qemu-img resize` on
  `/opt/xdr-lab/images/...`).
- Calling `virsh net-define`/`virsh net-destroy default` from any
  deploy path (constitution P-5).
- Using `--cdrom`, `--location`, or `--pxe` in `virt-install`. The
  appliance is `--import`-only (base qcow2 is the truth).
- Writing to `/var/lib/libvirt/images/` directly. The lab owns
  `/opt/xdr-lab/` and only `/opt/xdr-lab/`.

## 14. Validation Philosophy

A KVM-runtime change is valid only if:

1. `deploy <vm>` is idempotent (rerun → no-op, exit 0).
2. `deploy all` survives a per-VM failure without aborting later
   VMs (with `WARN` logs).
3. `destroy <vm>` is a no-op on a non-existent VM (exit 0 + WARN).
4. `start <vm>` on an undefined VM emits a structured error and
   non-zero exit (no auto-deploy).
5. Base images under `/opt/xdr-lab/images/<vm>/<file>.qcow2` are
   byte-identical before and after `deploy`.
6. No new privileged tool is invoked from L1 (Python).
