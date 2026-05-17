# Real Environment Bring-Up — XDR Lab Appliance

Operator runbook for **first live lab** on hardware or nested ESXi: from
host prep through **first CALDERA recon** and **post-run cleanup**. This
document does **not** change IP/port contracts, schemas, or CLI behavior.

**Canonical dataplane:** Ubuntu 24.04 → libvirt/KVM → **Open vSwitch
bridge `br0`** → libvirt **`ovs-net`** with **`<virtualport type='openvswitch'/>`**
→ guests and OVS port mirror (spec 006 / 007). Do not describe the lab as
a Linux kernel–only bridge environment.

---

## 0. Preconditions

- Ubuntu 24.04 appliance with packages per `README.md` §3.
- **`br0`** exists as an **OVS bridge**; host addressing for `10.10.10.1/24`
  on `br0` matches `lab-vms.json`.
- `virsh net-define config/ovs-net.xml` → `net-start` / `net-autostart`
  **`ovs-net`** (see `README.md` §12).
- `XDR_BASE`, `config/paths.sh`, and `aella_cli` installed per installer.

---

## 1. CALDERA bootstrap (server)

Follow **`docs/caldera-integration.md` §2.0** (supported platform, clone,
venv, plugins, systemd). Prefer:

```bash
cd /path/to/xdr-lab-appliance
./bootstrap/caldera-server-bootstrap.sh --dry-run
sudo CALDERA_PLUGINS=sandcat,stockpile,atomic \
  CALDERA_LISTEN_HOST=127.0.0.1 CALDERA_PORT=8888 \
  ./bootstrap/caldera-server-bootstrap.sh
```

Validate HTTP + key from the orchestration host per §2.0 **Health
verification**.

---

## 2. API key configuration

1. Align CALDERA `api_key_red` with XDR Lab: **`XDR_CALDERA_API_KEY`**
   and/or `api_key_file` in `config/caldera-lab.json` (see
   `docs/caldera-integration.md` §3).
2. **Never commit** live keys; use `config/lab.env` or a root-only file
   (e.g. `/etc/xdr-lab/caldera-api-key`) as documented.
3. `export XDR_CALDERA_API_KEY='…'` in the shell that runs `aella_cli` when
   not using `api_key_file`.

---

## 3. Adversary UUID creation

1. In CALDERA UI, open **Campaigns / adversaries** (or equivalent) and
   copy the **adversary UUID** for your exercise (recon-oriented profile).
2. Set `config/caldera-lab.json::scenarios.<id>.adversary_id` to that UUID
   (repo packs may keep `null`; merged config wins — see
   `docs/caldera-integration.md` §4.4).
3. `aella_cli lab scenario list` — confirm merged rows show the UUID.

Non-dry `scenario run` remains **blocked** until `adversary_id` resolves
(non-empty merged value).

---

## 4. Sandcat deployment

1. `aella_cli lab scenario pack validate`
2. `aella_cli lab scenario bootstrap validate`
3. `aella_cli lab scenario atomic validate`
4. `aella_cli lab scenario agent deploy` (optional `--dry-run` first)
5. `aella_cli lab scenario agent status` — CALDERA matrix matches expected
   lab hosts.

Artifacts: `${XDR_BASE}/runtime/caldera-agent/bootstrap-*.sh` /
`bootstrap-*.ps1`. Windows may require manual Admin PowerShell per
`docs/caldera-integration.md`.

---

## 5. VM reachability

1. `aella_cli lab deploy all` (or per-VM) — idempotent.
2. `aella_cli lab start all` as needed.
3. `aella_cli lab status all` — domains running.
4. `aella_cli lab access` + reverse-NAT checks (`README.md` §5.1 golden
   ports): SSH/RDP to **external** IP:port.

---

## 6. Mirror validation

1. `aella_cli lab mirror apply`
2. `aella_cli lab mirror verify` — exit 0; consistent **`output_port`**
   for sensor on **`br0`**.
3. Optional: `aella_cli lab mirror traffic` — live probe path (requires
   healthy sensor SSH and mirror).
4. Direct engine: `bash "${XDR_LAB_MANAGER:-$XDR_BASE/scripts/xdr-lab-vm-manager.sh}" mirror status`

---

## 7. Snapshot verification

1. `aella_cli lab snapshot create pre-live-recon --dry-run` then without
   `--dry-run`.
2. `aella_cli lab snapshot list` — snapshot present on batch targets.
3. First live run: use `--snapshot-before` on `scenario run` per
   `docs/caldera-integration.md`.

---

## 8. First recon execution

1. `aella_cli lab scenario run recon --snapshot-before --dry-run` — read
   preflight + checklist; **no fake success** if adversary or agents are
   missing.
2. Same command **without** `--dry-run` when preflight is clean.
3. `aella_cli lab scenario status --human` — post-run review,
   `last_live_run`, hints.
4. `tail -f logs/caldera-orchestration.jsonl` — JSONL events (spec 012).

**Telemetry:** the platform does **not** auto-validate SIEM/EDR telemetry;
operators review sensor and CALDERA outcomes manually.

---

## 9. Post-run cleanup

1. `aella_cli lab scenario stop` — finish CALDERA operation when applicable.
2. Optional: `aella_cli lab scenario agent remove` — tear down Sandcat when
   safe.
3. Optional snapshot revert: `aella_cli lab snapshot revert <name>` after
   quiesce (see `docs/operational-recovery.md`).
4. Retain logs under `logs/` and state under `runtime/state/` per
   `docs/operational-maintenance.md`.

---

## 10. Troubleshooting flow

Use this order (also in `README.md` §10.1):

1. `aella_cli lab scenario run <id> --dry-run` — stdout/stderr preflight.
2. `tail -n 80 logs/caldera-orchestration.jsonl` — `scenario_preflight_failed`,
   `scenario_live_run_failed`, warnings.
3. `aella_cli lab scenario bootstrap validate` — HTTP, key, plugins path.
4. `aella_cli lab scenario atomic validate` — ART on guests.
5. `aella_cli lab scenario agent deploy` / `agent status`.
6. `aella_cli lab mirror verify` / `nat verify`.
7. `aella_cli lab scenario pack validate` / `scenario status --human`.
8. Network plane: `virsh net-info ovs-net`, `ovs-vsctl show`, `ip -4 addr show dev br0`
   — confirm **OVS `br0`** + **`ovs-net`** (spec 006).
9. **RC reboot gate:** `${XDR_ROOT}/bootstrap/validate-host-network.sh` exit 0;
   if fail, `sudo ${XDR_ROOT}/bootstrap/fix-runtime-state.sh` then re-validate.
   See `docs/operational-validation.md`.

Deeper recovery: `docs/operational-recovery.md`, `docs/caldera-integration.md` §9+.

---

## 11. See also

- `docs/live-run-playbook.md` — first live adversary run (ordered playbook).
- `docs/runtime-evidence-collection.md` — evidence bundle workflow.
- `docs/runtime-state-inspection.md` — `runtime/state/*.json` field guide.
- `docs/operator-troubleshooting-matrix.md` — failure codes and recovery.
- `docs/release-candidate-checklist.md` — RC sign-off matrix.
- `docs/runtime-smoke-validation.md` — minimal CI/smoke commands.
- `docs/environment-sanity-checklist.md` — full sanity pass + live recon
  sequence (§12).
