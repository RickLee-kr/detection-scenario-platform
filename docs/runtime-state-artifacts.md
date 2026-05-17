# Runtime State Artifacts — Operator Reference

Index of **durable operator-facing state** on the XDR Lab appliance: JSON
files under `runtime/state/`, structured logs, and **host runtime validation
logs** added for RC operational resilience.

Paths honor `XDR_RUNTIME_STATE_DIR` when set; default
`${XDR_ROOT}/runtime/state/`. Full field guide:
`docs/runtime-state-inspection.md`. CALDERA orchestration context:
`docs/caldera-integration.md` §9.0a.

---

## 1. JSON state files (`runtime/state/`)

| File | Writer | Purpose |
| --- | --- | --- |
| `scenario.json` | `caldera_orchestration.py` | Scenario status, agents matrix, `last_live_run`, errors |
| `caldera.json` | `caldera_orchestration.py` | CALDERA reachability, active operation, bootstrap validate snapshots |
| `nat.json` | `nat_state.py` | Reverse NAT + MASQUERADE contract vs live iptables (read-only probe) |
| `mirror.json` | `ovs_mirror_state.py` | OVS mirror intent vs reality |
| `snapshots.json` | `snapshot_state.py` | Libvirt snapshot catalog (`internal` vs `external_disk` per VM; see `runtime-state-inspection.md` §6) |
| `images.json` | image download manager | Cached image manifest state |

**Host network validation** does not write JSON state files today; use
`validate-host-network.sh --json` for machine-readable host plane snapshots.

---

## 2. Structured logs (`logs/`)

| File | Source | Use when |
| --- | --- | --- |
| `caldera-orchestration.jsonl` | `caldera_orchestration.py` | Scenario run / agent deploy timeline |
| `vm-manager.log` | `xdr-lab-vm-manager.sh` | Deploy, mirror, nat dispatch |
| `host-runtime-validation.log` | `bootstrap/_runtime-validation-lib.sh` | Host validate / self-heal actions |

Tail examples:

```bash
tail -f logs/caldera-orchestration.jsonl | jq -c '{ts,event,scenario}'
tail -20 logs/host-runtime-validation.log
```

---

## 3. Correlating host failure with lab symptoms

| Guest symptom | Check host artifact / command |
| --- | --- |
| No route to `10.10.10.1` | `validate-host-network.sh`; `ip -br link show br0` |
| `nat verify` fails | `nat.json` + `validate-host-network.sh` (MASQUERADE / reverse NAT) |
| CALDERA unreachable from VM | `validate-caldera.sh` + `caldera.json::http_reachable` |
| Sandcat deploy fails | `caldera.json::agent_deploy_last` + host gateway checks |

---

## 4. Safe refresh vs destructive reset

| Action | Mutates guests? | Mutates host iptables? |
| --- | --- | --- |
| `aella_cli lab scenario status` | No | No |
| `aella_cli lab nat verify` | No | No |
| `bootstrap/validate-*.sh` | No | No |
| `bootstrap/fix-runtime-state.sh` | No | No (link/IP/libvirt only) |
| `aella_cli lab destroy` | Yes | No |

---

## 5. Related

- `docs/operational-validation.md` — reboot procedure, br0 DOWN analysis
- `docs/troubleshooting.md` — triage matrix
- `docs/runtime-state-inspection.md` — per-field JSON interpretation
