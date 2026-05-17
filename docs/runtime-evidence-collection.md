# Runtime Evidence Collection — Operator Guide

How to assemble an **audit-friendly evidence bundle** after CALDERA scenario
runs, mirror validation, and snapshot workflows. This is **operator-run**
documentation only; it does not add automated telemetry verdicts or change
schemas.

**English-only** operational text. Preserve secrets: redact API keys in any
artifact you attach to tickets.

---

## 1. Purpose

Evidence bundles support:

- First live adversary run sign-off
- Repeatable operator validation across runs
- Post-incident review with engineering or vendor support

Minimum principle: **copy before truncate** (`docs/operational-maintenance.md`).

---

## 2. JSONL collection

**Primary file:** `${XDR_BASE}/logs/caldera-orchestration.jsonl`

### 2.1 Copy-out for a time window

```bash
ts="$(date -u +%Y%m%dT%H%MZ)"
evdir=~/xdr-lab-evidence/"$ts"
mkdir -p "$evdir"
cp -a logs/caldera-orchestration.jsonl "$evdir/"
# Optional: slice last N lines only
tail -n 500 logs/caldera-orchestration.jsonl > "$evdir/caldera-orchestration.tail500.jsonl"
```

### 2.2 Filtered extracts (jq)

```bash
# Live-run related lines only
jq -c 'select(.event | test("scenario_live_run|snapshot_before|preflight"))' \
  logs/caldera-orchestration.jsonl > "$evdir/live-run-slice.jsonl"

# Failures and errors
jq -c 'select(.event | test("failed|error"))' \
  logs/caldera-orchestration.jsonl | tail -n 100 > "$evdir/errors.tail100.jsonl"
```

### 2.3 vm-manager structured log

```bash
if [ -f logs/vm-manager.log ]; then
  cp -a logs/vm-manager.log "$evdir/"
fi
```

---

## 3. `runtime/state` artifact review

Copy the full state directory (small JSON files):

```bash
cp -a runtime/state "$evdir/runtime-state"
```

Review priority:

1. `scenario.json` — `last_live_run`, `last_history`, `last_error`, `agents`
2. `caldera.json` — `active_caldera_operation_id`, `agent_deploy_last`,
   `http_reachable`
3. `mirror.json` — `consistent`, `output_port_name`, `sensor_interface`
4. `nat.json` — `consistent`, `dnat`, `missing`
5. `snapshots.json` — batch names aligned with `snapshot_before_name`

Field semantics: `docs/runtime-state-inspection.md`.

---

## 4. CALDERA operation screenshots

Capture (as your org requires):

- **Agents** page — paws, platforms, `last_seen` timestamps visible
- **Operations** — operation header showing id/name matching stdout / JSONL
- **Timeline** — representative ability rows in `running` and `finished`
  states
- **Adversaries** — profile used (UUID may be cropped in screenshots; keep
  full UUID in a separate text file if policy allows)

File naming suggestion: `caldera-agents-<UTC>.png`, `caldera-op-<operation_id>.png`.

---

## 5. Sandcat status capture

**On appliance:**

```bash
aella_cli lab scenario agent status > "$evdir/agent-status.txt"
aella_cli lab scenario agent status --json > "$evdir/agent-status.json"
```

**On Linux guest (`linux-server`):**

```bash
pgrep -a sandcat || true
ss -ntp | head -n 40
```

**On Windows (`windows-victim`):**

```powershell
Get-Process | Where-Object { $_.Name -match 'sandcat' }
```

Include CALDERA REST export if automated:

```bash
curl -s -H "KEY: $XDR_CALDERA_API_KEY" \
  "$(jq -r .base_url config/caldera-lab.json)/api/v2/agents" \
  | jq . > "$evdir/caldera-agents-rest.json"
```

**Redact** sensitive fields before external share.

---

## 6. Mirror verification evidence

```bash
aella_cli lab mirror verify 2>&1 | tee "$evdir/mirror-verify.txt"
bash "${XDR_LAB_MANAGER:-$XDR_BASE/scripts/xdr-lab-vm-manager.sh}" mirror status
cp -a runtime/state/mirror.json "$evdir/mirror.json"
```

Optional read-only OVS context (operator judgment; no destructive commands):

```bash
ovs-vsctl list Mirror > "$evdir/ovs-mirror-list.txt" 2>&1 || true
```

---

## 7. tcpdump capture examples

**Sensor VM (mirrored traffic)** — correlate with CALDERA operation window:

```bash
# From appliance via reverse NAT SSH (golden port 1022 → sensor:22)
ssh -p 1022 sensor@<EXT_IP> 'sudo tcpdump -i any -nn -s0 -c 500 -w /tmp/lab-run.pcap "net 10.10.10.0/24"'
```

Copy pcap out with `scp` after the run.

**Host-side short sample (lab bridge only — requires sudo):**

```bash
sudo tcpdump -i br0 -nn -c 200 -w "$evdir/br0-sample.pcap" 2>&1 | tee "$evdir/tcpdump-host.txt"
```

Document **start/stop UTC** next to each capture file.

---

## 8. VM reachability evidence

```bash
aella_cli lab access > "$evdir/lab-access.txt"
aella_cli lab status all > "$evdir/lab-status-all.txt"
aella_cli lab validate all 2>&1 | tee "$evdir/lab-validate-all.txt"
```

Optional ping matrix from host:

```bash
for ip in 10.10.10.10 10.10.10.20 10.10.10.30; do
  ping -c2 -W2 "$ip" | tee -a "$evdir/ping-matrix.txt" || true
done
```

---

## 9. Snapshot evidence

```bash
aella_cli lab snapshot list > "$evdir/snapshot-list.txt"
cp -a runtime/state/snapshots.json "$evdir/snapshots.json"
jq '.last_live_run.snapshot_before_name' runtime/state/scenario.json \
  > "$evdir/snapshot-before-name.txt" 2>/dev/null || true
```

If revert was executed, record command line and post-revert `validate` output.

---

## 10. Operator reporting workflow

1. **Create evidence directory** with UTC folder name (§2.1).
2. **Freeze JSONL** — copy full file or bounded tail; note first/last line
   timestamps.
3. **Freeze runtime state** — `runtime/state` copy (§3).
4. **CALDERA** — screenshots + optional REST JSON (§4, §5).
5. **Network** — mirror + NAT JSON + verify transcripts (§6).
6. **Optional pcaps** — sensor + timestamps (§7).
7. **Summary memo** — one English paragraph: scenario id, operation id,
   outcome, anomalies, revert yes/no.

Ticket template fields:

- Git SHA / package version
- `XDR_BASE` path
- `base_url` (host:port only if sensitive)
- `scenario_id`, `caldera_operation_id` (from stdout or `caldera.json`)
- Attachment list with SHA256 of large files (`sha256sum` per file)

---

## 11. Related documents

- `docs/live-run-playbook.md` — ordered first live run
- `docs/runtime-state-inspection.md` — JSON interpretation
- `docs/operator-troubleshooting-matrix.md` — failure codes
- `docs/operational-maintenance.md` — retention and rotation
