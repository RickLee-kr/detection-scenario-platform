# Troubleshooting — XDR Lab Appliance

Host-focused triage for **operational resilience** and links to scenario /
CALDERA matrices. For adversary-run failures see also
`docs/operator-troubleshooting-matrix.md` and `docs/caldera-integration.md` §9.

---

## `br0_down` — lab gateway unreachable

| Field | Content |
| --- | --- |
| **Symptoms** | `ip -br addr show br0` → `DOWN`; guests cannot ping `10.10.10.1`; Sandcat / CALDERA failures from VMs |
| **Likely causes** | OVS bridge recreated at boot without admin UP; missing netplan persistence for lab IP; boot race before OVS ready |
| **Validation** | `${XDR_ROOT}/bootstrap/validate-host-network.sh`; `ip -br link show br0`; `ovs-vsctl show` |
| **Expected** | `br0` operstate **UP**; `inet 10.10.10.1/24` present; exit 0 from validator |
| **Recovery** | `sudo ${XDR_ROOT}/bootstrap/fix-runtime-state.sh` — or manual: `sudo ip link set br0 up`; `sudo ip addr add 10.10.10.1/24 dev br0` |
| **RC fix** | Golden Image persistence — `docs/release-hardening.md` |

---

## `br0_missing_ip` — bridge up but no gateway

| Field | Content |
| --- | --- |
| **Symptoms** | `br0` UP but no `10.10.10.1`; partial connectivity |
| **Validation** | `ip -4 addr show dev br0`; `validate-host-network.sh` exit 12 |
| **Recovery** | `fix-runtime-state.sh` or `sudo ip addr add 10.10.10.1/24 dev br0` |

---

## `ovs_net_inactive` — libvirt network down

| Field | Content |
| --- | --- |
| **Symptoms** | VM start failures; `virsh net-info ovs-net` → `Active: no` |
| **Validation** | `validate-libvirt.sh`; `virsh net-list --all` |
| **Recovery** | `sudo virsh net-start ovs-net` (also done by `fix-runtime-state.sh`) |
| **Note** | Does not fix `br0` DOWN — run host network validation first |

---

## `libvirtd_inactive`

| Field | Content |
| --- | --- |
| **Symptoms** | `virsh` connection errors |
| **Validation** | `validate-libvirt.sh`; `systemctl status libvirtd` |
| **Recovery** | `sudo systemctl restart libvirtd` (`fix-runtime-state.sh`) |

---

## `caldera_unreachable_from_guests`

| Field | Content |
| --- | --- |
| **Symptoms** | CALDERA OK on host localhost; VMs cannot callback |
| **Validation** | `validate-caldera.sh` (checks `http://10.10.10.1:8888`); guest `curl` / `ss` |
| **Likely causes** | `br0` DOWN; CALDERA bound `127.0.0.1` only; firewall |
| **Recovery** | Fix host network first; align `CALDERA_LISTEN_HOST` per `docs/caldera-integration.md` §2 |

---

## `nat_contract_drift`

| Field | Content |
| --- | --- |
| **Symptoms** | `aella_cli lab nat verify` exit non-zero; SSH via external ports fails |
| **Validation** | `aella_cli lab nat status`; `validate-host-network.sh` (MASQUERADE + reverse NAT) |
| **Recovery** | Restore Golden Image iptables — **not** automated by XDR Lab heal scripts |

---

## Operational console quick path

```bash
sudo ${XDR_ROOT}/xdr-lab.sh
# 1 → host network
# 2 → libvirt
# 3 → CALDERA
# 4 → safe self-heal
```

---

## Reboot validation failure

1. Run §6 procedure in `docs/operational-validation.md`
2. If heal fixes every reboot → implement Golden Image persistence (`docs/release-hardening.md`)
3. Re-run `docs/release-candidate-checklist.md` network section

---

## Escalation

- ESXi portgroup promiscuous / forged transmits (nested lab) — `README.md` §3
- Upstream CALDERA defects — server logs / `journalctl -u caldera.service`
- Image team — netplan/OVS persistence not owned by appliance repo
