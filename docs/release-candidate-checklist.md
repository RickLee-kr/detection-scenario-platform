# Release Candidate (RC) Validation Checklist — XDR Lab Appliance

Use this checklist before declaring a **release candidate** build or
golden image **RC-ready**. It aggregates governance specs (006, 007,
010, 011, 012) and operator runbooks into a single sign-off matrix.
**English-only** operational text; no schema or IP/port contract changes
are implied by this document.

**Topology vocabulary:** **Open vSwitch bridge `br0`**, **OVS-backed
libvirt network `ovs-net`**, **openvswitch virtualport** — not a Linux
kernel–only bridge lab.

---

## 1. Topology verification

| # | Check | Command / action | Pass |
| --- | --- | --- | --- |
| 1.1 | `lab-vms.json` bridge field | `jq -r .network.bridge config/lab-vms.json` | `br0` |
| 1.2 | Per-VM bridge | `jq -r '.vms[] | .bridge' config/lab-vms.json` (unique) | all `br0` |
| 1.3 | Subnet / gateway | `jq .network.lab_subnet_cidr,.network.gateway config/lab-vms.json` | `10.10.10.0/24`, `10.10.10.1` |
| 1.4 | `ovs-net` active | `virsh net-info ovs-net` | `Active: yes` |
| 1.5 | `ovs-net` XML | `virsh net-dumpxml ovs-net` | `bridge name='br0'`, `virtualport type='openvswitch'` |

---

## 2. OVS validation

| # | Check | Command / action | Pass |
| --- | --- | --- | --- |
| 2.0 | Host runtime (RC) | `${XDR_ROOT}/bootstrap/validate-host-network.sh` | Exit 0 — `br0` UP + `10.10.10.1/24` |
| 2.0b | Post-reboot heal (if needed) | `sudo ${XDR_ROOT}/bootstrap/fix-runtime-state.sh` | Restores link/IP/`ovs-net` only |
| 2.1 | OVS daemon | `systemctl is-active openvswitch-switch` | `active` |
| 2.2 | Bridge present | `ovs-vsctl br-exists br0 && echo ok` | `ok` |
| 2.3 | Ports | `ovs-vsctl list-ports br0` | Lab vnet/tap ports when VMs up |
| 2.4 | No destructive scripts | N/A — confirm no `emer-reset` / `del-br br0` in custom forks | Policy clean |

---

## 3. Reverse NAT validation

| # | Check | Command / action | Pass |
| --- | --- | --- | --- |
| 3.1 | Engine verify | `aella_cli lab nat verify` | Exit 0 |
| 3.2 | Snapshot | `aella_cli lab nat status` | JSON consistent with golden matrix |
| 3.3 | Access map | `aella_cli lab access` | Matches `README.md` §5.1 |

---

## 4. VM deployment validation

| # | Check | Command / action | Pass |
| --- | --- | --- | --- |
| 4.1 | Deploy idempotency | `aella_cli lab deploy all` (repeat) | No duplicate domains; success logs |
| 4.2 | Status | `aella_cli lab status all` | Expected inventory |
| 4.3 | Validate | `aella_cli lab validate all` | Exit 0 when guests healthy |

---

## 5. CALDERA validation

| # | Check | Command / action | Pass |
| --- | --- | --- | --- |
| 5.1 | Config | `jq .base_url config/caldera-lab.json` | Intended server |
| 5.2 | List / HTTP | `aella_cli lab scenario list` | HTTP success; merged scenarios |
| 5.3 | Bootstrap | `aella_cli lab scenario bootstrap validate` | Pass per `docs/caldera-integration.md` |
| 5.4 | Adversary | Merged `adversary_id` non-empty for scenarios you will run live | Not blocked |

---

## 6. Sandcat validation

| # | Check | Command / action | Pass |
| --- | --- | --- | --- |
| 6.1 | Deploy | `aella_cli lab scenario agent deploy` | Artifacts under `runtime/caldera-agent/` |
| 6.2 | Status | `aella_cli lab scenario agent status` | Expected paws / hosts |
| 6.3 | UI cross-check | CALDERA UI → Agents | Live agents when exercise requires |

---

## 7. Snapshot validation

| # | Check | Command / action | Pass |
| --- | --- | --- | --- |
| 7.1 | Create | `aella_cli lab snapshot create rc-gate --dry-run` then live | Success |
| 7.2 | List | `aella_cli lab snapshot list` | `rc-gate` visible |
| 7.3 | Revert dry-run | `aella_cli lab snapshot revert rc-gate --dry-run` | Intention printed |

---

## 8. JSONL runtime validation

| # | Check | Command / action | Pass |
| --- | --- | --- | --- |
| 8.1 | Log exists | `test -f logs/caldera-orchestration.jsonl` (or `${XDR_BASE}/logs/…`) | File appendable |
| 8.2 | Lines parse | `tail -n 5 logs/caldera-orchestration.jsonl \| jq -e . >/dev/null` | Each line valid JSON |
| 8.3 | Dry-run event | Run any `scenario … --dry-run`; tail log | Structured event present |

---

## 9. Cleanup validation

| # | Check | Command / action | Pass |
| --- | --- | --- | --- |
| 9.1 | Scenario stop | `aella_cli lab scenario stop` | Completes or documents blocked state |
| 9.2 | Agent remove (optional) | `aella_cli lab scenario agent remove` | Exits per policy |
| 9.3 | Lab cleanup (destructive lab only) | `aella_cli lab cleanup` | Only when intentional; inventory-scoped |

---

## 10. Operational recovery validation

| # | Check | Command / action | Pass |
| --- | --- | --- | --- |
| 10.1 | Recovery doc walk | Spot-check `docs/operational-recovery.md` ordering matrix | Operators can execute |
| 10.2 | Mirror recovery | `mirror verify` after intentional `mirror apply` | Idempotent recovery path |

---

## 11. Sign-off

Record: **build id / git SHA**, **operator**, **date**, **`XDR_BASE`**,
**CALDERA base_url**, **RC blocker list** (if any).

---

## 12. Related documents

- `docs/live-run-playbook.md`
- `docs/real-environment-bringup.md`
- `docs/runtime-smoke-validation.md`
- `docs/environment-sanity-checklist.md`
- `docs/deployment-readiness.md`
- `docs/packaging-guidance.md`
- `docs/operator-troubleshooting-matrix.md`
- `docs/runtime-evidence-collection.md`

---

## 13. Repeatability and regression hardening

Run after a **first successful live adversary run** and again before RC
freeze when code or CALDERA versions change.

### 13.1 Repeatability validation

| # | Check | Command / action | Pass criteria |
| --- | --- | --- | --- |
| 13.1.1 | Second dry-run baseline | `aella_cli lab scenario run recon --snapshot-before --dry-run` | Preflight summary matches documented expectations |
| 13.1.2 | Second live run (optional) | Same as first live with fresh evidence bundle | New JSONL `scenario_live_run_submitted` line; new operation id |
| 13.1.3 | State overwrite sanity | `jq '.last_live_run.caldera_operation.operation_id' runtime/state/scenario.json` | Matches last stdout JSON (field path may vary — compare to stdout) |

### 13.2 Multiple-run consistency checks

| # | Check | Pass criteria |
| --- | --- | --- |
| 13.2.1 | Mirror + NAT | `mirror verify` and `nat verify` exit 0 on consecutive days |
| 13.2.2 | Snapshots | `snapshot list` shows expected batch names; no orphan pre-scenario names without matching revert policy |
| 13.2.3 | JSONL | No unexplained gaps in `scenario_preflight_completed` → `scenario_live_run_submitted` chain for successful runs |

### 13.3 Cleanup verification

| # | Check | Pass criteria |
| --- | --- | --- |
| 13.3.1 | Post-run stop | `aella_cli lab scenario stop` completes; UI operation finished |
| 13.3.2 | Agent policy | `agent remove` executed when next run requires clean CALDERA matrix |
| 13.3.3 | Logs | Evidence copied per `docs/runtime-evidence-collection.md` before rotation |

### 13.4 Snapshot rollback consistency

| # | Check | Pass criteria |
| --- | --- | --- |
| 13.4.1 | Revert rehearsal | `snapshot revert <pre-scenario-name> --dry-run` | Intention matches §7 snapshot docs |
| 13.4.2 | Live revert (maintenance window) | `snapshot revert <name>` then `validate all` | Guests healthy for next campaign |

### 13.5 Repeated mirror validation

| # | Check | Pass criteria |
| --- | --- | --- |
| 13.5.1 | Daily gate | `aella_cli lab mirror verify` | Exit 0 |
| 13.5.2 | Evidence | `mirror.json` archived with timestamp | Operator audit trail |

### 13.6 Stale runtime artifact detection

| # | Check | Pass criteria |
| --- | --- | --- |
| 13.6.1 | Orphan operation | `caldera.json` vs CALDERA UI | No unexplained active ids after `scenario stop` |
| 13.6.2 | Stale `mirror.json` | `last_verified_time` vs last exercise | Refreshed via `mirror status` / `mirror verify` |
| 13.6.3 | Old `last_error` | `scenario.json` | Cleared or superseded after successful rerun (`status` not `failed`) |

### 13.7 See also

- `docs/live-run-playbook.md`
- `docs/environment-sanity-checklist.md` §13
- `docs/operator-troubleshooting-matrix.md`
