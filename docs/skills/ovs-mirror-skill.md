# Skill — OVS Mirror

Operational memory for any future Cursor / contributor task that
touches Open vSwitch mirror configuration. Governed by spec 007.
Read this **before** writing `xdr-lab-ovs-manager.sh` or invoking
`ovs-vsctl` in any committed code path.

## Hard rules (forbidden)

- **Never delete `br0`.** `br0` is the **Open vSwitch** lab dataplane
  and the authoritative attachment point for **`ovs-net`** / openvswitch
  virtualports (constitution M-10, P-3). `ovs-vsctl del-br br0` MUST NOT
  exist anywhere in this project.
- **Never flush OVS globally.** Forbidden commands:
  - `ovs-vsctl emer-reset`
  - `ovs-vsctl --all destroy …`
  - `ovs-vsctl clear bridge <bridge> mirrors`
  - `ovs-vsctl clear bridge <bridge> ports`
  - `ovs-ofctl del-flows <bridge>` (for flows unrelated to the lab
    mirror)
- **Never touch OVS bridges the lab doesn't own.** Mirror operations
  target the lab bridge (default **`br0`**, `LAB_BRIDGE`). Other OVS
  bridges on the host are off-limits unless a future spec explicitly
  extends scope.
- **Never delete a mirror by clearing the bridge's mirror set.**
  Always target the named mirror object directly.

## Mirror operations MUST be incremental and named

The mirror has a stable name (proposed `xdr-mirror`). All
mutations target it explicitly:

```bash
# Add a source port (lab VM tap):
ovs-vsctl --id=@p get port "$VM_IFACE" \
  -- --id=@m get mirror "$MIRROR_NAME" \
  -- add mirror "$MIRROR_NAME" select-src-port @p

# Remove a source port:
ovs-vsctl --id=@p get port "$VM_IFACE" \
  -- --id=@m get mirror "$MIRROR_NAME" \
  -- remove mirror "$MIRROR_NAME" select-src-port @p

# Allowed scoped teardown (named mirror only):
ovs-vsctl --if-exists destroy mirror "$MIRROR_NAME"
```

Never use `clear bridge … mirrors`. Always operate on the named
mirror.

## Validate sensor interface before applying mirror

Auto-detection is mandatory (spec 007 §5):

1. Look up the sensor VM name from `lab-vms.json` (today
   `sensor-vm`).
2. Resolve its host-side tap interface via `virsh domiflist
   <sensor>` filtered to ports on the lab OVS bridge.
3. If the sensor's interface cannot be resolved → `die "sensor
   mirror destination unresolved"`. Do NOT pick a default like
   `vnet0`.
4. Log the discovered iface
   (`mirror_port_discovered vm=sensor-vm iface=…`).
5. Use the discovered interface as the mirror's `output-port`.

The sensor MUST NOT appear in `select-src-port` or
`select-dst-port`. The sensor receives mirrored traffic; it does
not originate it for the mirror's purposes.

## Verify philosophy

`mirror verify` is the operator's audit. It MUST:

- Confirm the lab's OVS bridge exists.
- Confirm the named mirror exists on that bridge.
- Confirm `output_port` is exactly the sensor's discovered iface.
- Confirm `select_src_port` set equals the discovered lab-VM
  ifaces in scope (no extras, no omissions).
- Emit `mirror_verify_ok` or `mirror_verify_failed details=…`.

## Recovery patterns

- **Mirror missing → `mirror apply`.** Scoped, idempotent.
- **Sensor interface changed → re-run `mirror apply`.** Auto-
  detection picks up the new iface.
- **Stray source port left after a VM was removed →
  `mirror apply` reconciles** when the implementation derives the set from
  `lab-vms.json`.
- **OVS daemon dead →** out of scope; operator restarts
  `openvswitch-switch`. The lab does NOT auto-restart it.

## When you would otherwise be tempted to…

- **…`ovs-vsctl emer-reset` "to start clean":** stop. Use scoped mirror
  teardown of the **named** mirror object, then `mirror apply`.
  `emer-reset` is forbidden by constitution P-3.
- **…hard-code `vnet0` as the sensor:** stop. Use auto-detection
  via `virsh domiflist`.
- **…delete and recreate the OVS bridge to "force a clean
  state":** stop. The bridge is operator-owned; only the named
  mirror object is lab-owned.
- **…clear all mirrors on the bridge to remove the lab's:**
  stop. Use `destroy mirror "$MIRROR_NAME"` (scoped).

## Related specs and skills

- Spec 006 (network architecture), spec 007 (this skill's primary
  spec), spec 011 (operational safety), spec 012 (logging).
- Companion skills: `sensor-deployment-skill.md`,
  `appliance-cli-skill.md`.
