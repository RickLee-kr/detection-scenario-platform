# Release Hardening — Host Runtime Persistence (RC)

Operational requirements for declaring the XDR Lab KVM host appliance
**reboot-safe** at release-candidate level. Complements
`docs/release-candidate-checklist.md` §§1–3.

---

## 1. RC-level requirement: OVS bridge state persistence

**OVS bridge state persistence is now an RC-level operational requirement.**

A signed-off Golden Image MUST satisfy, **without manual intervention** after
`reboot`:

- `br0` exists as an OVS bridge
- `br0` kernel link **UP**
- `10.10.10.1/24` assigned on `br0`
- `ovs-net` **Active: yes**
- `net.ipv4.ip_forward=1`
- Golden Image MASQUERADE + reverse NAT contract (`aella_cli lab nat verify` exit 0)

Validation authority:

```bash
${XDR_ROOT}/bootstrap/validate-host-network.sh
```

Exit **0** on cold boot is mandatory for RC sign-off.

---

## 2. What hardening is NOT

Per appliance constitution:

- `xdr-lab.sh` / `fix-runtime-state.sh` are **not** infrastructure installers
- No blind `ovs-vsctl del-br`, no libvirt network redefine, no VM destroy
- No conversion back to Linux bridge
- No `iptables` mutation in validation or heal paths (`nat_state.py` remains read-only)

---

## 3. Golden Image responsibilities (bootstrap phase)

| Responsibility | Owner | Notes |
| --- | --- | --- |
| Install `openvswitch-switch`, libvirt | Golden Image | One-time |
| Create OVS `br0`, define `ovs-net` | Golden Image | `config/ovs-net.xml` |
| Persist `10.10.10.1/24` on `br0` | Golden Image netplan/systemd | **Gap observed in RC** |
| MASQUERADE + DNAT rules | Golden Image iptables | Verified by `nat verify` |
| CALDERA systemd (optional) | `bootstrap/caldera-server-bootstrap.sh` | Bind plan documented |

---

## 4. Runtime responsibilities (appliance repo)

| Tool | Role |
| --- | --- |
| `validate-host-network.sh` | Detect drift / post-reboot failure |
| `validate-libvirt.sh` | Hypervisor + `ovs-net` health |
| `validate-caldera.sh` | CALDERA unit, venv, port, HTTP path for operators and guests |
| `validate-appliance.sh` | Aggregate validator (host-network + CALDERA + libvirt) |
| `ensure-caldera-runtime.sh` | CALDERA venv / requirements self-heal |
| `repair-caldera-service.sh` | Align `caldera.service` with runtime user and venv |
| `fix-runtime-state.sh` | **Safe** recovery when persistence slips |
| `xdr-lab.sh` | Operator console — validation menu only |

Install path: `sudo installer/cli-installer.sh` → `/opt/xdr-lab/`.

---

## 5. Recommended Golden Image persistence patterns

Choose **one** primary pattern (image team decision):

### 5.1 netplan OVS bridge stanza (preferred when netplan owns lab NIC)

Declare `br0` as OVS bridge with static `10.10.10.1/24` in the image netplan.
Ensure `openvswitch-switch` starts before `netplan apply` or use
`renderer: networkd` ordering documented for your Ubuntu build.

### 5.2 systemd oneshot after OVS (minimal)

Example unit shape (reference only — **not installed by this repo**):

```ini
[Unit]
Description=XDR Lab br0 runtime gate
After=openvswitch-switch.service
Wants=openvswitch-switch.service
Before=libvirtd.service

[Service]
Type=oneshot
ExecStart=/opt/xdr-lab/bootstrap/fix-runtime-state.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

Enable only after dry-run review on the image. Pair with monitoring via
`validate-host-network.sh` in RC automation.

### 5.3 Operator cron / login hook (weakest)

Acceptable for dev labs only — **not** RC sign-off quality.

---

## 6. Service ordering summary

```
openvswitch-switch.service
        ↓
  br0 UP + 10.10.10.1/24   ← RC gap if missing
        ↓
libvirtd.service → ovs-net active
        ↓
VMs / CALDERA / Sandcat paths
```

`caldera.service`: keep `After=network-online.target`; add operational gate
`validate-host-network.sh` before live adversary runs when guests call
`10.10.10.1:8888`.

---

## 7. RC sign-off addendum

Add to release checklist (see `docs/release-candidate-checklist.md`):

1. Cold reboot ×2 with `validate-host-network.sh` exit 0 each time
2. `fix-runtime-state.sh` **not required** for pass (healer is contingency)
3. `linux-server` pings `10.10.10.1` post-reboot
4. `aella_cli lab scenario agent status` true for planned roles after reboot

Record: date, image version, `XDR_ROOT`, validator exit codes, operator initials.

---

## 8. CALDERA service persistence (optional RC gate)

When CALDERA runs on the appliance host (`/opt/caldera`), treat **`caldera.service` reboot survival** as an operational requirement alongside host-network persistence.

**Authority:**

```bash
${XDR_ROOT}/bootstrap/validate-caldera.sh
${XDR_ROOT}/bootstrap/validate-appliance.sh
```

**Repair chain (idempotent, no manual venv steps):**

```bash
sudo ${XDR_ROOT}/bootstrap/ensure-caldera-runtime.sh --apt-repair
sudo ${XDR_ROOT}/bootstrap/repair-caldera-service.sh --start
```

Or one shot: `sudo ${XDR_ROOT}/bootstrap/deploy-caldera-runtime-fix.sh`

**Service ordering:** `caldera.service` must remain `After=network-online.target xdr-lab-host-network.service` so guests calling `10.10.10.1:8888` see a restored lab gateway before CALDERA starts.

**RC failures to record explicitly:**

| Exit / journal | Meaning |
| --- | --- |
| `217/USER` | `User=` in unit does not exist — run repair chain |
| `203/EXEC` | `/opt/caldera/.venv/bin/python3` missing — `ensure-caldera-runtime.sh` |
| `validate-caldera` exit **20** | Port not listening (including false “running” restart loops) |
| `validate-caldera` exit **30** | HTTP `/api/agents` not reachable (connection refused / no response) |
| `validate-caldera` exit **35** | HTTP reachable but REST not authenticated (`302`→`/login`, wrong/missing `KEY`) |

Shell regression tests: `tests/test_caldera_runtime.sh`.
