# Packaging Structure Guidance (Future) — XDR Lab Appliance

**Status:** documentation only. **No** OVA build, install script rewrite,
registry publishing, or offline bundler is implemented in this change set.

This section describes a **recommended** layout for a future **release
candidate** so operators, CI, and field teams share the same vocabulary.

---

## 1. Goals

- **Repeatable installs** across air-gapped and connected sites.
- **Clear separation** between versioned binaries, mutable runtime, and
  operator-local secrets.
- **Auditable artifacts** (checksum files, SBOM placeholders, release
  notes).

---

## 2. Recommended OVA (future)

```
xdr-lab-appliance-<version>.ova
├── xdr-lab-appliance-<version>-disk1.vmdk   # Ubuntu 24.04 golden guest
├── xdr-lab-appliance-<version>.ovf         # vCPU/RAM/network hints
└── xdr-lab-appliance-<version>.mf          # SHA-256 manifest
```

**Embedded expectations**: preinstall `aella_cli`, ship `/opt/xdr-lab`
skeleton with empty `images/` and `runtime/`, include **no** secrets.
First boot runs `cloud-init` or an operator `install.sh` phase to lay
down `lab-vms.json` URLs and CALDERA settings.

---

## 3. Recommended `install.sh` (future)

Single entrypoint idempotent with today's `installer/cli-installer.sh`
responsibilities, extended with flags:

```
install.sh [--offline-bundle PATH] [--project-root PATH] [--skip-images]
```

**Suggested behavior**:

- Copy `scripts/`, `config/*.example` → `config/` (do not overwrite existing).
- `pip install` / `setup.py` for `aella_cli`.
- Optional `--offline-bundle` extracts qcow2 + manifest into `${XDR_BASE}/images`.

---

## 4. Image repository (future)

Logical layout (HTTPS or object storage):

```
/xdr-lab/<release>/
  manifest.json              # URLs, sizes, sha256
  sensor/6.2.0/virt_deploy_modular_ds.sh
  sensor/6.2.0/aella-modular-ds-6.2.0.qcow2
  windows-victim.qcow2
  linux-server.qcow2
  test-vm1.qcow2
```

`config/images-manifest.json` (already referenced in `aella_cli` help)
should remain the **machine-readable** join point between semver and
download URLs.

---

## 5. Offline bundle (future)

```
xdr-lab-offline-<version>.tar.zst
├── manifest.json
├── images/...
├── scenarios/...
├── bootstrap/...
└── README.txt   # pointer back to docs/deployment-readiness.md
```

Operators unpack to a staging directory, point `XDR_BASE`, and run
`lab download all --force` against local `file://` URLs or a static
file layout mirrored 1:1 with the online repository.

---

## 6. Release artifact layout (future GitHub / Artifactory / S3)

```
release/xdr-lab-appliance-<version>/
  xdr-lab-appliance-<version>.ova
  xdr-lab-offline-<version>.tar.zst
  SHA256SUMS
  SBOM.json                    # placeholder until pipeline emits SPDX
  RELEASE_NOTES.md
  docs-html.zip                # optional frozen render of docs/
```

---

## 7. Compatibility with today's tree

Until packaging lands, the **authoritative** install path remains:

```bash
sudo bash installer/cli-installer.sh
```

and documentation in `README.md` plus `docs/deployment-readiness.md`.

---

## 8. Release naming convention

- **Source / Git:** tags `vMAJOR.MINOR.PATCH` (e.g. `v1.4.0`) or
  `vMAJOR.MINOR.PATCH-rcN` for release candidates (e.g. `v1.4.0-rc1`).
- **Debian / OVA filenames:** `xdr-lab-appliance_<version>_<arch>.deb`,
  `xdr-lab-appliance-<version>.ova` — **ASCII**, no spaces.
- **Offline bundle:** `xdr-lab-offline-<version>.tar.zst` aligned with the
  same semantic version as the Git tag.

---

## 9. Artifact versioning

- **Semantic version** is the primary operator-facing version for release
  notes and compatibility statements.
- **Image manifest** (`manifest.json` URLs, §4) SHOULD embed the same
  `version` string as the release tag minus a leading `v` if you normalize
  that way — document the chosen rule once in `RELEASE_NOTES.md` for the
  release.
- **Build metadata** (git SHA, build timestamp) SHOULD appear in
  `SBOM.json` or `RELEASE_NOTES.md` appendix, not inside `lab-vms.json`
  (preserve additive-only schema evolution elsewhere).

---

## 10. SHA256 workflow

1. After building release binaries / images, run `sha256sum` on each
   shipped artifact from a **clean** build directory.
2. Write **`SHA256SUMS`** at the release root with **one line per file**:
   `HASH  filename` (two spaces preferred for GNU compatibility).
3. Publish **`SHA256SUMS`** alongside artifacts; operators verify with
   `sha256sum -c SHA256SUMS`.
4. Optionally sign **`SHA256SUMS`** with GPG (`*.asc`) using your org’s
   release key — not required by this repository today.

---

## 11. Image manifest structure

Recommended **`manifest.json`** fields (additive, machine-readable):

| Field | Purpose |
| --- | --- |
| `version` | Release semver string |
| `released_at` | ISO-8601 UTC timestamp |
| `artifacts[]` | Each: `name`, `url`, `size_bytes`, `sha256` |
| `min_schema_version` | Lowest `lab-vms.json` `schema_version` supported |
| `notes` | Short English string; pointer to `RELEASE_NOTES.md` |

QCow2 URLs remain **content**, not embedded in the Python package
(constitution M-3, M-4).

---

## 12. Release notes structure

`RELEASE_NOTES.md` for each public drop SHOULD contain:

1. **Version + date** — semver and UTC date.
2. **Summary** — one paragraph operator-facing summary.
3. **Changed components** — CLI, `xdr-lab-vm-manager.sh`, scenario packs,
  config templates (additive fields only unless `schema_version` bumped).
4. **Upgrade steps** — explicit commands (`pip install -e .`, installer,
  `virsh net-define` if XML changed).
5. **Known limitations** — link to specs (006–012) and runbooks.
6. **Checksums** — pointer to `SHA256SUMS` or inline table for small
  releases.

---

## 13. Upgrade compatibility notes

- **CLI:** existing subcommands and IP/port contracts MUST be preserved
  (constitution M-6); release notes call out **additive** subcommands only.
- **`lab-vms.json`:** upgrades MUST respect `schema_version`; unknown
  versions remain a hard error (constitution §8).
- **Runtime JSON / JSONL:** additive fields only; do not rename keys that
  consumers rely on. Release notes SHOULD list new JSONL `event` types or
  state file keys.
- **OVS / libvirt:** upgrading the host OVS or libvirt packages is
  operator-owned; note any **minimum** versions discovered during RC
  validation.

---

## 14. Runtime state compatibility expectations

After upgrade, operators SHOULD:

1. Re-run `aella_cli lab nat verify` and `aella_cli lab mirror verify` on
   the target host.
2. Inspect `runtime/state/*.json` — old files remain readable; new fields
   appear additively.
3. Truncate or archive JSONL only **after** copy-out (`docs/operational-maintenance.md`).

State files are **derived**; deleting them is recoverable by re-running
verify/apply paths — release notes SHOULD say so when state layout gains
optional keys.

---

## 15. Release hardening recommendations

Operational guidance for teams preparing **immutable-ish** drops and safer
field upgrades. This does not mandate a specific CI vendor.

### 15.1 Immutable release recommendations

- Publish **read-only** artifact directories per version (no in-place
  overwrites of `v1.2.3` objects after release timestamp).
- Tag Git **exactly** at the commit reflected in `RELEASE_NOTES.md`.
- Attach **SBOM** and **license** archives even when placeholders (§6).
- Prefer **separate** channels for `-rc` vs GA artifacts to reduce operator
  confusion.

### 15.2 Image checksum verification workflow

1. Download OVA / offline bundle / qcow2 set to a staging host.
2. Verify **`SHA256SUMS`** with `sha256sum -c SHA256SUMS` from a clean directory
   (§10).
3. Optionally verify **GPG** `.asc` if your org signs sums.
4. Record verifier identity + UTC time in the ticket.

### 15.3 Runtime backup guidance

Before host OS upgrades or CALDERA major bumps:

- Copy `${XDR_BASE}/runtime/state/*.json` and `${XDR_BASE}/logs/*.jsonl` to
  read-only archive (`docs/runtime-evidence-collection.md`).
- Export `virsh dumpxml` for each lab domain if required by change-management
  policy (operator-owned; not automated here).

### 15.4 State preservation guidance

- Treat `runtime/state` as **audit** input — back up before destructive lab
  actions (`lab cleanup`).
- Never commit live `caldera-lab.json` secrets; use private overlays or
  `api_key_file` paths documented per operator security standard.

### 15.5 Upgrade testing recommendations

- Spin a **staging** appliance with the same ESXi portgroup policy; run
  `docs/environment-sanity-checklist.md` §§1–13.
- Re-run `aella_cli lab scenario run <id> --snapshot-before --dry-run` then a
  short live smoke if policy allows.
- Compare JSONL event keys to prior release — only **additive** new `event`
  strings should appear without release-note callouts.

### 15.6 Rollback recommendations

- Keep previous **deb** / **pip** package and previous qcow2 **`SHA256SUMS`**
  until the new version survives one full checklist pass.
- If orchestration regressions appear, restore prior `appliance_cli` +
  `xdr-lab-vm-manager.sh` together (matched pair).
- For guest corruption, prefer **`snapshot revert`** over `destroy` when a
  known-good snapshot exists (`docs/operational-recovery.md`).
