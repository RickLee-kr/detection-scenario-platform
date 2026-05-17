# Spec 007 — OVS Mirror Policy

> Binds to: constitution §4, §6, §9, M-14, P-3. Refines L7 from
> specs 001 and 006. Companion: `docs/skills/ovs-mirror-skill.md`.

## 1. Goal

Define how the lab mirrors east-west traffic on **`br0`** (the same
**Open vSwitch bridge** used by **`ovs-net`** and
`<virtualport type='openvswitch'/>`) to the sensor VM's NIC so the
NDR/XDR sensor sees all relevant traffic — **without ever performing a
destructive OVS operation**.

This spec is intentionally precise about what is forbidden, because OVS
commands are exceptionally easy to use destructively.

## 2. Architecture

The canonical model is a **single Open vSwitch bridge `br0`**:

- Lab VMs attach to **`br0`** through the libvirt **`ovs-net`** definition
  (see spec 006): **OVS-backed libvirt network** with an **openvswitch
  virtualport**.
- The **OVS port mirror** is configured **on `br0`**. Lab VM taps and the
  sensor tap are OVS ports on **`br0`**; the mirror object selects traffic
  and sets **`output_port`** to the sensor’s port.

There is **no** parallel “Linux bridge `br0`” dataplane in this
architecture: **`br0` is the OVS dataplane** for the lab. Historical
drafts that described a separate `xdr-mirror-br` beside a kernel bridge
are **not** the shipped geometry.

```
                  ┌──────────────────────────┐
                  │  Open vSwitch bridge br0 │
                  │  (M-10 authoritative)    │
                  │  + ovs-net / virtualport │
                  └──────────────────────────┘
                          ▲   ▲   ▲   ▲
                          │   │   │   │   (lab VM + sensor OVS ports)
                          │   │   │   │
              (mirror sources, RX+TX scope)
                          │   │   │   │
                  Named mirror on br0
                    select_all=true (shipped default)
                    output_port = sensor tap
```

## 3. Component Responsibilities

### 3.1 L4 — declarative state

Add to `lab-vms.json` (proposed, behind `schema_version` bump):

```
"network": {
  …,
  "ovs_mirror": {
    "ovs_bridge": "br0",
    "mirror_name": "mirror-to-sensor",
    "sensor_vm": "sensor-vm",
    "include_vm_types": ["windows", "linux"]
  }
}
```

Until that schema lands, mirror parameters MUST align with runtime
defaults (`LAB_BRIDGE`, `XDR_LAB_MIRROR_NAME`, `XDR_LAB_SENSOR_VM`) and
MUST be expressible without hard-coding `vnetN` indices.

### 3.2 L2 — mirror orchestration (shipped vs future split)

Conventions identical to `xdr-lab-vm-manager.sh`:

- `set -euo pipefail`
- `log_structured` to `/opt/xdr-lab/logs/vm-manager.log` (and siblings)
- `die`, `require_cmd`
- Reads from `lab-vms.json` where applicable
- Never destroys **`br0`** (Open vSwitch lab bridge), never issues
  `emer-reset`, never clears all mirrors on the bridge outside the named
  object lifecycle

**Shipped implementation:** mirror verbs (`mirror apply|verify|validate-traffic|status`)
live in **`xdr-lab-vm-manager.sh`** and delegate inspection/state to
`ovs_mirror_state.py`. A dedicated `xdr-lab-ovs-manager.sh` remains a
permitted future refactor without changing the **non-destructive**
policy.

Verbs (initial):

- `apply` — ensure the named mirror exists on **`br0`** with
  **`output_port`** set to the discovered sensor interface; use
  incremental / idempotent `ovs-vsctl` patterns scoped to the mirror name.
- `verify` — sanity-check mirror existence and **`output_port`** against
  inventory-driven discovery (read-only where possible; non-zero exit on
  mismatch).
- `validate-traffic` — operator traffic probe path (engine: host + sensor
  SSH), without inventing fake success when mirror state is inconsistent.
- `status` — refresh / print `runtime/state/mirror.json`.

### 3.3 L1 — `aella_cli lab mirror …`

Per spec 005 and the shipped CLI (`appliance_cli.py`):

```
aella_cli lab mirror apply [sensor-vm]
aella_cli lab mirror verify [sensor-vm]
aella_cli lab mirror traffic [sensor-vm]   # engine: validate-traffic
```

The engine entrypoint `xdr-lab-vm-manager.sh mirror …` also exposes
`mirror status` (refresh / print `mirror.json`), which is **not** wired
as an `aella_cli` subcommand today — call the manager script directly
when operators need that refresh.

## 4. Operational Assumptions

- The host has `openvswitch-switch` installed and the `ovs-vswitchd`
  service running.
- **`br0`** exists as an OVS bridge before mirror apply (spec 006 / P-11).
- VM tap interface names follow libvirt's conventions (e.g. `vnetN`),
  discoverable per VM via `virsh domiflist <vm>`.
- The sensor VM's NIC is identifiable by its libvirt interface attached
  to **`br0`** (OVS port).

## 5. Sensor Port Auto-detection Philosophy

The OVS manager MUST NOT hard-code a `vnetN` index for the sensor or for
any lab VM. Auto-detection is mandatory:

1. Read the sensor VM name from `lab-vms.json` (or default `sensor-vm`).
2. Run `virsh domiflist <sensor>` (or equivalent). The interface attached
   to the lab OVS bridge (**`br0`**) is the sensor’s mirror destination.
3. For each lab VM in scope, discover its tap interface the same way.
4. Use the discovered interface names to build mirror parameters as
   implemented (shipped: `select_all=true` on **`br0`** with
   **`output_port`** = sensor port — consult `ovs_mirror_state.py` for
   exact reconciliation rules).
5. Log each discovered mapping at INFO (`mirror_port_discovered vm=… iface=…`).

If discovery fails for any VM (no interface, VM not running), that VM is
**skipped with a WARN** structured log where the implementation allows;
the operator can re-run `mirror apply` after starting the missing VMs.

## 6. Non-Destructive Mirror Policy

Every mutation MUST be:

- **Named.** The mirror object has a stable name (e.g.
  `mirror-to-sensor` via `XDR_LAB_MIRROR_NAME`) so operations target it
  explicitly.
- **Incremental / idempotent** per shipped semantics: re-running apply
  MUST NOT widen blast radius beyond the named mirror object.
- **Scoped.** No operation touches mirrors with different names or bridges
  outside **`LAB_BRIDGE`** (default **`br0`**).
- **Reentrant.** Second runs MUST converge to the same declared mirror
  identity without destructive OVS resets.

## 7. Mirror Verification Philosophy

`verify` MUST inspect the OVS state and confirm (as implemented by
`ovs_mirror_state.py` / engine):

1. **`br0`** exists and OVS is healthy.
2. The named mirror object exists on **`br0`**.
3. **`output_port`** references the sensor's discovered interface.
4. Overall consistency flags in `mirror.json` match engine rules (no fake
   success paths).

Each check produces structured logging; an overall `mirror_verify_ok` or
`mirror_verify_failed` summary is emitted. Failures return non-zero for
orchestration.

## 8. Mirror Recovery Philosophy

- **OVS / `br0` missing.** Operator restores Open vSwitch and **`br0`**
  per host bring-up; the lab does NOT auto-create **`br0`** (P-11).
- **Mirror object missing.** `apply` recreates it in a scoped way.
- **Source port missing for a powered-off VM.** WARN / skip patterns per
  implementation; re-run after VMs start.
- **Sensor port missing.** Hard failure: operator inspects sensor VM and
  `ovs-net` attachment.
- **Operator manually misconfigured the mirror.** Run scoped disable/remove
  of the **named** mirror only, then `mirror apply` again — never
  `emer-reset`.

## 9. Failure Handling Philosophy

- `ovs-vsctl` not installed → `require_cmd` fails → structured error, exit
  non-zero.
- `ovs-vswitchd` not running → first command fails → propagated; operator
  inspects journald.
- Bridge name collision (non-lab process owns the expected name) → hard
  failure; renaming requires a spec/config amendment.

## 10. Prohibited `ovs-vsctl` Patterns

The following MUST NEVER appear in lab code:

- `ovs-vsctl emer-reset`
- `ovs-vsctl del-br br0` or any destructive recreation of **`br0`**
- `ovs-vsctl del-br <any non-lab bridge>` without an explicit operator-only
  procedure outside this repository
- `ovs-vsctl clear bridge <bridge> mirrors` (wipes the whole bridge's
  mirrors)
- `ovs-vsctl clear bridge <bridge> ports`
- `ovs-vsctl --all destroy …`
- Any `ovs-vsctl` invocation that would strip **`br0`** of all lab ports or
  delete **`br0`** (constitution P-3, P-11).
- Any `ovs-ofctl` flow modifications (`del-flows`, `mod-flows`) for
  purposes unrelated to the named lab mirror.

Allowed patterns are **scoped** `add`/`remove`/`set` on the **named**
mirror and documented bridge attach operations that preserve **`br0`**
integrity.

## 11. Validation Philosophy

A mirror-related change is valid only if:

1. No path can delete **`br0`** (Open vSwitch lab bridge) or flush OVS
   globally.
2. No path can issue `emer-reset`, `--all destroy`, or `clear bridge …
   mirrors` / `clear bridge … ports`.
3. `mirror apply` is idempotent and converges to the documented mirror
   identity.
4. `mirror verify` returns exit 0 only when actual state matches the
   engine’s consistency model.
5. The sensor's interface is the **`output_port`** for the mirror; the
   sensor MUST NOT be treated as a mirror source.
6. Every `ovs-vsctl` invocation is logged via `log_structured` before
   execution where the runtime layer performs mutations.

## 12. Future Extensibility Guidance

- Per-VM include/exclude flags MAY be added to `lab-vms.json::vms.<name>`
  (e.g. `mirror: false`) once the base spec is extended additively.
- Bidirectional mirror (also mirror sensor egress to a forensic collector)
  is out of scope; would require a new spec.
- ERSPAN or remote mirror destinations are out of scope and forbidden in
  this spec (sensor receives traffic on its local NIC).
