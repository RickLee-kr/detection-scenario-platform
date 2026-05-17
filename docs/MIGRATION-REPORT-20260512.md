# Migration Report — 2026-05-12

Migration of scattered XDR lab assets into the canonical project root
`/home/aella/xdr-lab-appliance`.

## 1. Source → Target table

| # | Source path                                                                          | Target path                                                              | Type            | Exec | Duplicate? | Refs updated |
|---|--------------------------------------------------------------------------------------|--------------------------------------------------------------------------|-----------------|------|------------|--------------|
| 1 | `/home/aella/Stellar appliance cli/appliance_cli.py`                                 | `appliance/appliance_cli.py`                                             | Python CLI      | no   | no         | yes (XDR_BASE env) |
| 2 | `/home/aella/Stellar appliance cli/setup.py`                                         | `appliance/setup.py`                                                     | Python package  | no   | no         | no |
| 3 | `/home/aella/Stellar appliance cli/src/stellar_appliance_cli/__init__.py`            | `appliance/src/stellar_appliance_cli/__init__.py`                        | Python package  | no   | no         | no |
| 4 | `/home/aella/Stellar appliance cli/src/stellar_appliance_cli/appliance_cli.py`       | `appliance/src/stellar_appliance_cli/appliance_cli.py`                   | Python (legacy) | no   | no         | yes (XDR_BASE env) |
| 5 | `/home/aella/Stellar appliance cli/cli-installer.sh`                                 | `installer/cli-installer.sh`                                             | Shell           | yes  | no         | yes (PROJECT_ROOT-relative) |
| 6 | `/home/aella/Stellar appliance cli/packaging/opt/xdr-lab/scripts/xdr-lab-vm-manager.sh` | `scripts/xdr-lab-vm-manager.sh`                                       | Shell           | yes  | no         | yes (paths.sh sourcing) |
| 7 | `/home/aella/Stellar appliance cli/packaging/opt/xdr-lab/config/lab-vms.json`        | `config/lab-vms.json`                                                    | JSON            | no   | no         | no |
| 8 | `/home/aella/Stellar appliance cli/skills/*.md` (7 files)                            | `docs/skills/*.md`                                                       | Markdown        | no   | no         | no |
| 9 | `/home/aella/Stellar appliance cli/.specify/specs/0[01][0-9]-*/spec.md` (12 dirs)    | `docs/specs/0[01][0-9]-*/spec.md`                                        | Markdown        | no   | no         | no |
| 10 | `/home/aella/Stellar appliance cli/.specify/specs-index.md`                         | `docs/specs/specs-index.md`                                              | Markdown        | no   | no         | no |
| 11 | `/home/aella/Stellar appliance cli/.specify/memory/constitution.md`                 | `docs/memory/constitution.md`                                            | Markdown        | no   | no         | no |
| 12 | `/home/aella/xdr-lab-cloudinit/create-cloud-vm.sh`                                  | `scripts/create-cloud-vm.sh`                                             | Shell           | yes  | no         | yes (paths.sh sourcing) |
| 13 | `/home/aella/xdr-lab-cloudinit/sensor-vm/{user-data,meta-data}`                     | `cloud-init/sensor-vm/{user-data,meta-data}`                             | deprecated dev-only cloud-init reference      | no   | no         | no |
| 14 | `/home/aella/xdr-lab-cloudinit/test-vm1/{user-data,meta-data}`                      | `cloud-init/test-vm1/{user-data,meta-data}`                              | cloud-init      | no   | no         | no |
| 15 | `/home/aella/xdr-lab-cloudinit/test-vm2/{user-data,meta-data}`                      | `cloud-init/test-vm2/{user-data,meta-data}`                              | cloud-init      | no   | no         | no |
| 16 | `/home/aella/cloudinit/test-vm1/{user-data,meta-data}`                              | `cloud-init/test-vm1-extras/{user-data,meta-data}`                       | cloud-init      | no   | yes (variant) | no |
| 17 | `/home/aella/ovs-net.xml`                                                           | `config/ovs-net.xml`                                                     | libvirt XML     | no   | no         | no |
| 18 | `/home/aella/xdr-lab-cloudinit/*/seed.iso` (3 files, 374 KB each)                   | (kept in backups only — `.gitignore` filters `*.iso`)                    | binary          | no   | no         | n/a |

Files **NOT moved** (intentionally out of scope):

- `/home/aella/jammy-server-cloudimg-amd64.img` (692 MB Ubuntu cloud image — gitignored; lives in libvirt pool)
- `/home/aella/ubuntu.iso` (3.3 GB, owned by `libvirt-qemu:kvm`)
- `/home/aella/download.sh` (Google Drive helper — backed up under `backups/.../misc/`, not part of the lab runtime)
- `/home/aella/downloaded_file.ext` (artefact from `download.sh`)
- The two source git repos (`/home/aella/Stellar appliance cli/.git`, `xdr-lab-appliance/.git` already existed). Source repo history is preserved at its original location.

## 2. Backup snapshot

`backups/pre-migration-20260512/` (2.6 MB):

- `stellar-appliance-cli/`  — exact copy of `/home/aella/Stellar appliance cli/` (incl. its `.git/`)
- `xdr-lab-cloudinit/`      — exact copy of `/home/aella/xdr-lab-cloudinit/` (incl. seed.iso)
- `cloudinit/`              — exact copy of `/home/aella/cloudinit/`
- `misc/ovs-net.xml`        — original libvirt XML
- `misc/download.sh`        — original google-drive helper

All copies preserve mtime, ownership and executable bits (`cp -a`).

## 3. Path-reference updates

Every script that previously hard-coded `/opt/xdr-lab`, `$HOME/xdr-lab-cloudinit`,
or `/var/lib/libvirt/images` now sources `config/paths.sh` (when present)
and honours environment overrides:

| File                                | What changed |
|-------------------------------------|--------------|
| `scripts/create-cloud-vm.sh`        | Sources `paths.sh`; uses `${UBUNTU_CLOUD_BASE_IMG}`, `${LIBVIRT_IMAGE_DIR}`, `${CLOUDINIT_DIR}`, `${LAB_OVS_NETWORK}`. Original behaviour identical when defaults apply. |
| `scripts/xdr-lab-vm-manager.sh`     | Sources `paths.sh` if present (no-op when run from the install target). Still respects `XDR_BASE` (default `/opt/xdr-lab`). |
| `installer/cli-installer.sh`        | Rewritten for the new layout: pip-installs `appliance/`, copies `scripts/xdr-lab-vm-manager.sh` and `config/lab-vms.json` into `${XDR_ROOT}` (default `/opt/xdr-lab`). |
| `appliance/appliance_cli.py`        | `LAB_MANAGER` / `LAB_CONFIG` now read from `XDR_LAB_MANAGER` / `XDR_LAB_CONFIG` / `XDR_BASE` env vars. |
| `appliance/src/stellar_appliance_cli/appliance_cli.py` (legacy) | Same env-var pattern; kept as a reference snapshot. |

## 4. Backwards compatibility

Operational impact on the **existing running lab**:

- The previous install target `/opt/xdr-lab` still works (defaults unchanged).
- Existing libvirt domains, OVS bridge `br0`, network `ovs-net`, and any
  in-place `~/xdr-lab-cloudinit/` seed ISOs are untouched.
- `aella_cli` (if currently installed via the old `cli-installer.sh`)
  continues to work because the manager path defaults remain
  `/opt/xdr-lab/scripts/xdr-lab-vm-manager.sh`.
- Re-running the new `installer/cli-installer.sh` will overwrite the
  installed shell manager and JSON config in-place under `/opt/xdr-lab/`
  (same paths as before).

## 5. Validation results

```
bash -n scripts/*.sh installer/*.sh config/paths.sh     -> all OK
python3 -m py_compile appliance/appliance_cli.py        -> OK
python3 -m py_compile appliance/setup.py                -> OK
python3 -c "json.load(open('config/lab-vms.json'))"     -> OK
xmllint --noout config/ovs-net.xml                      -> OK
aella_cli help / lab help / lab deploy ... --dry-run    -> OK
XDR_BASE=$PWD aella_cli lab deploy sensor-vm --dry-run  -> resolves repo-local manager path correctly
shellcheck                                              -> not installed on host (recommended to install)
```

## 6. Broken or missing items

- **None**. No file was deleted or overwritten on the original lab host.
- `seed.iso` files are intentionally not promoted into the repo
  (gitignored as `*.iso`). They live in `backups/` and can be
  regenerated by `cloud-localds`.
- `shellcheck` was not available on the host — recommend
  `sudo apt install shellcheck` before committing further shell changes.

## 7. Remaining technical debt

1. `scripts/xdr-lab-vm-manager.sh` runs `mkdir -p "${XDR_BASE}/..."` at
   script load time. When run from the repo without sudo and with
   `XDR_BASE=/opt/xdr-lab`, this prints `Permission denied`. Recommend
   deferring `mkdir` calls until an action actually needs them, or
   adding an early `if [[ ! -w $(dirname "$XDR_BASE") ]]; then die ...`
   short-circuit when not running install commands.
2. `appliance/src/stellar_appliance_cli/` is explicitly a legacy
   snapshot per spec 005. Recommend either deleting it or moving it
   under `docs/legacy/` once spec 005 is finalized.
3. `appliance_cli.py` still imports `cmd_appliance_status` /
   `cmd_appliance_info` that shell out to `uptime` / `uname` without
   honouring `dry-run`. Low-risk, but worth aligning.
4. `cloud-init/test-vm1-extras/` is a near-duplicate of
   `cloud-init/test-vm1/` from a parallel `/home/aella/cloudinit/`
   working copy. Decide which is authoritative and remove the other.
5. Reverse-NAT materialization (spec 010) and OVS mirror automation
   (spec 007) are still in `_future_capabilities` in
   `config/lab-vms.json` — they are not part of the migration but are
   the highest-value next features.
6. `scenarios/`, `templates/`, `tests/` are empty placeholders.

## 8. Recommended next implementation steps

1. **Commit the migration snapshot** (operator decision — git config
   must be valid):
   ```bash
   cd /home/aella/xdr-lab-appliance
   git add .
   git commit -m "chore: initial migration into xdr-lab-appliance repo"
   ```
2. **Install shellcheck** and re-run `shellcheck -x scripts/*.sh
   installer/*.sh` to harden the bash codebase.
3. **Run the installer in-place** to verify backwards-compat:
   ```bash
   sudo bash installer/cli-installer.sh
   aella_cli lab status
   ```
4. **Materialize the OVS mirror** (spec 007) — add
   `scripts/ovs-mirror.sh` that reads `lab-vms.json` and runs the
   `ovs-vsctl -- --id=@m create mirror ...` sequence.
5. **Materialize reverse-NAT** (spec 010) — add `scripts/rnat.sh`
   that emits idempotent iptables rules from
   `lab-vms.json[*].external_nat_port_mapping`.
6. **Scenario framework** (spec 008) — add a minimal
   `scenarios/0001-recon-baseline.yaml` and a `scenarios/run.sh`
   runner.
7. **TUI** — wire `aella_cli` into a curses/textual front-end that
   reuses the existing `do_lab()` dispatch table.

## 9. Decommissioning the legacy locations (operator-only)

Once parity is verified, the operator may remove these — they are
**not removed by this migration**:

```
rm -rf "/home/aella/Stellar appliance cli"
rm -rf "/home/aella/xdr-lab-cloudinit"
rm -rf "/home/aella/cloudinit"
rm    "/home/aella/ovs-net.xml"
```

A copy of every file lives under
`/home/aella/xdr-lab-appliance/backups/pre-migration-20260512/`.
