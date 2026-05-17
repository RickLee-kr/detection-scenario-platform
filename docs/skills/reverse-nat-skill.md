# Skill — Reverse NAT

Operational memory for any task that touches reverse-NAT
configuration. Governed by spec 010. Read before writing
`xdr-lab-nat-manager.sh` or any `aella_cli nat …` subcommand.

## Hard rules

- All lab DNAT rules live in **one** named chain:
  `XDR_LAB_DNAT` (in table `nat`, jumped from `PREROUTING` by a
  single rule).
- The optional companion forward chain is `XDR_LAB_FWD` (in
  table `filter`, jumped from `FORWARD`).
- The lab MUST NOT touch any other chain, table, or default
  policy (constitution P-13).
- **Never** invoke any of:
  - `iptables -F`
  - `iptables -X`
  - `iptables -t nat -F`
  - `iptables -t nat -X`
  - `iptables -P FORWARD DROP` (or any default policy change)
  - `iptables-restore < /dev/null`
- Mappings are derived from
  `lab-vms.json::vms.<vm>.external_nat_port_mapping`. No
  hard-coded port numbers anywhere else.

## Canonical service → internal port table

```
ssh         → 22/tcp
https       → 443/tcp
http        → 80/tcp
rdp         → 3389/tcp
winrm_http  → 5985/tcp
winrm_https → 5986/tcp
ui          → 8810/tcp   (sensor UI)
```

For a service not in this table, use the explicit form in
`lab-vms.json`:

```json
"external_nat_port_mapping": {
  "custom": {"external": 12345, "internal": 67890, "proto": "tcp"}
}
```

## Idempotent rebuild pattern

```bash
ensure_chain() {
  iptables -t "$1" -N "$2" 2>/dev/null || true
}

enable() {
  load lab-vms.json
  detect collisions on external port across all VMs → die on collision

  ensure_chain nat XDR_LAB_DNAT
  iptables -t nat -F XDR_LAB_DNAT
  for mapping in mappings:
    iptables -t nat -A XDR_LAB_DNAT \
      -p "$proto" --dport "$ext" \
      -j DNAT --to-destination "$ip:$int"

  # exactly-one jump in PREROUTING
  iptables -t nat -C PREROUTING -j XDR_LAB_DNAT 2>/dev/null \
    || iptables -t nat -A PREROUTING -j XDR_LAB_DNAT

  # optional FORWARD allow (when host default policy is DROP)
  ensure_chain filter XDR_LAB_FWD
  iptables -F XDR_LAB_FWD
  iptables -A XDR_LAB_FWD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
  iptables -A XDR_LAB_FWD -o br0 -j ACCEPT
  iptables -C FORWARD -j XDR_LAB_FWD 2>/dev/null \
    || iptables -I FORWARD -j XDR_LAB_FWD
}

disable() {
  iptables -t nat -D PREROUTING -j XDR_LAB_DNAT 2>/dev/null || true
  iptables -t nat -F XDR_LAB_DNAT 2>/dev/null || true
  iptables -D FORWARD -j XDR_LAB_FWD 2>/dev/null || true
  iptables -F XDR_LAB_FWD 2>/dev/null || true
}
```

`enable` MUST be deterministic — running it twice produces the
same `XDR_LAB_DNAT` chain content and exactly one PREROUTING
jump.

## Collision detection (mandatory)

Before touching iptables, the script MUST scan every VM's
`external_nat_port_mapping` and confirm no external port appears
twice. Collision is a hard failure:

```
nat_port_collision external=2022 vms=[linux-server, foo-vm]
```

## `verify` semantics

`aella_cli nat verify` MUST:

- Recompute expected rules from `lab-vms.json`.
- Read actual `XDR_LAB_DNAT` rules from iptables.
- Assert set-equality (no extras, no omissions, no duplicates).
- Assert exactly one PREROUTING jump.
- Emit `nat_verify_ok` (exit 0) or `nat_verify_failed
  details=…` (exit non-zero).

## Operator visibility (`status`)

Print a human table before the raw iptables dump:

```
VM              Service       External  Internal IP    Internal Port  Proto
windows-victim  rdp           3389      10.10.10.30    3389           tcp
```

Operators MUST be able to answer "how do I reach VM X?" without
running iptables themselves.

## When you would otherwise be tempted to…

- **…`iptables -F` to start clean:** stop. Use
  `aella_cli nat disable && aella_cli nat enable`
  (constitution P-13).
- **…hard-code an external port literal in a script:** stop. Read it from
  `lab-vms.json`.
- **…add a rule directly to `PREROUTING`:** stop. Add it to
  `XDR_LAB_DNAT`. PREROUTING gets exactly one jump rule.
- **…toggle `net.ipv4.ip_forward`:** stop. That's operator-side
  base config (spec 006 §4).
- **…install `iptables-persistent` from the manager:** stop.
  Persistence is operator-side (constitution P-9).
- **…use `iptables-restore` with a generated file:** stop.
  Apply rules with `iptables` invocations only, so the
  structured log captures each mutation.

## Recovery patterns

- **Mismatch between config and reality →**
  `nat disable && nat enable`.
- **Operator added their own rule to `XDR_LAB_DNAT` →**
  `nat verify` flags it; `nat enable` rebuilds the chain
  cleanly.
- **Reboot wiped rules →** operator's bring-up procedure
  re-runs `aella_cli nat enable`. The manager does NOT install
  its own systemd unit.

## Current implementation (read-only Golden-Image validator)

Until the full `xdr-lab-nat-manager.sh` from spec §3.2 ships, the
project operates the **inverse** of the §3 design: the KVM Host
Golden Image owns the rules; the appliance only **observes** them.

- Entrypoint: `xdr-lab-vm-manager.sh nat <verify|status>`.
- Helper: `scripts/nat_state.py` (`refresh`, `verify`, `status`
  subcommands).
- State file: `runtime/state/nat.json` (atomic write).
- Authoritative mapping (Golden-Image contract, **not**
  `lab-vms.json`):

```
sensor-vm        10.10.10.10  ext tcp/1022 -> int tcp/22
linux-server     10.10.10.20  ext tcp/2022 -> int tcp/22
windows-victim   10.10.10.30  ext tcp/3389 -> int tcp/3389
```

**Optional management** (not iptables DNAT — `docs/web-console.md`):

```
windows-build    host tcp/6081 -> 127.0.0.1:5901 (websockify/noVNC)
windows-victim   host tcp/6082 -> 127.0.0.1:5902 (websockify/noVNC)
```

Validate core NAT: `nat verify --iptables-only`. Validate web consoles:
`lab web-console verify <vm>` or `bootstrap/validate-web-console.sh`.

The validator only calls `iptables -S POSTROUTING / PREROUTING /
FORWARD`. **No** `iptables -A / -I / -D / -F / -X / -P` ever runs.
Dry-run mode (`XDR_LAB_DRY_RUN=1`) is a no-op for `nat verify` /
`nat status` since they are already read-only by construction.

When the full mutating manager ships, this validator continues to
own `verify`/`status` as a cross-check against `lab-vms.json`-driven
rebuilds.

## Related specs and skills

- Spec 006 (network architecture), spec 010 (primary), spec
  011 (safety), spec 012 (logging).
- Companion skills: `appliance-cli-skill.md`,
  `sensor-deployment-skill.md` (sensor exposes ssh/https/ui
  externally).
