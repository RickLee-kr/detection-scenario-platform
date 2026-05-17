# Environment Sanity Checklist — XDR Lab Appliance

Run this checklist **after** install (`installer/cli-installer.sh`) and
**before** first production-style scenarios. Commands assume a configured
install with `config/paths.sh` sourced and `XDR_BASE` pointing at the
active tree (repository or `/opt/xdr-lab`). Adjust paths if you use a
non-default `XDR_LAB_MANAGER`.

**CLI vs engine**: `aella_cli` does not expose every `xdr-lab-vm-manager.sh`
mirror subcommand; where noted, invoke the manager script directly.

---

## 1. libvirt verification

| Step | Command / action | Pass criteria |
| --- | --- | --- |
| Daemon | `systemctl is-active libvirtd` | `active` |
| KVM | `virt-host-validate` (optional) | No blocking failures for QEMU/KVM |
| Network | `virsh net-info ovs-net` | `Active: yes` (after `net-define` / `net-start` per `README.md` §12) |
| Domains | `aella_cli lab status all` | Expected domains listed; running state matches intent |

---

## 2. OVS verification

| Step | Command / action | Pass criteria |
| --- | --- | --- |
| Host runtime | `${XDR_ROOT}/bootstrap/validate-host-network.sh` | Exit 0 (`br0` UP, gateway IP, NAT contract) |
| Service | `systemctl is-active openvswitch-switch` | `active` |
| Bridge | `ovs-vsctl show` | `br0` exists and carries lab ports |
| libvirt attachment | `virsh net-dumpxml ovs-net` | Bridge name `br0`, `virtualport type='openvswitch'` |

---

## 3. Bridge verification

| Step | Command / action | Pass criteria |
| --- | --- | --- |
| Host IP | `ip -4 addr show dev br0` | `10.10.10.1/24` present |
| Reachability | From host: `ping -c2 10.10.10.10` (when sensor-vm is up) | Replies if guest firewall allows ICMP |

---

## 4. NAT verification (lab egress)

| Step | Command / action | Pass criteria |
| --- | --- | --- |
| Engine | `aella_cli lab nat verify` | Exit 0; snapshot aligned with policy |
| Status JSON | `aella_cli lab nat status` | Useful for diffing drift over time |

Operator expectation: outbound **MASQUERADE/SNAT** is environment-specific
(spec 006); the CLI **verifies** declared reverse-NAT and related
read-only probes, not arbitrary operator `iptables` tables.

---

## 5. Reverse NAT verification (operator → guest)

| Step | Command / action | Pass criteria |
| --- | --- | --- |
| Summary | `aella_cli lab access` | Port map matches `README.md` §5.1 golden matrix |
| SSH paths | From a workstation: `ssh -p 1022 sensor@<EXT>`, `ssh -p 2022 ubuntu@<EXT>` | Login succeeds when guests are up |
| RDP | Client to `<EXT>:3389` | Session to `windows-victim` when VM is running |

---

## 6. VM reachability

| Step | Command / action | Pass criteria |
| --- | --- | --- |
| Batch | `aella_cli lab validate all` | Exit 0 after deploy; per-VM checks per engine |
| Spot | `aella_cli lab status <vm>` + ping/SSH/RDP as above | Consistent with workload |

---

## 7. CALDERA reachability

| Step | Command / action | Pass criteria |
| --- | --- | --- |
| Config | `jq .base_url config/caldera-lab.json` | URL matches running CALDERA |
| API | `aella_cli lab scenario list` | HTTP 200 class response; merged scenario rows |
| Bootstrap | `aella_cli lab scenario bootstrap validate` | Plugins / key / reachability per `docs/caldera-integration.md` |

---

## 8. Sandcat check-in

| Step | Command / action | Pass criteria |
| --- | --- | --- |
| Deploy | `aella_cli lab scenario agent deploy` | Bootstrap artifacts under `${XDR_BASE}/runtime/caldera-agent/` |
| Status | `aella_cli lab scenario agent status` | CALDERA matrix shows expected hosts / paw prints |
| Guest | CALDERA UI → Agents | Live agents for linux-server / windows-victim as planned |

---

## 9. Snapshot capability

| Step | Command / action | Pass criteria |
| --- | --- | --- |
| Create | `aella_cli lab snapshot create pre-checklist --dry-run` then without `--dry-run` | Success logs; VMs return to running as applicable |
| List | `aella_cli lab snapshot list` | New snapshot visible for batch targets |
| Revert dry-run | `aella_cli lab snapshot revert pre-checklist --dry-run` | Engine prints intended actions |

---

## 10. Mirror validation

| Step | Command / action | Pass criteria |
| --- | --- | --- |
| State refresh | `bash "${XDR_LAB_MANAGER:-$XDR_BASE/scripts/xdr-lab-vm-manager.sh}" mirror status` | Prints / refreshes `runtime/state/mirror.json` |
| Consistency | `aella_cli lab mirror verify` | Exit 0; mirror present and consistent |
| Path probe | `aella_cli lab mirror traffic` | ICMP / tcpdump path per engine (maps to `validate-traffic` in the manager) |

---

## 11. Sign-off

Record date, operator, and appliance `XDR_BASE` in your change log. If any
step fails, use `docs/operational-recovery.md` before retrying scenarios.

---

## 12. Full live recon validation sequence

Use after §§1–10 pass and when preparing the **first** (or regression)
**live** CALDERA recon. This section does **not** assert automatic
telemetry validation; operators observe guests, CALDERA UI, and sensor
pipelines manually.

### 12.1 Ordered steps

| Step | Command / action | Pass criteria |
| --- | --- | --- |
| 12.1.1 | `aella_cli lab scenario pack validate` | Schema + VM names OK; warnings understood |
| 12.1.2 | `aella_cli lab scenario bootstrap validate` | CALDERA HTTP + API key + plugin hints per policy |
| 12.1.3 | `aella_cli lab scenario atomic validate` | ART paths / exec readiness on target guests |
| 12.1.4 | `aella_cli lab scenario agent deploy` | Sandcat artifacts present; agents check in when required |
| 12.1.5 | Merged `adversary_id` set for `recon` (or chosen id) | `aella_cli lab scenario list` shows UUID |
| 12.1.6 | `aella_cli lab mirror apply` && `aella_cli lab mirror verify` | Exit 0; mirror on **OVS `br0`** |
| 12.1.7 | `aella_cli lab scenario run recon --snapshot-before --dry-run` | Preflight complete; no unexpected `scenario_preflight_failed` |
| 12.1.8 | `aella_cli lab scenario run recon --snapshot-before` | Live run accepted; CALDERA operation progresses |
| 12.1.9 | `aella_cli lab scenario status --human` | Post-run block readable; `last_live_run` consistent |
| 12.1.10 | `aella_cli lab scenario stop` | Clean finish path or documented manual recovery |

### 12.2 Expected operator observations

| Area | Expected observation |
| --- | --- |
| CALDERA UI | Operation moves from queued → running → finish (or operator-stopped); abilities visible for the adversary profile |
| Guests | Brief recon-style activity (ping/dns/curl patterns per pack) where abilities target those hosts |
| Sensor | Increased mirrored traffic on **`br0`** during the window (pcap/IDS UI operator-specific); **no** auto-pass/fail from XDR Lab |
| Reverse NAT | SSH/RDP paths still match golden matrix if operators use external access during the run |

### 12.3 Expected JSONL events (illustrative)

Exact `event` strings are defined by `scripts/caldera_orchestration.py` and
spec 012; a typical **live** recon run includes several of:

- Preflight / planning records (`scenario_preflight_*`, `scenario_live_run_*` families)
- `scenario_live_run_completed` or failure/stop counterparts on stderr summary paths

**Validate by:** `tail -n 100 logs/caldera-orchestration.jsonl | jq -r .event`
— expect **no** silent success when HTTP or agents are broken (non-zero CLI
exit).

### 12.4 Expected runtime / state updates

| Artifact | Expected update |
| --- | --- |
| `runtime/state/scenario.json` | `last_live_run`, `last_history`, timestamps advance; no hand-edit |
| `runtime/state/caldera.json` | Active operation echo when applicable |
| `runtime/state/mirror.json` | Refreshed when mirror verbs run |
| `runtime/state/nat.json` | Updated on `nat verify` |

### 12.5 Expected CALDERA behavior

- REST calls use configured `base_url` and red API key.
- Live run refuses when merged `adversary_id` empty (blocked, not faked).
- `scenario stop` issues finish/cancel to the extent the server allows.

### 12.6 Expected mirror behavior

- Mirror object remains on **Open vSwitch `br0`** with sensor as
  **`output_port`** (spec 007).
- `mirror verify` after the run still passes unless VMs were stopped and
  policy expects WARN-only paths.

### 12.7 See also

- `docs/real-environment-bringup.md`
- `docs/release-candidate-checklist.md`
- `docs/runtime-smoke-validation.md`

---

## 13. Repeatability and multi-run consistency

Use this section when proving the lab across **multiple** live or dry runs
before RC sign-off. No automated telemetry verdicts; operators compare
artifacts manually.

### 13.1 Repeatability validation (gates)

| # | Check | Command / action | Pass criteria |
| --- | --- | --- | --- |
| 13.1.1 | Deterministic config | `sha256sum config/lab-vms.json config/caldera-lab.json` archived between runs | Same files reused intentionally across runs |
| 13.1.2 | Clean preflight | `aella_cli lab scenario run recon --snapshot-before --dry-run` | Same warning class as baseline (no surprise new `scenario_preflight_failed`) |
| 13.1.3 | Mirror idempotency | `aella_cli lab mirror verify` before and after each run day | Exit 0 both times unless topology changed |
| 13.1.4 | NAT stability | `aella_cli lab nat verify` before/after | Exit 0; `nat.json` `consistent` remains `true` |

### 13.2 Multiple-run consistency checks

| # | Check | Pass criteria |
| --- | --- | --- |
| 13.2.1 | JSONL event presence | Each live run adds at least `scenario_live_run_submitted` (and stop/failure counterparts) | Lines monotonic in time; no duplicate operation ids unless re-run |
| 13.2.2 | `last_live_run` | `scenario.json` reflects the **latest** run’s operation id after each live `run` | Operator confirms overwrite is expected |
| 13.2.3 | Agent matrix | `agent status` stable across runs when Sandcat not removed | Same roles `true` |

### 13.3 Cleanup verification

After each run session:

| # | Action | Pass criteria |
| --- | --- | --- |
| 13.3.1 | `aella_cli lab scenario stop` | Completes per policy; UI not stuck indefinitely |
| 13.3.2 | Optional `agent remove` | CALDERA agents cleared when exercise requires isolation |
| 13.3.3 | Disk hygiene | `df -h` — no unexpected full volumes from JSONL growth |

### 13.4 Snapshot rollback consistency

| # | Action | Pass criteria |
| --- | --- | --- |
| 13.4.1 | Record `snapshot_before_name` | From `scenario.json` / `scenario status --human` |
| 13.4.2 | `snapshot revert <name> --dry-run` then live | Same VM set returns to prior baseline per operator checks |
| 13.4.3 | Post-revert | `aella_cli lab validate all` exit 0 when guests healthy |

### 13.5 Repeated mirror validation

Run `mirror verify` at start/end of each exercise day; archive `mirror.json`
diffs in evidence bundles (`docs/runtime-evidence-collection.md`).

### 13.6 Stale runtime artifact detection

| Symptom | Investigation | Mitigation |
| --- | --- | --- |
| `caldera.json` shows old `active_caldera_operation_id` after UI cleared | `scenario status --human`; JSONL tail | `scenario stop`; UI finish per `docs/operational-recovery.md` §3 |
| `mirror.json` older than last `mirror apply` | Compare `last_verified_time` to wall clock | Run `mirror status` / `mirror verify` |
| `snapshots.json` missing latest batch | `snapshot list` vs file | Re-run `snapshot create` test path |

### 13.7 See also

- `docs/live-run-playbook.md`
- `docs/operator-troubleshooting-matrix.md`
- `docs/runtime-state-inspection.md`
