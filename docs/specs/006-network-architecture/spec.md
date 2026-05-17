# Spec 006 — Network Architecture

> Binds to: constitution §2, §4, M-10, M-11, P-3, P-5, P-11, P-12,
> P-13. Refines L7 from spec 001.

## 1. Goal

Define the **lab network plane**: the authoritative internal Open
vSwitch (OVS) bridge, the OVS-backed libvirt attachment model, the
fixed lab subnet, the egress/NAT model, and the reverse-NAT entry
model. This spec is the geometry that specs 007 (OVS mirror) and 010
(reverse NAT) plug into.

## 2. Architecture

```
                ESXi vSwitch (external)
                       │
                       ▼
          ┌──────────────────────────┐
          │  Appliance (Ubuntu 24.04)│
          │                          │
          │   uplink NIC (mgmt/ext)  │   ← operator SSH / curl ingress
          │           │              │
          │           ▼              │
          │    iptables NAT          │
          │     - SNAT/MASQUERADE    │   ← lab → external egress
          │     - DNAT (reverse NAT) │   ← spec 010
          │           │              │
          │           ▼              │
          │   br0  (Open vSwitch     │   ← authoritative internal OVS
          │         bridge, M-10)   │       bridge (10.10.10.0/24, M-11)
          │     gw 10.10.10.1       │
          │   ┌───┬────┬───────┬─────┬─────────────┐
          │   │   │    │       │     │             │
          │   ▼   ▼    ▼       ▼     ▼             ▼
          │ sensor windows linux   test-vm1   OVS port mirror
          │ -vm   -victim -server               (spec 007, same br0)
          │ 10.10 10.10  10.10    10.10
          │ .10.10 .10.20 .10.30  .10.40
          └──────────────────────────────────────┘
```

**Libvirt attachment:** lab domains use the **`ovs-net`** network
definition (`config/ovs-net.xml`): `<bridge name='br0'/>` with
`<virtualport type='openvswitch'/>`. That binds guest virtio ports to
**OVS ports on `br0`**, not to a Linux kernel bridge stack.

## 3. Component Responsibilities

### 3.1 `br0` — the authoritative internal Open vSwitch bridge

- `br0` is an **Open vSwitch bridge** created and maintained by the
  host operator (OVS integration with Netplan, `ovs-vsctl`, or an
  equivalent operator-controlled bring-up). It is **not** described as
  a Linux kernel bridge environment for the lab dataplane.
- `br0` is the value of `lab-vms.json::network.bridge` and the value of
  every per-VM `bridge` field.
- `br0` carries the lab subnet `10.10.10.0/24`.
- The appliance assigns `10.10.10.1` to `br0` on the host side (the
  lab default gateway), when the operator’s host addressing model
  provides that address on the OVS bridge.
- L2 MUST NOT create, destroy, or reconfigure `br0` (constitution P-11).
  If `br0` is missing, every L2 script that requires it MUST emit a
  structured error and exit non-zero.

### 3.2 `ovs-net` — OVS-backed libvirt network

- The canonical libvirt XML is `config/ovs-net.xml` (`<name>ovs-net</name>`).
- Forward mode `bridge` with `bridge name='br0'` and
  `<virtualport type='openvswitch'/>` tells libvirt/QEMU to attach
  guests using an **openvswitch virtualport** onto **`br0`**.
- L2 MUST NOT define ad-hoc libvirt networks outside the documented
  lab model (constitution P-5): it does not repurpose `virsh default`
  or other unrelated networks.

### 3.3 Fixed lab subnet

`lab-vms.json::network`:

```
bridge          = "br0"
lab_subnet_cidr = "10.10.10.0/24"
gateway         = "10.10.10.1"
dns             = "10.10.10.1"
netmask         = "255.255.255.0"
```

These five values are **fixed**. Changing them is a `schema_version`
bump and a coordinated update across specs 004 (sensor), 007
(mirror), 010 (reverse NAT), and the runtime layer.

Per-VM IPs are declared by `lab-vms.json::vms.<name>.internal_ip` and
MUST be inside the lab subnet.

### 3.4 NAT (egress)

- The appliance MAY provide outbound NAT/MASQUERADE so lab VMs reach
  the internet through the uplink NIC. This is operator-configured
  (e.g. via Netplan post-up scripts or a dedicated manager).
- The lab's egress NAT is **not part of this project's responsibility
  today**. The project respects whatever the host provides and never
  flushes it.
- Future spec extension (spec 010 or a sibling) MAY add explicit
  ownership of an `XDR_LAB_NAT` iptables chain. Until then, NAT
  configuration is operator-side.

### 3.5 Reverse NAT (ingress)

Reverse NAT exposes selected internal services on the appliance's
external NIC. Governed in detail by spec 010. From this spec's
perspective:

- The mapping is declared per-VM in
  `lab-vms.json::vms.<name>.external_nat_port_mapping`. Example:
  `windows-victim.external_nat_port_mapping.rdp = 3389` means TCP
  connections to the appliance's external IP on port 3389 reach
  `10.10.10.30:3389`.
- All reverse-NAT rules MUST live in a single, project-owned iptables
  chain (proposed name: `XDR_LAB_DNAT`). The chain is flushed and rebuilt
  by its own L2 script; the host's other iptables state is untouched
  (constitution P-13).

## 4. Operational Assumptions

- The appliance is a single host. There is no clustering, no remote
  libvirt.
- The host's primary uplink NIC is **not** named `br0`. `br0` is
  internal-only (OVS lab dataplane).
- IP forwarding (`net.ipv4.ip_forward = 1`) is enabled on the host. This
  project does NOT toggle the sysctl; the operator's base image does.
- The lab uses IPv4 only. IPv6 on `br0` is undefined; future spec
  amendments MAY add it.

## 5. Runtime Flow

Internal traffic flow for a VM-to-VM ping:

```
windows-victim (10.10.10.30) → ARP/IP packet on its virtio NIC
       │
       ▼
openvswitch virtualport on br0 (OVS dataplane)
       │
       ▼
linux-server's tap interface on br0 (10.10.10.20)
       │
       ▼
linux-server VM receives the packet
```

The sensor receives copies via the **OVS port mirror** on `br0` (spec
007), not via a duplicate Linux-kernel-only bridge path.

External access flow (operator → windows-victim RDP):

```
operator → appliance_ext_ip:3389 (TCP)
       │
       ▼ iptables PREROUTING (XDR_LAB_DNAT, spec 010)
       │   DNAT to 10.10.10.30:3389
       ▼
br0 (OVS) → windows-victim tap → guest's RDP
```

Egress flow (VM → internet):

```
windows-victim → 10.10.10.1 (gateway on br0)
       │
       ▼ host kernel routing + iptables POSTROUTING (operator MASQUERADE)
       ▼
uplink NIC → external network
```

## 6. VM Connectivity Philosophy

- Every lab VM has exactly one NIC attached to **`ovs-net`** (therefore
  to **`br0`** as an OVS port). Multi-NIC designs are out of scope for
  the current spec.
- VMs use **static internal IPs** declared in `lab-vms.json`. The
  declaration is the source of truth; per-VM OSes are responsible for
  matching it (cloud-init for Linux, deploy-time scripts for Windows,
  sensor deploy script for the sensor).
- The lab does NOT operate a DHCP server. `10.10.10.1` is purely a
  gateway/DNS address.
- DNS for lab VMs resolves to the appliance's DNS forwarder at
  `10.10.10.1`. The forwarder is operator-side; this project does not
  implement it.

## 7. Failure Handling Philosophy

- Missing `br0` → L2 scripts that require it emit `br0_missing`
  structured error and `die`. They never auto-create it.
- VM cannot get an IP → not a deploy failure; deploy already completed
  when `virt-install` returned. Operator inspects guest OS config.
- Reverse-NAT rule missing after `nat enable` → spec 010 failure path;
  this spec only mandates that the rule is scoped to `XDR_LAB_DNAT`.
- Egress broken (VMs can't reach internet) → host MASQUERADE problem;
  out of scope for this project's runtime.

## 8. Recovery Philosophy

- **`br0` brought down by an unrelated operator action.** Operator
  restores the OVS bridge and host addressing (OVS/Netplan procedures),
  then re-runs the relevant lab commands (deploy is idempotent; mirror/NAT
  re-apply via their own verbs).
- **Lab subnet collision.** If the operator must move the lab to a
  different `/24`, update `lab-vms.json` (bump `schema_version`), update
  all `internal_ip`s, redeploy, re-apply mirror and reverse NAT.
- **NIC name change on the appliance.** Reverse NAT (spec 010) binds to
  an explicit external interface name; an interface rename requires
  updating that script's config, not editing iptables manually.

## 9. Traffic Flow Diagrams (canonical)

```
Lab internal east-west:
  VM_A.tap → br0 (OVS) → VM_B.tap
        ↘ (OVS port mirror on br0)
          sensor.tap (RX-only copy)  (spec 007)

Operator ingress to lab service:
  ext_NIC → iptables PREROUTING(XDR_LAB_DNAT) → br0 (OVS) → VM.tap
  return path: VM.tap → br0 → iptables POSTROUTING (conntrack)
               → ext_NIC → operator

Lab egress to internet:
  VM.tap → br0 (OVS) → host route → iptables POSTROUTING (operator MASQUERADE)
         → ext_NIC → upstream
```

## 10. Future Extensibility Guidance

- A future "multi-subnet lab" (e.g. DMZ + internal) MUST be represented
  by additional declarative blocks under `lab-vms.json::network` (e.g.
  `networks[]` instead of `network`). Today's single-subnet design is
  intentional and any extension MUST bump `schema_version`.
- A future "isolated scenario subnet" (e.g. air-gapped attack range)
  MUST attach to a **different** Open vSwitch bridge (e.g. `br1`) and
  MUST NOT silently reuse `br0`. The choice of bridge per scenario is
  declarative.
- IPv6 support MAY be added by declaring `lab_subnet_v6_cidr` and
  per-VM `internal_ipv6`. It MUST be optional at first.

## 11. Forbidden Implementation Patterns

- Recreating `br0` (constitution P-11). If `br0` is missing, scripts halt
  with a structured error.
- Repurposing `br0` for non-lab workloads or attaching the uplink NIC to
  it as an OVS port without an explicit operator design.
- `ip link set <uplink> down` or any modification of the uplink NIC by
  appliance scripts (constitution P-12).
- Calling `virsh net-destroy default` or modifying libvirt's managed
  networks outside the lab’s **`ovs-net`** contract (constitution P-5).
  Historical note: older drafts referred to a Linux-only bridge model;
  the shipped lab uses **OVS `br0` + `ovs-net` + openvswitch
  virtualport**.
- `iptables -F`, `iptables -t nat -F`, `iptables -X` (constitution
  P-13). Reverse NAT manages only its named chain.
- Storing additional network state outside `lab-vms.json` (e.g. Python
  dicts, env vars, /etc/sysconfig files). The JSON is the only source of
  truth.

## 12. Validation Philosophy

A network-architecture change is valid only if:

1. `lab-vms.json::network.bridge` is `"br0"` and every per-VM `bridge`
   is also `"br0"` (unless a `schema_version` bump introduces
   multi-bridge).
2. Every `internal_ip` is inside `lab_subnet_cidr`.
3. No script in `/opt/xdr-lab/scripts/` issues `ip link …` against an
   interface that is not part of the lab plane.
4. No script creates libvirt networks that contradict the **`ovs-net`**
   / **`br0`** / openvswitch virtualport contract without a spec bump.
5. Reverse-NAT rules (when implemented) live exclusively in
   `XDR_LAB_DNAT`; nothing in the project flushes the global nat table.
6. OVS mirror objects (when implemented) live on **`br0`** under a
   named mirror object owned by the lab (spec 007).
