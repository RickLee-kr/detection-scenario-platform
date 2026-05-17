# Runtime Smoke Validation — XDR Lab Appliance

Minimal **CI** and **pre-push** guidance for maintainers: fast checks that
do **not** substitute for a full lab or CALDERA server. No telemetry
auto-validation; no fake success paths. **English-only** operational
documentation.

**Lab topology words:** Open vSwitch bridge **`br0`**, OVS-backed libvirt
**`ovs-net`**, **openvswitch virtualport**.

---

## 1. Python syntax (`py_compile`)

From the repository root (adjust paths if `appliance_cli.py` lives under
`appliance/` in your checkout):

```bash
cd /path/to/xdr-lab-appliance
python3 -m py_compile appliance/appliance_cli.py \
  scripts/caldera_orchestration.py \
  scripts/ovs_mirror_state.py \
  scripts/snapshot_state.py \
  scripts/nat_state.py \
  scripts/image_download_manager.py \
  scripts/vm_runtime_state.py
```

**Pass:** exit code 0, no `SyntaxError`.

---

## 2. Shellcheck (recommended)

Static analysis for shell entrypoints (optional in CI if `shellcheck` is
installed):

```bash
command -v shellcheck >/dev/null 2>&1 && shellcheck -x scripts/xdr-lab-vm-manager.sh scripts/create-cloud-vm.sh installer/cli-installer.sh bootstrap/caldera-server-bootstrap.sh bootstrap/atomic-red-team-linux.sh || true
```

**Pass:** no errors (warnings are team policy). If `shellcheck` is absent,
skip explicitly in CI logs.

---

## 3. Dry-run scenario validation

Requires `config/caldera-lab.json` and API key for HTTP probes where
implemented:

```bash
source config/paths.sh
aella_cli lab scenario pack validate
aella_cli lab scenario bootstrap validate || true
aella_cli lab scenario run recon --snapshot-before --dry-run || true
```

**Pass:** commands return per policy; **`--dry-run`** must not perform live
CALDERA mutations or libvirt snapshots. Inspect stderr for
`scenario_preflight_failed` vs expected warnings (empty `adversary_id` warns
in pack validate but **blocks** live run only).

---

## 4. JSON syntax validation

**Config and packs** (run from repo root):

```bash
for f in config/lab-vms.json config/caldera-lab.json scenarios/*.json; do
  [ -f "$f" ] || continue
  python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$f" || exit 1
done
```

**Runtime state examples** (if tracked):

```bash
for f in docs/examples/runtime-state/*.example; do
  [ -f "$f" ] || continue
  python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$f" || exit 1
done
```

**Pass:** no `JSONDecodeError`.

---

## 5. Runtime artifact validation

After any local engine dry-run that materializes state:

```bash
test -d runtime/state || mkdir -p runtime/state
# When mirror/nat engines have run:
for f in mirror.json nat.json scenario.json caldera.json; do
  if [ -f "runtime/state/$f" ]; then python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "runtime/state/$f" || exit 1; fi
done
```

**Pass:** existing JSON state files parse; absence is not a failure in a
clean tree.

---

## 6. Mirror validation (live host only)

On an appliance with OVS + VMs:

```bash
aella_cli lab mirror apply --dry-run
aella_cli lab mirror verify
```

**Pass:** `verify` exit 0 when mirror consistent on **`br0`**.

---

## 7. Stellar sensor readiness (live host only)

Operational readiness requires the real Stellar Cyber Modular Data Sensor
artifacts, not a development cloud-image VM:

```bash
${XDR_ROOT:-/opt/xdr-lab}/bootstrap/validate-sensor-identity.sh
${XDR_ROOT:-/opt/xdr-lab}/bootstrap/validate-appliance.sh --strict
```

**Pass:** output includes `sensor_type=stellar_sensor`,
`stellar_sensor_artifact_found=true`, `stellar_sensor_ready=true`, and
`READY_FOR_STELLAR_SENSOR_SCENARIO=true`.

---

## 8. Snapshot validation (live libvirt only)

```bash
aella_cli lab snapshot create ci-smoke --dry-run
```

**Pass:** engine accepts; live snapshot requires running domains and disk
space.

---

## 9. Environment sanity workflow

For a full pass on real hardware, run **`docs/environment-sanity-checklist.md`**
end-to-end, then **`docs/release-candidate-checklist.md`** for RC gating.

---

## 10. Suggested CI job skeleton (example)

```yaml
# Illustrative only — adapt to your runner image.
steps:
  - uses: actions/checkout@v4
  - run: python3 -m py_compile appliance/appliance_cli.py scripts/*.py
  - run: |
      for f in config/lab-vms.json config/caldera-lab.json scenarios/*.json; do
        python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$f"
      done
  - run: command -v shellcheck && shellcheck -x scripts/xdr-lab-vm-manager.sh || true
```

---

## 11. See also

- `docs/live-run-playbook.md`
- `docs/runtime-evidence-collection.md`
- `docs/runtime-state-inspection.md`
- `docs/operator-troubleshooting-matrix.md`
- `docs/real-environment-bringup.md`
- `docs/release-candidate-checklist.md`
- `docs/environment-sanity-checklist.md`
