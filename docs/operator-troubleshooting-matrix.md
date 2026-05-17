# Operator Troubleshooting Matrix — XDR Lab Appliance

Structured triage for **first live adversary run** readiness and recovery.
Commands assume `source config/paths.sh` from the project root (or
`/opt/xdr-lab`). **English-only** operational text.

Cross-reference: `docs/caldera-integration.md` §9.0 (triage order),
`docs/operational-recovery.md` §6 (ordering matrix).

---

## How to use this matrix

1. Identify the **code** (left column) closest to your symptom.
2. Run **validation commands**; compare to **expected outputs**.
3. Apply **recovery steps** in order.
4. Use **escalation** when host networking, ESXi portgroup policy, or CALDERA
   upstream defects are suspected.

---

## `caldera_unreachable`

| Field | Content |
| --- | --- |
| **Symptoms** | `curl` to `base_url` fails; `scenario list` errors; `bootstrap validate` fails HTTP; JSONL `caldera_http_error`; `scenario.json` `status=failed` with `url_error` text |
| **Likely causes** | CALDERA process down; wrong `base_url`; firewall; TLS mismatch; bind address only on `127.0.0.1` while probing from wrong host |
| **Validation commands** | `jq -r .base_url config/caldera-lab.json`; `curl -s -o /dev/null -w '%{http_code}\n' -H "KEY: $XDR_CALDERA_API_KEY" "$(jq -r .base_url config/caldera-lab.json)/api/agents"`; `systemctl status caldera.service` (if applicable) |
| **Expected outputs** | `200` or meaningful `401` from curl — not `000` / connection refused |
| **Recovery steps** | Start CALDERA per `docs/caldera-integration.md` §2.0; fix `base_url`; open firewall path from appliance to CALDERA port; align bind address with agent callback plan |
| **Escalation** | Platform / network team if upstream routing or TLS inspection breaks REST |

---

## `api_key_missing`

| Field | Content |
| --- | --- |
| **Symptoms** | Non-dry `agent deploy` / `scenario run` exit **2**; stderr mentions missing key; `caldera.json::agent_deploy_last.fatal_reason` contains `api_key_missing` |
| **Likely causes** | `XDR_CALDERA_API_KEY` unset; `api_key_file` missing or unreadable; wrong `api_key_env` |
| **Validation commands** | `test -n "${XDR_CALDERA_API_KEY:-}" && echo env_ok || echo env_empty`; `jq -r .api_key_file config/caldera-lab.json`; `sudo test -r /etc/xdr-lab/caldera-api-key && echo file_ok` |
| **Expected outputs** | At least one of env non-empty or readable key file |
| **Recovery steps** | Export key or install file per `docs/caldera-integration.md` §3; align with CALDERA `api_key_red` |
| **Escalation** | Security team for key rotation procedures |

---

## `missing_adversary_id`

| Field | Content |
| --- | --- |
| **Symptoms** | `status=blocked`; `last_error` mentions adversary; JSONL / stderr `missing_adversary_id`; live `scenario run` refused |
| **Likely causes** | Pack `caldera.adversary_id` null and JSON fallback empty; typo in `scenario_id` key |
| **Validation commands** | `aella_cli lab scenario list` (merged `adversary_id` column); `aella_cli lab scenario run <id> --snapshot-before --dry-run` |
| **Expected outputs** | Non-empty merged UUID for your `scenario_id` |
| **Recovery steps** | Set `config/caldera-lab.json::scenarios.<id>.adversary_id` or pack UUID per `docs/caldera-integration.md` §4.4c |
| **Escalation** | CALDERA admin if adversary profiles are missing from server |

---

## `stale_sandcat`

| Field | Content |
| --- | --- |
| **Symptoms** | Agents `dead` in UI; `last_seen` stale; `agent status` matrix false despite processes on guests; duplicate paws |
| **Likely causes** | Old Sandcat sessions; hostname change; `host_substrings` mismatch; guest firewall blocking callback |
| **Validation commands** | `aella_cli lab scenario agent status`; `curl -s -H "KEY: $XDR_CALDERA_API_KEY" "$(jq -r .base_url config/caldera-lab.json)/api/v2/agents" \| jq '.[] \| {paw,host,last_seen}'` |
| **Expected outputs** | Fresh `last_seen` for expected lab hosts |
| **Recovery steps** | `docs/operational-recovery.md` §2 — UI cleanup when safe; guest stop Sandcat; `agent remove` then `agent deploy` |
| **Escalation** | Guest OS hardening team if enterprise EDR kills agent |

---

## `mirror_json_missing`

| Field | Content |
| --- | --- |
| **Symptoms** | `runtime/state/mirror.json` absent or never updated; `mirror verify` errors referencing state |
| **Likely causes** | Mirror engine never run; wrong `XDR_RUNTIME_STATE_DIR`; permission issue under `${XDR_BASE}/runtime/state` |
| **Validation commands** | `test -f runtime/state/mirror.json && echo present || echo absent`; `bash "${XDR_LAB_MANAGER:-$XDR_BASE/scripts/xdr-lab-vm-manager.sh}" mirror status` |
| **Expected outputs** | File exists after `mirror status` / `mirror verify` |
| **Recovery steps** | Run `mirror apply` then `mirror verify`; ensure `XDR_BASE` writable |
| **Escalation** | If `br0` missing — host OVS bring-up (spec 006); appliance does not auto-create `br0` |

---

## `vm_unreachable`

| Field | Content |
| --- | --- |
| **Symptoms** | `lab validate` fails; SSH/RDP timeouts; agent deploy SSH errors |
| **Likely causes** | VM powered off; wrong static IP inside guest; vSwitch promiscuous/MAC policy on ESXi; guest firewall |
| **Validation commands** | `aella_cli lab status <vm>`; `ping -c2 <internal_ip>`; `aella_cli lab access`; `aella_cli lab nat verify` |
| **Expected outputs** | Domain `running`; ping/SSH per golden matrix when policy allows ICMP |
| **Recovery steps** | `lab start <vm>`; fix cloud-init / guest IP; ESXi portgroup policy per `README.md` §3 |
| **Escalation** | Virtualization admin for nested virt / portgroup |

---

## `reverse_nat_failure`

| Field | Content |
| --- | --- |
| **Symptoms** | `nat verify` non-zero; `nat.json` inconsistent; external SSH/RDP fails while internal works |
| **Likely causes** | `XDR_LAB_DNAT` chain drift; wrong external NIC; iptables save/restore overwritten rules |
| **Validation commands** | `aella_cli lab nat verify`; `aella_cli lab nat status`; `aella_cli lab access` |
| **Expected outputs** | `nat verify` exit 0; golden ports per `README.md` §5.1 |
| **Recovery steps** | Re-apply documented NAT manager path (spec 010); never `iptables -F` global tables |
| **Escalation** | Host security team if corporate firewall blocks inbound operator ports |

---

## `snapshot_failure`

| Field | Content |
| --- | --- |
| **Symptoms** | JSONL `snapshot_before_failed`; `scenario run` aborts before CALDERA PUT; libvirt error in stderr |
| **Likely causes** | Insufficient disk; VM not running; qcow2 format limitation; snapshot name collision |
| **Validation commands** | `df -h`; `aella_cli lab snapshot list`; `virsh snapshot-list <vm> --tree` on failing domain |
| **Expected outputs** | Adequate free space; snapshot create dry-run then live succeeds |
| **Recovery steps** | Free disk; quiesce guests; pick new snapshot name; see `docs/operational-recovery.md` §4 |
| **Escalation** | Storage team if shared pool exhausted |

---

## `operation_timeout`

| Field | Content |
| --- | --- |
| **Symptoms** | CALDERA UI stuck `running` for extended time; abilities pending; no progress |
| **Likely causes** | Agents disconnected mid-run; planner backlog; CALDERA server load |
| **Validation commands** | UI timeline; `agent status`; CALDERA server CPU/RAM; JSONL for last `scenario_live_run_submitted` timestamp |
| **Expected outputs** | Agents live; server responsive |
| **Recovery steps** | Confirm agents; use `scenario stop`; if server hung, restart CALDERA service per runbook (operator) |
| **Escalation** | CALDERA upstream support if server bugs suspected |

---

## `orphan_operation`

| Field | Content |
| --- | --- |
| **Symptoms** | UI shows running operation after CLI crash; `caldera.json` id does not match UI; `scenario stop` no-op |
| **Likely causes** | CLI interrupted; state file out of sync with server |
| **Validation commands** | `jq '.active_caldera_operation_id,.last_error' runtime/state/caldera.json`; compare to CALDERA UI |
| **Expected outputs** | Ids align or empty when nothing active |
| **Recovery steps** | `docs/operational-recovery.md` §3 — `scenario stop`; finish in UI/API; document manual action |
| **Escalation** | None unless repeated platform crashes |

---

## `cleanup_incomplete`

| Field | Content |
| --- | --- |
| **Symptoms** | Guest artifacts remain; agents still in CALDERA; `cleanup_recommended` true in human status |
| **Likely causes** | Skipped `agent remove`; abilities created persistent files; no snapshot revert |
| **Validation commands** | `aella_cli lab scenario status --human`; guest file/process checks per pack `cleanup_notes` |
| **Expected outputs** | Operators satisfied with guest hygiene |
| **Recovery steps** | Run pack cleanup guidance; `agent remove`; snapshot revert if needed |
| **Escalation** | IR playbook if unintended lateral exposure |

---

## Quick index by CLI / log token

| Token / location | Matrix row |
| --- | --- |
| `url_error`, `caldera_http_error` | `caldera_unreachable` |
| `api_key_missing`, HTTP 401 mismatches | `api_key_missing` |
| `missing_adversary_id` | `missing_adversary_id` |
| `fatal_preflight: true` | Often `caldera_unreachable` or `api_key_missing` |
| `snapshot_before_failed` | `snapshot_failure` |
| `mirror_exists: false`, verify non-zero | `mirror_json_missing` / mirror misconfig (see spec 007) |

---

## Related documents

- `docs/live-run-playbook.md`
- `docs/runtime-evidence-collection.md`
- `docs/runtime-state-inspection.md`
- `docs/caldera-integration.md`
