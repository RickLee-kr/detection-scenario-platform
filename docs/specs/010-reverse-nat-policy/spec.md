# Spec 010 — Reverse NAT Policy

> Binds to: constitution §4, §7, M-9, P-13. Refines L7 from
> spec 006. Companion: `skills/reverse-nat-skill.md`.

## 1. Goal

Define how the appliance exposes selected internal lab services on
its **external NIC** via reverse NAT — without ever flushing the
host's firewall, modifying unrelated chains, or hiding state from
the operator.

The mapping is **declarative**, **inventory-scoped**, and **lives
in its own iptables chain**.

## 2. Architecture

```
   external NIC (operator-facing)
            │
            ▼
iptables nat PREROUTING
   ├─ … host-owned rules untouched …
   └─ -j XDR_LAB_DNAT                    ← single jump owned by the lab
            │
            ▼
       XDR_LAB_DNAT                      ← lab-owned chain (rebuilt deterministically)
       ├─ -p tcp --dport 1022 -j DNAT --to-destination 10.10.10.10:22
       ├─ -p tcp --dport 44110 -j DNAT --to-destination 10.10.10.10:443
       ├─ -p tcp --dport 8810  -j DNAT --to-destination 10.10.10.10:8810
       ├─ -p tcp --dport 3389 -j DNAT --to-destination 10.10.10.30:3389
       ├─ -p tcp --dport 45986 -j DNAT --to-destination 10.10.10.30:5986
       ├─ -p tcp --dport 2022 -j DNAT --to-destination 10.10.10.20:22
       └─ -p tcp --dport 22040 -j DNAT --to-destination 10.10.10.40:22

iptables filter FORWARD
   └─ -j XDR_LAB_FWD                     ← optional companion chain that
       (allow established/related + DNAT'd flows toward br0)   ALLOWs the DNAT'd flows
```

The mapping is the projection of every VM's
`external_nat_port_mapping` block in `lab-vms.json` onto its
`internal_ip` and a service-specific internal port.

## 3. Component Responsibilities

### 3.1 L4 — declarative state

Per-VM in `lab-vms.json::vms.<name>.external_nat_port_mapping`:

```
"external_nat_port_mapping": {
  "ssh":         1022,    // service name → external port
  "https":       44110,
  "rdp":         3389,
  "winrm_https": 45986,
  "ui":          8810,
  "<custom>":    <port>
}
```

The service name MUST resolve to a **canonical internal port**
known to the NAT manager. A minimal canonical table (proposed):

```
ssh         → 22/tcp
https       → 443/tcp
http        → 80/tcp
rdp         → 3389/tcp
winrm_http  → 5985/tcp
winrm_https → 5986/tcp
ui          → 8810/tcp   (sensor UI; declared by sensor profile)
```

Adding a new service name is a coordinated update: it gets listed
in the canonical table inside the NAT manager (or a future
dedicated config file) and used by VMs.

A free-form entry MAY also be expressed as
`"<svc>": {"external": 12345, "internal": 67890, "proto": "tcp"}`
to bypass the canonical table for one-off services.

### 3.2 L2 — `xdr-lab-nat-manager.sh` (future script)

Verbs:

- `enable`  — idempotently rebuild `XDR_LAB_DNAT` from
              `lab-vms.json`, ensure the single PREROUTING jump
              exists, ensure the companion `XDR_LAB_FWD` exists if
              used.
- `disable` — remove the PREROUTING jump and flush
              `XDR_LAB_DNAT` (and `XDR_LAB_FWD`). Leave every
              other table/chain untouched.
- `status`  — print `iptables -t nat -nvL XDR_LAB_DNAT`
              and `iptables -nvL XDR_LAB_FWD` plus the canonical
              mapping derived from the config.
- `verify`  — assert that every declared mapping has exactly one
              matching rule in `XDR_LAB_DNAT` and that no extras
              exist.

Implementation pattern (illustrative):

```bash
# Atomic rebuild: build to a temp chain, then swap.
iptables -t nat -N XDR_LAB_DNAT_NEW 2>/dev/null || true
iptables -t nat -F XDR_LAB_DNAT_NEW
# … add rules to XDR_LAB_DNAT_NEW …
iptables -t nat -N XDR_LAB_DNAT 2>/dev/null || true
iptables -t nat -F XDR_LAB_DNAT
iptables -t nat -A XDR_LAB_DNAT -j XDR_LAB_DNAT_NEW
iptables -t nat -F XDR_LAB_DNAT_NEW
iptables -t nat -X XDR_LAB_DNAT_NEW
# Or — simpler — flush XDR_LAB_DNAT then re-add rules in a single critical section.
```

The script MUST ensure exactly one PREROUTING jump rule referencing
`XDR_LAB_DNAT` exists (use `iptables -C` to test before `iptables
-A`).

### 3.3 L1 — `aella_cli nat …` (future)

```
aella_cli nat enable
aella_cli nat disable
aella_cli nat status
aella_cli nat verify
```

Per spec 005 conventions.

## 4. Operational Assumptions

- The external NIC name is operator-configured (e.g. via
  `lab-vms.json::network.external_iface` — proposed field). If
  absent, the manager binds DNAT rules without `-i <iface>`,
  matching any inbound interface that hits PREROUTING. The
  recommended configuration declares `external_iface` to
  scope DNAT rules.
- Port ranges declared in `external_nat_port_mapping` do not
  collide with the operator's other host services. Conflicts are
  the operator's responsibility to resolve before `enable`.
- IP forwarding is enabled on the host (spec 006 §4). The NAT
  manager does NOT toggle `net.ipv4.ip_forward`.

## 5. Runtime Flow

```
aella_cli nat enable
       │
       ▼
xdr-lab-nat-manager.sh enable
       ├─ parse lab-vms.json → per-VM (external_port, internal_ip:internal_port, proto)
       ├─ ensure chain XDR_LAB_DNAT exists (iptables -N if needed)
       ├─ flush XDR_LAB_DNAT
       ├─ for each mapping: iptables -t nat -A XDR_LAB_DNAT -p <proto> --dport <ext> -j DNAT --to-destination <ip>:<int>
       ├─ ensure PREROUTING has exactly one -j XDR_LAB_DNAT
       ├─ if FORWARD policy is DROP: ensure XDR_LAB_FWD chain + FORWARD jump exist with stateful accept
       └─ log nat_enable_summary count=…
```

## 6. iptables Architecture (Mandatory)

- Lab-owned tables: only `nat` and `filter`.
- Lab-owned chains:
  - `XDR_LAB_DNAT` (in `nat`, jumped from `PREROUTING`).
  - `XDR_LAB_FWD`  (in `filter`, jumped from `FORWARD`) —
    optional, used when the host's `FORWARD` policy is `DROP`.
- Lab MUST NOT touch:
  - The default policy of any built-in chain.
  - Existing rules in `PREROUTING`/`FORWARD`/`POSTROUTING` other
    than its own single jump.
  - The `mangle`, `raw`, or `security` tables.

## 7. Reverse NAT Port Mapping Philosophy

- Mappings are declared **per VM**, not globally. The full lab
  mapping is the union of every VM's
  `external_nat_port_mapping`. Collisions on external port
  numbers MUST be a hard error at `enable` time, with a
  structured log naming both colliding VMs.
- Service names resolve via the canonical table; arbitrary
  service names are forbidden unless the entry uses the explicit
  `{external, internal, proto}` form.
- TCP is the default protocol; UDP MUST be expressed via the
  explicit form.
- Port number ranges MUST be 1–65535; numbers below 1024 SHOULD
  be flagged with a WARN (operator may have firewall conflicts).

## 8. Access Verification Philosophy

`verify` MUST:

1. Recompute the expected mappings from `lab-vms.json`.
2. Read the current `XDR_LAB_DNAT` chain.
3. Compare set-equality: every expected rule present, no
   unexpected rule present, no duplicates.
4. Confirm exactly one PREROUTING jump exists.
5. Emit a structured `nat_verify_ok` or
   `nat_verify_failed details=[…]`.

Operator MAY additionally probe `tcp:<external_port>` from a
known remote, but probing is out of scope for this script (it is
a network test, not a config check).

## 9. Operator Visibility Philosophy

`status` MUST print a human-friendly table that includes:

```
VM              Service       External  Internal IP    Internal Port  Proto
windows-victim  rdp           3389      10.10.10.30    3389           tcp
windows-victim  winrm_https   45986     10.10.10.30    5986           tcp
sensor-vm       ssh           1022      10.10.10.10    22             tcp
sensor-vm       https         44110     10.10.10.10    443            tcp
sensor-vm       ui            8810      10.10.10.10    8810           tcp
linux-server    ssh           2022      10.10.10.20    22             tcp
```

…followed by the raw `iptables -t nat -nvL XDR_LAB_DNAT` for audit.

This visibility is mandatory: operators MUST be able to answer
"how do I reach VM X?" without inspecting iptables themselves.

## 10. Failure Handling Philosophy

- External port collision across VMs → hard failure on `enable`
  before any iptables mutation; structured log
  `nat_port_collision external=<port> vms=[…]`.
- Unknown service name (not in canonical table, not explicit
  form) → hard failure; structured log
  `nat_service_unknown service=<name> vm=<vm>`.
- iptables command failure (kernel rejected rule) → propagate;
  `XDR_LAB_DNAT` may be partially populated. Operator runs
  `nat disable` then `nat enable` to recover; the manager does
  NOT silently flush on failure.
- Missing PREROUTING jump despite a populated `XDR_LAB_DNAT` →
  `verify` reports; `enable` reinstalls the jump.

## 11. Recovery Philosophy

- `aella_cli nat disable` followed by `aella_cli nat enable` is
  always safe and idempotent.
- If `iptables-save` was used to snapshot host state before
  enabling reverse NAT, restoring from that snapshot is
  acceptable; the manager does NOT manage `iptables-save`/
  `iptables-restore` cycles.
- A host reboot loses all rules; the operator's bring-up
  procedure SHOULD invoke `aella_cli nat enable` (e.g. via a
  systemd oneshot service shipped separately). The manager
  itself does NOT install a systemd unit.

## 12. Forbidden Implementation Patterns

- `iptables -F`, `iptables -X`, `iptables -t nat -F`,
  `iptables -t nat -X`, `iptables -P FORWARD DROP` (changing
  default policy), `iptables-restore < /dev/null` — all
  forbidden (constitution P-13).
- Touching any chain other than `XDR_LAB_DNAT` and
  `XDR_LAB_FWD` (and the minimal single jump rule in
  `PREROUTING` and optionally `FORWARD`).
- Hard-coded port numbers anywhere outside the canonical table
  and `lab-vms.json`.
- Implementing iptables logic in `appliance_cli.py`
  (constitution P-2).
- Auto-installing `iptables-persistent` or similar packages
  (constitution P-9).
- Logging plaintext credentials in `status` output.

## 13. Validation Philosophy

A reverse-NAT change is valid only if:

1. `enable` is idempotent: rerun produces an identical
   `XDR_LAB_DNAT` and no extra PREROUTING jumps.
2. `disable` followed by `enable` produces the same chain as a
   single `enable`.
3. Removing a VM from `lab-vms.json` and re-running `enable`
   removes all of that VM's rules (set difference).
4. Adding a new mapping to `lab-vms.json` and re-running
   `enable` adds exactly the new rule(s).
5. No rule outside `XDR_LAB_DNAT` / `XDR_LAB_FWD` (and their
   single jumps) is created or modified.
6. `status` enumerates every declared mapping exactly once.

## 14. Golden-Image Read-Only Validation Path (current implementation)

The full `xdr-lab-nat-manager.sh` from §3.2 is not yet built. Until
it ships, the operational contract is the **inverse**: the KVM Host
Golden Image is responsible for installing the NAT/Reverse-NAT
policy, and the appliance only **observes** that policy.

### 14.1 Authoritative mapping (Golden-Image contract)

```
VM                Internal IP    External  Internal  Proto
sensor-vm         10.10.10.10    1022      22        tcp
linux-server      10.10.10.20    2022      22        tcp
windows-victim    10.10.10.30    3389      3389      tcp
```

**Optional management access** (not iptables DNAT — see `docs/web-console.md`):

```
VM                websockify (host)   QEMU VNC (127.0.0.1)
windows-build     6081                5901  (display :1)
windows-victim    6082                5902  (display :2)
```

Configured via `XDR_LAB_WEB_CONSOLE_PORT_MAP`; QEMU VNC stays on localhost.
External exposure uses websockify ports only (no nginx/apache).

This mapping is intentionally **not** sourced from `lab-vms.json` for
iptables validation. The Golden Image is the operator-facing source of
truth for the production port contract; allowing `lab-vms.json` drift to
break that contract is unacceptable. The mapping therefore lives as a
constant in `scripts/nat_state.py` and is mirrored here as documentation.

`lab-vms.json::external_nat_port_mapping` MUST nonetheless carry the same
external ports for the core lab VMs so Access Info, inventory exports,
and a future `xdr-lab-nat-manager.sh` rebuild stay aligned with this table.

### 14.2 Components

- **`scripts/nat_state.py`** — read-only iptables introspection
  helper. Subcommands: `refresh`, `verify`, `status`. NEVER calls
  `iptables -F/-X/-A/-I/-D/-P`; only `iptables -S`.
- **`scripts/xdr-lab-vm-manager.sh nat <verify|status>`** — the
  operator entrypoint. Wraps the helper, emits structured logs,
  surfaces a per-defect summary on failure.
- **`runtime/state/nat.json`** — atomically-written state record
  describing every checked iptables rule. May also record an optional
  web-console listener when full `verify` runs (not part of DNAT contract).

### 14.3 Validation rules

`nat verify` exits zero if **all** of the following hold:

1. `iptables -t nat -S POSTROUTING` contains at least one
   `-A POSTROUTING -s 10.10.10.0/24 ... -j MASQUERADE` rule.
2. `iptables -t nat -S PREROUTING` contains a `-j DNAT` rule for
   every entry in the authoritative mapping, with the kernel's
   printed `--to-destination` matching the contract `<ip>:<port>`.
3. `iptables -S FORWARD` contains at least one `-j ACCEPT` rule
   whose `-s` or `-d` equals `10.10.10.0/24`.

Use `nat verify --iptables-only` (or `validate-host-network.sh`) for the
**core contract only**. Steps (1)–(3) are required for lab operation.

**Optional:** full `nat verify` (without `--iptables-only`) also probes a
legacy single-port web-console listener and records it in `nat.json`. Per-VM
websockify on **6081/6082** is validated separately — see
`docs/web-console.md` and `bootstrap/validate-web-console.sh`.

If any required step fails, `verify` exits non-zero and the helper writes the
diagnosis into `nat.json::missing[]`. The host's iptables state is **never**
modified.

### 14.4 Forbidden in the validation path (additive to §12)

- Running `iptables -A`, `-I`, `-D`, `-F`, `-X`, or `-P` from any
  code path of the validator.
- Reading `lab-vms.json::external_nat_port_mapping` for the rules
  themselves — that field is reserved for the future
  `xdr-lab-nat-manager.sh` mutating path, not for Golden-Image
  validation.
- Auto-installing packages, opening firewall ports, or starting
  systemd units to "repair" a missing rule. The operator's
  next action on a `nat_verify_failed` event is to re-bake the
  Golden Image, not to mutate the running host.

### 14.5 Migration to the full §3.2 manager

When `xdr-lab-nat-manager.sh` is implemented, the read-only
validator MUST coexist with the mutating manager: the manager will
own `enable`/`disable`; the validator will continue to own
`verify`/`status`. The authoritative mapping in `nat_state.py`
becomes the cross-check against what `xdr-lab-nat-manager.sh`
derives from `lab-vms.json`; any divergence is a configuration bug
that surfaces via `nat verify`.
