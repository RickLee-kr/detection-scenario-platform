# XDR Lab Appliance

A self-contained XDR / NDR security lab built on **KVM + Open vSwitch**, with
cloud-init Linux provisioning, qcow2 Windows deployment, traffic-mirror
sensor placement, and reverse-NAT external access. The appliance is
operated through a single Python CLI (`aella_cli`) backed by a shell
runtime engine.

> **Project root**: `/home/aella/xdr-lab-appliance` — this is the **only**
> official source of truth. Older locations (`/home/aella/Stellar appliance cli`,
> `/home/aella/xdr-lab-cloudinit`, `/home/aella/cloudinit`) are retained as
> read-only references until the operator confirms migration parity.

---

## 1. Project overview

The XDR Lab Appliance turns a single Ubuntu 24.04 host (typically a VM
under ESXi) into a fully orchestrated lab:

- A **lab L2 segment** (10.10.10.0/24) hosted on an Open vSwitch bridge `br0`.
- Three classes of VMs orchestrated by `aella_cli lab`:
  - `sensor-vm`     — NDR sensor / packet collector with SPAN-like mirror.
  - `victim-linux`  — cloud-init provisioned Ubuntu 24.04 (attack target / pivot).
  - `windows-victim`— qcow2 Windows endpoint (EDR / behavioural surface).
  - `test-vm1`      — disposable Linux for ad-hoc scenarios.
- A **reverse-NAT** layer (host iptables) that exposes a curated port map
  for each VM to the operator over the host's external NIC.
- A **TUI / CLI** (`aella_cli`) that wraps `virsh`, `virt-install`,
  `qemu-img`, `cloud-localds`, and OVS commands behind a uniform
  command surface with structured logging.

The lab is designed to be **rebuilt from source** at any time:
`aella_cli lab destroy all && aella_cli lab deploy all`.

---

## 2. Architecture

```
                ┌────────────────────────────────────────────┐
                │  ESXi host  (vmnic0 → vSwitch0)            │
                │   └── Ubuntu 24.04 VM (this appliance)     │
                │        ├── ens192 (mgmt / external NAT)    │
                │        └── ens224 → br0 (OVS, lab L2)      │
                └────────────┬───────────────────────────────┘
                             │
                  ┌──────────┴──────────┐
                  │   br0  (ovs-net)    │   10.10.10.0/24
                  └──┬──────┬──────┬────┘
                     │      │      │      ┌──────────────┐
              .10 ───┘      │      └─.30  │ windows-     │
             ┌────────────┐ │           │ │ victim       │
             │ sensor-vm  │ │           │ │ (qcow2)      │
             │ (mirror)   │ │           │ └──────────────┘
             └────────────┘ │           .20
                            │      ┌──────────────┐
                            └──.40 │ victim-linux │
                          ┌────────│ (cloud-init) │
                          │test-vm1│ ubuntu 24.04 │
                          └────────└──────────────┘

Mirror plane:
    OVS port-mirror: tap.* (any) → sensor-vm tap (rx-only)
External access:
    host ens192:1022  → sensor-vm:22
    host ens192:3389  → windows-victim:3389
    host ens192:2022  → victim-linux:22
    host ens192:22040  → test-vm1:22
```

See `docs/specs/006-network-architecture/spec.md` for the authoritative
network plane and `docs/specs/007-ovs-mirror-policy/spec.md` for the
mirror policy.

**Release-readiness operator docs** (deployment ergonomics, checklists,
recovery, retention, future packaging, RC validation, smoke guidance,
real-environment bring-up, **host runtime validation / reboot persistence**):
`docs/deployment-readiness.md`,
`docs/environment-sanity-checklist.md`, `docs/operational-validation.md`,
`docs/release-hardening.md`, `docs/troubleshooting.md`,
`docs/runtime-state-artifacts.md`, `docs/operational-recovery.md`,
`docs/operational-maintenance.md`, `docs/packaging-guidance.md`,
`docs/release-candidate-checklist.md`, `docs/runtime-smoke-validation.md`,
`docs/real-environment-bringup.md`, first live adversary run
(`docs/live-run-playbook.md`), evidence/state inspection
(`docs/runtime-evidence-collection.md`, `docs/runtime-state-inspection.md`),
and triage (`docs/operator-troubleshooting-matrix.md`).

---

## 3. Requirements

### ESXi host

- VT-x / AMD-V exposed to the guest (nested virtualization).
- Promiscuous mode + Forged transmits + MAC changes allowed on the lab
  vSwitch portgroup (required for nested L2 + OVS mirror).
- At least 16 GB RAM / 4 vCPU / 200 GB thin-provisioned disk for the
  Ubuntu appliance guest.

### Ubuntu 24.04 host (this appliance)

Required packages:

```
qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils
openvswitch-switch virtinst cloud-image-utils genisoimage
python3 python3-pip jq curl
```

User `aella` must be in groups `libvirt`, `kvm`, `sudo`. The host must
have a writable libvirt image pool at `/var/lib/libvirt/images`.

---

## 4. KVM / Open vSwitch architecture

- libvirt is the orchestrator; OVS is the dataplane.
- A single OVS bridge `br0` carries all lab traffic (definition:
  `config/ovs-net.xml`, registered with `virsh net-define`).
- All VMs attach via `--network network=ovs-net,model=virtio`.
- Static IPs are assigned by cloud-init (`network-config` on the seed
  ISO) — DHCP is intentionally **not** used inside the lab.
- The VM manager (`scripts/xdr-lab-vm-manager.sh`) is the single point
  of contact between Python and libvirt/qemu. Python never shells out
  to `virsh`/`virt-install` directly.

---

## 5. Reverse-NAT architecture

The host's external NIC (e.g. `ens192`) exposes a fixed map of TCP
ports → internal lab IP:port via iptables `DNAT`. The mapping lives in
`config/lab-vms.json` under each VM's `external_nat_port_mapping`. The
appliance will, in a future phase, materialize these rules
idempotently from the JSON.

Design constraints:

- Each VM has a deterministic external port range (no random ports).
- The mapping is **append-only**: new VMs get new ports; existing
  mappings never change without an operator decision.
- See `docs/specs/010-reverse-nat-policy/spec.md`.

### 5.1 Canonical operator access (core lab)

These values are the **Golden Image** reverse-NAT contract. Host `iptables`
must expose them; `config/lab-vms.json` must list the same external ports
for the three core VMs so `access` and `nat verify` stay aligned.

| VM | Internal IP | Service | External (host) → guest |
| --- | --- | --- | --- |
| `sensor-vm` | `10.10.10.10` | SSH | TCP **1022** → 22 |
| `victim-linux` | `10.10.10.20` | SSH | TCP **2022** → 22 |
| `windows-victim` | `10.10.10.30` | RDP | TCP **3389** → 3389 |

**Optional management** (not iptables DNAT — websockify on the host only):

| VM | websockify (host) | QEMU VNC (localhost) | URL (on appliance) |
| --- | --- | --- | --- |
| `windows-build` | TCP **6081** | `127.0.0.1:5901` | `http://127.0.0.1:6081/` |
| `windows-victim` | TCP **6082** | `127.0.0.1:5902` | `http://127.0.0.1:6082/` |

Requires `XDR_LAB_WEB_CONSOLE_PORT_MAP="windows-build=6081,windows-victim=6082"`
and `lab web-console start <vm>`. See `docs/web-console.md`.

Typical CLI (replace `<EXT>` with the appliance’s external IPv4 from
`access` output):

```bash
ssh -p 1022 sensor@<EXT>
ssh -p 2022 ubuntu@<EXT>
# RDP client → <EXT>:3389
# Browser (optional) → http://127.0.0.1:6082/   (after: lab web-console start windows-victim)
```

Read-only checks:

```bash
bash scripts/xdr-lab-vm-manager.sh access
bash scripts/xdr-lab-vm-manager.sh nat verify --iptables-only   # core DNAT only
bash scripts/xdr-lab-vm-manager.sh web-console verify windows-victim
${XDR_ROOT}/bootstrap/validate-web-console.sh
```

Example `nat.json` shape (abridged): `docs/examples/runtime-state/nat.json.example`.

---

## 6. OVS mirror overview

`sensor-vm` receives a copy of every frame seen by every other lab
`tap*` interface via an OVS port mirror (`select_all=true,
output_port=<sensor tap>`). The mirror is one-directional: the sensor
cannot inject traffic. This is the substrate for IDS / packet capture
without re-cabling the lab.

See `docs/specs/007-ovs-mirror-policy/spec.md` for the policy and
`docs/skills/ovs-mirror-skill.md` for the operational runbook.

---

## 7. Cloud-init Linux deployment

`victim-linux` and `test-vm1` are provisioned via cloud-init:

1. Ubuntu 24.04 cloud base image is fetched once and cached under
   `${XDR_BASE}/images/victim-linux/`.
2. A per-VM seed ISO is generated from `user-data`, `meta-data`, and a
   `network-config` (static IP, gateway, DNS).
3. `qemu-img create -b <base>` builds a thin overlay; `virt-install
   --import` boots it.
4. The VM manager validates SSH connectivity and reboot persistence
   before declaring the deploy successful.

Templates live in `cloud-init/<vm-name>/` and the manual one-shot
helper is `scripts/create-cloud-vm.sh`.

---

## 8. Windows qcow2 deployment

`windows-victim` is deployed from a prepared qcow2 image (already
generalized + qemu-guest-agent installed). The VM manager:

- Copies the qcow2 from the cached download to the runtime location.
- Resizes the disk to `disk_size_gb`.
- Calls `virt-install --import --os-variant win2k22`.

No cloud-init for Windows; configuration is baked into the qcow2 or
performed post-boot via WinRM (a future phase).

---

## 9. TUI goals

`aella_cli` exposes two top-level namespaces:

```
aella_cli appliance status | info
aella_cli lab deploy|download|start|stop|destroy|status <vm|all> [--nodownload] [--dry-run]
aella_cli lab snapshot create|revert|list|delete [<vm>] [<name>] [--dry-run]
```

`windows-victim` (UEFI/pflash) uses **external disk-only** snapshots; Linux VMs use internal libvirt snapshots. See `docs/runtime-state-inspection.md` §6.

```
aella_cli lab mirror apply|verify|traffic [--dry-run]
aella_cli lab nat verify|status [--dry-run]
aella_cli lab scenario list|bootstrap validate|atomic validate|pack validate|status|run <name>|stop|telemetry <NAME|last|verify>|agent <status|deploy|remove> [--snapshot-before] [--dry-run]
```

Future TUI work (tracked in `docs/specs/`):

- Real-time VM state dashboard (libvirt events → curses).
- One-key snapshot rollback (spec 009).
- Scenario runner extensions (spec 008): post-snapshot automation,
  per-scenario expected-telemetry assertions, multi-engine adapters
  (Atomic Red Team / Sliver / Mythic). CALDERA emulation is already
  wired through `aella_cli lab scenario …` — see
  `docs/caldera-integration.md`.

---

## 10. Attack simulation overview

Attack emulation is delegated to **MITRE CALDERA** via the official
`/api/rest` contract; XDR Lab never ships its own shell-script attacks.
The orchestrator lives at `scripts/caldera_orchestration.py` and is
driven through `aella_cli lab scenario …` (engine entrypoint:
`xdr-lab-vm-manager.sh scenario …`).

### 10.1 Configured scenarios

Scenario packs under `scenarios/*.json` ship with `caldera.adversary_id: null`;
operators fill a CALDERA adversary UUID in `config/caldera-lab.json::scenarios.<id>.adversary_id`
(fallback merge) or override the pack locally — see `docs/caldera-integration.md` §§4.4c–4.5a.

| scenario_id (`scenario list`) | Intent                              | Typical targets (from packs)      |
| ----------------------------- | ----------------------------------- | --------------------------------- |
| `recon`                       | discovery (ping/nslookup/curl/scan) | sensor-vm, victim-linux, windows-victim |
| `web`                         | HTTP / webshell-style patterns      | (see pack `target_vms`)           |
| `c2`                          | callback / channel-style behaviour  | (see pack)                        |
| `lateral`                     | SMB / PsExec / RDP movement         | (see pack)                        |
| `exfil`                       | staged upload / download            | (see pack)                        |
| `web-test` (legacy JSON only) | HTTP / webshell simulation          | windows-victim, victim-linux      |
| `lateral-movement` (legacy)   | lateral movement                    | windows-victim ↔ victim-linux    |
| `exfiltration` (legacy)      | exfil patterns                      | windows-victim, victim-linux      |

If the merged `adversary_id` is still empty, non-dry `scenario run` is refused (`status=blocked`).
See `docs/caldera-integration.md` §4 for UI/REST UUID lookup.

#### Five mandatory steps before a live CALDERA run

1. `aella_cli lab scenario pack validate` — pack schema / VM names; `adversary_id` null → warning only (§4.5a).
2. `aella_cli lab scenario bootstrap validate` — CALDERA HTTP, API key, plugins/atomic, ART path hints on the appliance.
3. `aella_cli lab scenario atomic validate` — ART repo/exec readiness on `victim-linux` / `windows-victim`.
4. `aella_cli lab scenario agent deploy` then `aella_cli lab scenario agent status` — Sandcat present and matrix shows expected VMs.
5. Set `config/caldera-lab.json::scenarios.<id>.adversary_id` to a real CALDERA UUID (packs stay null in git), run `aella_cli lab scenario list` to confirm the merged row, then `aella_cli lab scenario status --human` before `scenario run <id> --snapshot-before`.

**Minimum sequence (first live recon):** after steps 1–5 above, run  
`aella_cli lab scenario run <id> --snapshot-before --dry-run` and read the preflight + checklist block on stdout, then run the **same command without `--dry-run`**. After the live run, use **`aella_cli lab scenario status --human`** (post-run review block + `last_live_run`) and **`aella_cli lab scenario stop`** (stderr summary + JSONL `scenario_live_run_completed`). See `docs/caldera-integration.md` — **«First Live Recon Run Checklist»** and **«First Live Recon Run Execution»**.

On failures, triage in order: **`scenario run <id> --dry-run`** (preflight stdout / stderr) → `tail -n 80 logs/caldera-orchestration.jsonl` (`scenario_preflight_failed` / `scenario_live_run_failed` / `scenario_preflight_warning`) → `bootstrap validate` → `atomic validate` → `agent deploy` / `agent status` → `mirror verify` / `nat verify` → `pack validate` → `scenario status --human` (`docs/caldera-integration.md` §9.0).

### 10.2 Operator quick start (CALDERA)

```bash
cd /home/aella/xdr-lab-appliance
source config/paths.sh
export XDR_CALDERA_API_KEY='<your-caldera-red-key>'

# 1) Edit base_url + scenarios.<name>.adversary_id
#    Annotated template: config/caldera-lab.json.example
#    Live config:        config/caldera-lab.json
vim config/caldera-lab.json

# 2) Statically validate scenario pack files (required fields, lab-vms names, JSON/YAML)
aella_cli lab scenario pack validate

# 3) Validate config + probe CALDERA server (read-only)
aella_cli lab scenario list

# 4) Deploy Sandcat (bootstrap scripts + Linux SSH from appliance; Windows may stay manual — see docs)
aella_cli lab scenario agent deploy
#    Optional: aella_cli lab scenario agent deploy --dry-run   # probes VM/NAT/SSH; skips remote exec; exit 0 if bootstrap files written
ls runtime/caldera-agent/
#   bootstrap-windows.ps1    (guest Admin PowerShell if not using SSH auto path)
#   bootstrap-linux.sh         (normally run remotely by deploy; file kept under runtime/)

aella_cli lab scenario agent status     # confirm CALDERA sees the agents

# 5) Dry-run preflight (same checks as live; no CALDERA PUT / no libvirt snapshot)
aella_cli lab scenario run recon --snapshot-before --dry-run

# 6) Live run — stdout shows operation JSON; scenario.json records last_live_run + JSONL scenario_live_run_*
aella_cli lab scenario run recon --snapshot-before

# 7) Post-run human status (post-run review, last_live_run, mirror/EDR hints)
aella_cli lab scenario status --human

# 8) Stop CALDERA operation (stdout JSON + stderr summary; last_live_run.completed_at when run_id matches)
aella_cli lab scenario stop

# 9) Tear down test agents
aella_cli lab scenario agent remove
```

Every step has a `--dry-run` form that disables CALDERA mutations
(useful when wiring up a new environment); see
`docs/caldera-integration.md` §8.

### 10.3 Runtime artifacts (where to look when something breaks)

| Path                                       | Purpose                                       |
| ------------------------------------------ | --------------------------------------------- |
| `runtime/state/scenario.json`              | Scenario state, `last_history`, `last_live_run` (live submit snapshot), `telemetry_review_*`, `last_operation_summary`, `recommended_revert`, `cleanup_recommended` |
| `runtime/state/caldera.json`               | Server reachability + active operation id     |
| `runtime/state/nat.json`                   | Golden-Image NAT verify snapshot (`nat status`) |
| `logs/caldera-orchestration.jsonl`         | Structured event log (`tail -f | jq`)         |
| `runtime/caldera-agent/bootstrap-*.{ps1,sh}` | Generated Sandcat one-liners                 |

The full troubleshooting matrix (status values, log events, agent
matrix mismatches, OVS mirror verification while a scenario runs) is
in `docs/caldera-integration.md` §§9–11.

### 10.4 Limitations (current)

- CALDERA server lifecycle is **not** managed by this appliance by default —
  `config/caldera-lab.json::deployment` is informational; optional host install:
  `bootstrap/caldera-server-bootstrap.sh` (see `docs/caldera-integration.md`).
- After `scenario list` / `agent status` / `agent deploy`, `runtime/state/caldera.json`
  may echo `plugins` and `atomic_red_team` from `caldera-lab.json` for operator audit
  (the orchestrator does not apply them to the CALDERA server).
- `scenarios.<name>.adversary_id` MUST be populated before
  `scenario run` works (dry-run uses a placeholder).
- Sandcat agents must be deployed inside victim VMs; CALDERA will
  accept operations even with zero agents, but no ability will
  actually execute, so sensor/NDR will see no traffic.
- Post-snapshot is not automated — `--snapshot-before` only handles
  the pre-run baseline. See spec 008 §11.

### 10.5 References

- Operator guide: `docs/caldera-integration.md` (this is the primary
  source of truth for CALDERA operations).
- Reserved scenario-framework spec: `docs/specs/008-scenario-framework/spec.md`.
- Skill (memory): `docs/skills/attack-scenario-skill.md`.

---

## 11. Repository layout

```
xdr-lab-appliance/
├── README.md
├── LICENSE
├── .gitignore
├── docs/
│   ├── memory/constitution.md          # top-level binding rules
│   ├── specs/                          # 12 numbered specs (001–012)
│   ├── skills/                         # operational runbooks (cursor agents)
│   ├── deployment-readiness.md         # host sizing, topology, isolation
│   ├── environment-sanity-checklist.md # libvirt / OVS / NAT / CALDERA gates
│   ├── real-environment-bringup.md     # first live lab + CALDERA sequence
│   ├── release-candidate-checklist.md  # RC sign-off matrix
│   ├── runtime-smoke-validation.md     # CI / local smoke commands
│   ├── operational-recovery.md       # failed runs, stale agents, snapshots
│   ├── operational-maintenance.md    # cleanup vs stop, log retention
│   ├── packaging-guidance.md         # future OVA / offline bundle layout
│   └── caldera-integration.md          # MITRE CALDERA operator guide
├── appliance/
│   ├── appliance_cli.py                # canonical CLI (installed via pip)
│   ├── setup.py
│   └── src/stellar_appliance_cli/      # legacy snapshot (not installed)
├── installer/
│   └── cli-installer.sh                # installs appliance + lab assets
├── scripts/
│   ├── xdr-lab-vm-manager.sh           # KVM/libvirt/qemu engine
│   ├── caldera_orchestration.py        # MITRE CALDERA scenario engine
│   ├── snapshot_state.py               # snapshot batch helper
│   ├── ovs_mirror_state.py             # OVS mirror state machine
│   ├── nat_state.py                    # reverse-NAT validator (read-only)
│   └── create-cloud-vm.sh              # one-shot manual cloud-vm helper
├── config/
│   ├── paths.sh                        # centralized path/env definitions
│   ├── lab.env.example                 # template for runtime overrides
│   ├── lab-vms.json                    # VM topology / NAT / network
│   ├── caldera-lab.json                # CALDERA orchestration config
│   ├── caldera-lab.json.example        # annotated CALDERA config template
│   └── ovs-net.xml                     # libvirt definition for ovs-net
├── cloud-init/
│   ├── sensor-vm/{user-data,meta-data} # key-only template examples
│   ├── test-vm1/{user-data,meta-data}
│   ├── test-vm2/{user-data,meta-data}
│   └── test-vm1-extras/                # alternate key-only test-vm1 template
├── scenarios/                          # scenario packs (recon/web/c2/lateral/exfil; see spec 008)
├── images/                             # qcow2 / cloud base cache (gitignored)
├── templates/                          # (empty — virt-install XML stubs)
├── tests/                              # shell tests for CLI, CALDERA, NAT/OVS validation
├── logs/                               # runtime structured logs (gitignored)
└── backups/
    └── pre-migration-20260512/         # snapshot taken before migration
```

---

## 12. Quick start

```bash
cd /home/aella/xdr-lab-appliance
source config/paths.sh

# Install Python CLI + /opt/xdr-lab assets (requires sudo).
sudo bash installer/cli-installer.sh

# Host runtime validation console (non-installer; RC / post-reboot)
sudo /opt/xdr-lab/xdr-lab.sh
# or: /opt/xdr-lab/bootstrap/validate-host-network.sh

# Define the OVS libvirt network (one-shot).
sudo virsh net-define config/ovs-net.xml
sudo virsh net-start ovs-net
sudo virsh net-autostart ovs-net

# Deploy the lab.
aella_cli lab deploy all --dry-run     # preview
aella_cli lab deploy all               # for real
aella_cli lab status all
```

To run scripts directly from the repo (bypassing `/opt/xdr-lab`):

```bash
export XDR_BASE="$PROJECT_ROOT"          # repo-local install target
bash scripts/xdr-lab-vm-manager.sh status all
```

---

## 13. Path-normalization policy

All shell scripts source `config/paths.sh` (when present); all Python
code reads `XDR_BASE` / `XDR_LAB_MANAGER` / `XDR_LAB_CONFIG` from the
environment. There are **no hard-coded `/home/aella/...` paths** in
the runtime — `XDR_LAB_PROJECT_ROOT` defaults to
`/home/aella/xdr-lab-appliance` but every consumer accepts an
override.

---

## 14. Status

- Migration date: 2026-05-12.
- Migration is **non-destructive**: original assets remain at their
  legacy locations until the operator removes them.
- The lab environment (existing libvirt domains, OVS bridge) is
  untouched by this migration. Re-deploying from this repository is
  fully idempotent against an already-running lab.
