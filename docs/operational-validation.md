# Operational Validation — XDR Lab KVM Host Appliance

RC-level validation for **host runtime persistence and self-healing** after
real-environment bring-up. This document complements
`docs/environment-sanity-checklist.md` and `docs/release-candidate-checklist.md`.

**Scope:** operational resilience only. These tools do **not** install OVS,
libvirt, `br0`, or Golden Image `iptables`. That remains the **KVM Host Golden
Image bootstrap** phase.

---

## 1. Real-environment finding (br0 DOWN)

During live validation the host showed:

```bash
ip -br addr show br0
# br0    DOWN
```

**Impact chain:**

| Layer | Symptom |
| --- | --- |
| L3 gateway | Guests could not reach `10.10.10.1` |
| CALDERA | Unreachable from lab VMs when bound on lab IP or via gateway path |
| Sandcat | Download / callback failure |
| Operations | CALDERA adversary run ineffective |

**Manual recovery that restored service:**

```bash
sudo ip addr add 10.10.10.1/24 dev br0
sudo ip link set br0 up
```

After recovery: CALDERA reachable, Sandcat check-in succeeded, operations functional.

---

## 2. Operational root cause (br0 DOWN)

The architecture (OVS-native `br0` + `ovs-net`) is **correct**. The failure
mode is **runtime state persistence**, not application logic in
`xdr-lab-vm-manager.sh` / `aella_cli`.

Typical contributing factors on Ubuntu 24.04 + OVS appliances:

1. **No netplan/systemd guarantee for `br0` operstate UP** after reboot when
   `br0` is managed by OVS rather than classic `networkd` DHCP profiles on the
   uplink NIC only.
2. **Boot ordering race:** `openvswitch-switch` recreates the OVS bridge while
   `br0` kernel link stays **DOWN** until explicitly raised or until a
   higher-layer unit assigns the lab gateway address.
3. **Address loss:** `10.10.10.1/24` may be configured in Golden Image
   cloud-init/netplan but not re-applied if the OVS bridge is recreated empty
   at early boot.
4. **libvirtd / ovs-net start before br0 is usable:** guests attach to
   `ovs-net` while the gateway path is down — symptoms look like “CALDERA
   broken” but L3 on the host bridge is the root fault.

This pattern is **known in OVS deployments** when bridge admin state and host
IP are not owned by a single, ordered persistence path. It is **not expected**
for a production appliance image without explicit RC reboot validation.

---

## 3. Validation tooling

Scripts install to `${XDR_ROOT}/bootstrap/` (default `/opt/xdr-lab/bootstrap/`).

| Script | Command | Exit 0 means |
| --- | --- | --- |
| Host network | `sudo ${XDR_ROOT}/bootstrap/validate-host-network.sh` | `br0` UP, gateway IP, OVS, `ovs-net`, forward, NAT contract |
| libvirt | `${XDR_ROOT}/bootstrap/validate-libvirt.sh` | `libvirtd` + `qemu:///system` + active `ovs-net` |
| Sensor identity | `${XDR_ROOT}/bootstrap/validate-sensor-identity.sh` | `sensor_type=stellar_sensor`, versioned Stellar sensor artifacts present, no deprecated cloud-image runtime |
| CALDERA | `${XDR_ROOT}/bootstrap/validate-caldera.sh` | Process, listen port, HTTP probes |
| Web console | `${XDR_ROOT}/bootstrap/validate-web-console.sh` | Running Windows VMs: websockify → `127.0.0.1` QEMU VNC (see `docs/web-console.md`) |
| Self-heal | `sudo ${XDR_ROOT}/bootstrap/fix-runtime-state.sh` | Safe fixes applied (see §5) |

JSON output: append `--json` to any `validate-*.sh` script.

**Operational console** (non-installer):

```bash
sudo ${XDR_ROOT}/xdr-lab.sh
# or non-interactive:
${XDR_ROOT}/xdr-lab.sh host-validate-network
${XDR_ROOT}/xdr-lab.sh host-validate-libvirt
${XDR_ROOT}/xdr-lab.sh host-validate-caldera
sudo ${XDR_ROOT}/xdr-lab.sh host-fix-runtime
```

Structured log: `${XDR_LOGS_DIR}/host-runtime-validation.log` (default
`/opt/xdr-lab/logs/host-runtime-validation.log`).

---

## 4. Example operational outputs

### 4.1 Healthy host network (PASS)

```
=== validate-host-network (br0 / ovs-net) ===
[PASS] br0_exists          interface br0 present
[PASS] br0_up              br0 operstate UP
[PASS] br0_gateway_ip      10.10.10.1/24 on br0
[PASS] ovs_vsctl           ovs-vsctl show succeeded
[PASS] ovs_bridge          OVS bridge br0 in ovs-vsctl show
[PASS] ovs_net_defined     libvirt network ovs-net defined
[PASS] ovs_net_active      ovs-net Active=yes
[PASS] ip_forward          net.ipv4.ip_forward=1
[PASS] nat_masquerade      POSTROUTING MASQUERADE for 10.10.10.0/24
[PASS] reverse_nat         reverse NAT contract verified (nat_state.py verify)
---
RESULT: PASS (exit 0)
```

### 4.2 Failed state (br0 DOWN — observed in RC)

```
=== validate-host-network (br0 / ovs-net) ===
[PASS] br0_exists          interface br0 present
[FAIL] br0_up              br0 is DOWN (ip -br link)
[FAIL] br0_gateway_ip      missing inet 10.10.10.1/24 on br0
...
---
RESULT: FAIL (exit 50)
```

### 4.3 Self-heal transcript

```
[INFO] ACTION: bring br0 up — ip link set br0 up
[INFO] ACTION: restore 10.10.10.1/24 on br0 — ip addr add 10.10.10.1/24 dev br0
=== post-fix validation (read-only) ===
...
RESULT: PASS (exit 0)
```

---

## 5. Safe self-healing contract (`fix-runtime-state.sh`)

**Allowed actions only:**

| Condition | Action |
| --- | --- |
| `br0` exists, DOWN | `ip link set br0 up` |
| `br0` missing `10.10.10.1/24` | `ip addr add 10.10.10.1/24 dev br0` |
| `ovs-net` defined, inactive | `virsh net-start ovs-net` |
| `libvirtd` inactive | `systemctl restart libvirtd` |

**Forbidden:** recreate `br0`, `ovs-vsctl del-br`, redefine destructive libvirt
networks, `iptables` mutation, VM destroy, package reinstall.

Use `--dry-run` to print intended actions without applying them.

---

## 6. Reboot persistence validation (RC procedure)

Run after every Golden Image change or before RC sign-off.

### 6.1 Pre-reboot baseline

```bash
source ${XDR_ROOT}/config/paths.sh
${XDR_ROOT}/bootstrap/validate-host-network.sh
${XDR_ROOT}/bootstrap/validate-libvirt.sh
${XDR_ROOT}/bootstrap/validate-sensor-identity.sh
${XDR_ROOT}/bootstrap/validate-caldera.sh
aella_cli lab nat verify
aella_cli lab status all
```

Record outputs in the change log.

### 6.2 Reboot

```bash
sudo reboot
```

### 6.3 Post-reboot (within 5 minutes of login)

```bash
# 1) Host plane
${XDR_ROOT}/bootstrap/validate-host-network.sh || true
ip -br addr show br0
ip -br link show br0

# 2) If validation fails — safe heal first (NOT full reinstall)
sudo ${XDR_ROOT}/bootstrap/fix-runtime-state.sh

# 3) libvirt + CALDERA
${XDR_ROOT}/bootstrap/validate-libvirt.sh
${XDR_ROOT}/bootstrap/validate-caldera.sh

# 4) Lab contract
aella_cli lab nat verify
aella_cli lab scenario bootstrap validate
aella_cli lab scenario agent status
```

### 6.4 RC pass criteria

| Check | Pass |
| --- | --- |
| `validate-host-network.sh` | Exit **0** without manual `ip` commands |
| `validate-libvirt.sh` | Exit **0** |
| `validate-sensor-identity.sh` | Exit **0** with `stellar_sensor_ready=true` |
| `validate-caldera.sh` | Exit **0** or documented bind on `127.0.0.1` only with guest path waived |
| Guest gateway | From `linux-server`: `ping -c2 10.10.10.1` |
| Sandcat | `agent status` shows expected roles after reboot |

If post-reboot validation **always** requires `fix-runtime-state.sh`, the
Golden Image needs **persistent br0 addressing** (§7) — self-heal is a
safety net, not the primary persistence mechanism.

---

## 7. systemd ordering guidance (findings — do not overengineer)

Investigated ordering concerns between:

| Unit | Role |
| --- | --- |
| `openvswitch-switch.service` | Creates OVS bridges (`br0`) |
| `network-online.target` | Declares routable management NIC ready |
| `libvirtd.service` | Starts hypervisor; may auto-start `ovs-net` |
| `caldera.service` | CALDERA HTTP (optional bootstrap) |

**Findings:**

1. **`openvswitch-switch` must be active before libvirt attaches guests to
   `ovs-net`.** If libvirt starts first, `virsh net-start ovs-net` may succeed
   while `br0` remains administratively DOWN — validate with
   `validate-host-network.sh`, not only `virsh net-info`.
2. **`network-online.target` alone does not raise OVS internal bridge IP.**
   Management NIC (`ens192`) online ≠ lab gateway on `br0`.
3. **`caldera.service` should remain `After=network-online.target`** (already
   in `bootstrap/caldera-server-bootstrap.sh`). If CALDERA must serve guests on
   `10.10.10.1`, also ensure **host network validation passes before
   `systemctl start caldera`** in RC checklists.
4. **Recommended Golden Image addition (operator-owned):** a small
   **oneshot** unit *after* `openvswitch-switch.service` that runs
   `fix-runtime-state.sh --dry-run` or a netplan fragment pinning
   `10.10.10.1/24` on `br0` with `optional: true`. XDR Lab ships the validator
   and safe healer; **image bake** owns whether that unit is enabled.

No additional systemd units are installed by this repository by design
(appliance philosophy: validate + safe heal, not silent re-bootstrap).

---

## 8. Is the appliance reboot-safe today?

| Aspect | Status |
| --- | --- |
| Architecture (OVS + ovs-net + reverse NAT contract) | Stable — no change required |
| **Observed RC behavior** | `br0` may boot **DOWN** without gateway IP — **not RC-safe** without persistence or automated heal |
| **With `fix-runtime-state.sh` in post-boot runbook** | **Operationally recoverable** in minutes |
| **With Golden Image br0 persistence + RC reboot test** | Target **RC-safe** state |

**Additional persistence handling required:** yes — at the **Golden Image**
layer (netplan/systemd oneshot ordering), documented in
`docs/release-hardening.md`. Runtime scripts close the validation gap; they do
not replace image-level persistence.

---

## 9. Related documents

- `docs/release-hardening.md` — RC persistence requirements
- `docs/troubleshooting.md` — symptom → validation → recovery
- `docs/runtime-state-artifacts.md` — JSON state files + host logs
- `docs/environment-sanity-checklist.md` — full lab checklist
- `docs/release-candidate-checklist.md` — RC sign-off matrix
