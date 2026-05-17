# Deployment Readiness — XDR Lab Appliance

Operator-facing guidance for **consistent deployment**, **first-boot
expectations**, and **capacity planning**. This document does not change
runtime contracts (IPs, ports, schemas, or code paths). Authoritative
geometry remains in `docs/specs/006-network-architecture/spec.md`,
`docs/specs/007-ovs-mirror-policy/spec.md`, and `docs/specs/010-reverse-nat-policy/spec.md`.

---

## 1. Required host resources

### 1.1 Hypervisor (when the appliance runs as a nested guest)

- **Nested virtualization**: VT-x / AMD-V exposed to the Ubuntu guest.
- **vSwitch / port group**: Promiscuous mode, forged transmits, and MAC
  address changes allowed on the segment that carries lab traffic (nested
  L2 + OVS mirror expectations align with `README.md` §3).

### 1.2 Ubuntu 24.04 appliance host

- **Role**: Single orchestration host running libvirt/KVM, Open vSwitch,
  and `aella_cli`.
- **Accounts**: The operator user must be in `libvirt`, `kvm`, and
  `sudo` (see `README.md` §3).
- **libvirt storage pool**: Writable default pool at
  `/var/lib/libvirt/images` (or an equivalent pool referenced by your
  install; images and overlays must fit).

### 1.3 Software packages

Minimum set matches `README.md` §3 (qemu-kvm, libvirt, OVS, virtinst,
cloud-image tooling, Python 3, jq, curl).

---

## 2. CPU and RAM recommendations

### 2.1 Sum of declared guest allocations (`config/lab-vms.json`)

| VM | vCPU | RAM (MiB) |
| --- | --- | --- |
| sensor-vm | 4 | 6144 |
| windows-victim | 2 | 4096 |
| linux-server | 2 | 2048 |
| test-vm1 | 1 | 1024 |
| **Declared guest totals** | **9** | **13312** (~13 GiB) |

### 2.2 Host headroom (recommended)

- **RAM**: Provision the appliance guest with **at least 24–32 GiB** if
  all four VMs run concurrently, plus any CALDERA or capture workloads on
  the host. The historical **16 GiB** floor in `README.md` is a minimum
  for a reduced footprint (fewer concurrent guests or smaller edits to
  `lab-vms.json`).
- **vCPU**: **≥ 12 vCPU** on the appliance guest is comfortable when all
  lab domains are running and scenarios generate parallel disk/network
  activity. **4 vCPU** remains a documented historical minimum for the
  appliance guest only when the operator accepts contention.

---

## 3. Disk sizing guidance

Plan for **four cost centers**: base image cache, per-VM runtime qcow2,
libvirt internal snapshots, and logs/state under `${XDR_BASE}` (default
`/opt/xdr-lab`).

### 3.1 Declared guest disk sizes (`lab-vms.json`)

| VM | `disk_size_gb` |
| --- | --- |
| sensor-vm | 80 |
| windows-victim | 60 |
| linux-server | 40 |
| test-vm1 | 20 |
| **Sum** | **200** |

Thin provisioning still needs **burst space** for snapshot chains and
guest growth.

### 3.2 Practical host disk targets

| Concern | Suggested planning range |
| --- | --- |
| Appliance root + `/var/lib/libvirt/images` | **≥ 200 GiB** thin for a minimal lab; **≥ 400 GiB** for comfortable snapshot and cache headroom |
| `${XDR_BASE}/images` (downloads, Windows tree) | Size of your Stellar sensor qcow2, Windows golden qcow2s, and victim Linux cloud base — often **tens of GiB** |
| `${XDR_BASE}/runtime` | Runtime disks grow with guest use; budget **snapshot overhead** on top of declared sizes |
| Repository checkout (`images/`, `logs/`) | When `XDR_BASE` points at the repo, keep the same totals on the filesystem backing `PROJECT_ROOT` |

---

## 4. Snapshot storage expectations

- Snapshots are created through **`aella_cli lab snapshot create`** (batch
  over the core trio: sensor-vm, linux-server, windows-victim — see
  `README.md` §9 and `docs/specs/009-snapshot-runtime/spec.md` for the
  governance model).
- **qcow2 internal snapshots** increase backing-file size nonlinearly with
  write churn during scenarios. After repeated live CALDERA runs, expect
  **notable growth** on `windows-victim` and `linux-server` disks first.
- **Operational rule**: keep free space on the volume that holds
  `${LIBVIRT_IMAGE_DIR}` and runtime paths above **20–30%** before large
  scenario campaigns.

---

## 5. Mirror traffic sizing considerations

- The OVS mirror copies **ingress frames** from selected lab tap ports to
  the sensor output port (rx-only semantics; see spec 007).
- **Rule of thumb**: the sensor sees **roughly one extra copy** of each
  mirrored frame compared with a non-mirrored lab. Budget sensor **disk
  and CPU for PCAP/IDS** in proportion to expected **east-west Mbps**
  during scenarios (burst traffic from recon scans, lateral movement, or
  exfil drills can spike briefly).
- **Uplink impact**: mirror traffic stays on `br0`; it does **not** double
  NAT egress unless the sensor forwards captures externally.

---

## 6. Recommended lab isolation

- **Management plane**: Restrict SSH on the appliance host and reverse-NAT
  ports (`README.md` §5.1) to operator networks only.
- **Lab subnet**: Treat `10.10.10.0/24` as **untrusted** — no routing to
  production VLANs without explicit controls.
- **CALDERA**: If CALDERA listens beyond localhost, firewall callbacks and
  UI/API ports per `docs/caldera-integration.md` §2.
- **DNS / egress**: Decide whether lab guests may reach the public
  internet; outbound NAT is operator-controlled (spec 006 §3.3).

---

## 7. Expected network topology

High-level view (same story as `README.md` §2):

- **External / management NIC** on the appliance: operator access,
  reverse-NAT entry, and optional outbound NAT.
- **`br0` + `ovs-net`**: **Open vSwitch bridge** `br0` with libvirt
  network **`ovs-net`** using `<virtualport type='openvswitch'/>` (see
  `config/ovs-net.xml`); all lab VMs attach here.
- **Lab subnet**: `10.10.10.0/24`, gateway `10.10.10.1` on the host.
- **Static addressing**: Per-VM IPs from `lab-vms.json` and cloud-init
  seeds — **no lab DHCP**.
- **Reverse NAT**: Golden port map (e.g. 1022 → sensor-vm:22, 2022 →
  linux-server:22, 3389 → windows-victim:3389) — see `README.md` §5.1.

---

## 8. Stellar Sensor Artifact Readiness

Operational readiness is defined only for the official
**Stellar Cyber Modular Data Sensor** architecture. An Ubuntu cloud-image VM
used as `sensor-vm` is deprecated development material and cannot pass
operational readiness. A live run requires both files in the versioned sensor
cache:

```text
/opt/xdr-lab/images/sensor/6.2.0/virt_deploy_modular_ds.sh
/opt/xdr-lab/images/sensor/6.2.0/aella-modular-ds-6.2.0.qcow2
```

If these files are missing, validators print:

```text
stellar_sensor_artifact_found=false
stellar_sensor_ready=false
READY_FOR_STELLAR_SENSOR_SCENARIO=false
```

When the real Stellar sensor is present, validators report:

```text
sensor_type=stellar_sensor
stellar_sensor_artifact_found=true
stellar_sensor_ready=true
READY_FOR_STELLAR_SENSOR_SCENARIO=true
```

Install upstream artifacts explicitly:

```bash
sudo install -D -m 0755 <artifact>/virt_deploy_modular_ds.sh /opt/xdr-lab/images/sensor/6.2.0/virt_deploy_modular_ds.sh
sudo install -D -m 0644 <artifact>/aella-modular-ds-6.2.0.qcow2 /opt/xdr-lab/images/sensor/6.2.0/aella-modular-ds-6.2.0.qcow2
```

Stellar download credentials belong in `/etc/xdr-lab/stellar-download.env`
with root-only permissions. Do not store them in code, JSON, git, or logs.
Placeholder URLs such as `REPLACE_ME.example.invalid` are configuration errors.
Download commands must stop with `CONFIG_PLACEHOLDER_ERROR` instead of trying to
fetch them.

---

## 9. Related documents

- First-time verification: `docs/environment-sanity-checklist.md`
- Real hardware / nested bring-up: `docs/real-environment-bringup.md`
- Release candidate sign-off: `docs/release-candidate-checklist.md`
- CI / smoke commands: `docs/runtime-smoke-validation.md`
- Recovery: `docs/operational-recovery.md`
- Cleanup and retention: `docs/operational-maintenance.md`
- Future packaging layout: `docs/packaging-guidance.md`
- CALDERA: `docs/caldera-integration.md`
