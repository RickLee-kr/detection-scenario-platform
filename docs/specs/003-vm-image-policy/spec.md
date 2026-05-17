# Spec 003 — VM Image Policy

> Binds to: constitution §5, §6, M-3, M-4, M-9, P-1, P-4. Refines L3
> from spec 001.

## 1. Goal

Define how VM images (base qcow2 files and the sensor deploy
script + sensor qcow2) are **sourced, cached, verified, updated, and
versioned**.

Images are **content**, not code: they live outside the package, are
downloaded at deploy time, and are owned by the appliance under
`/opt/xdr-lab/images/`.

## 2. Architecture

```
remote artifact host(s)
        │
        │  HTTPS (curl / wget; declared in lab-vms.json)
        ▼
/opt/xdr-lab/images/
  ├── <vm>/<disk_filename>         (generic VMs; immutable after download)
  └── sensor/
        ├── virt_deploy_modular_ds.sh   (sensor deploy script; exec bit set)
        └── <sensor base>.qcow2          (sensor base disk)
```

L2 (the runtime layer) is the **only** writer to this tree. L1
never writes here.

## 3. Component Responsibilities

### 3.1 `download_vm_image <vm>`

- Validates that `<vm>` is a key in `lab-vms.json::vms`.
- Reads `image_url` (and, for sensor, `virt_deploy_script_url` and
  `virt_deploy_script_name` and `sensor_cache_dir`).
- Creates the per-VM directory (or sensor cache dir).
- Downloads via `curl -fL --retry 3 --retry-delay 2` (preferred)
  or `wget -q -O` (fallback). No third tool is used.
- For sensor: also downloads the deploy script and `chmod a+x`s
  it.
- Emits `download_vm_image_begin` / `download_vm_image_end`
  structured logs.

### 3.2 Cache locations

- Generic VMs: `${IMG}/<vm>/<disk_filename>` where `IMG =
  /opt/xdr-lab/images`.
- Sensor: `${sensor_cache_dir}/<basename(image_url)>` and
  `${sensor_cache_dir}/${virt_deploy_script_name}`. The cache dir
  is declared in `lab-vms.json` (default
  `/opt/xdr-lab/images/sensor`).

### 3.3 Verification

This spec governs the **policy**; verification primitives may be
implemented incrementally.

- **MVP (today):** trust the HTTPS transport. `curl -fL` returns
  non-zero on HTTP errors; partial downloads fail the deploy
  precondition (`Missing qcow2`).
- **Required next iteration:** declared `sha256` per artifact in
  `lab-vms.json`. After download, L2 MUST compute `sha256sum` and
  compare. Mismatch → delete the bad file, emit a structured
  error, abort deploy.
- **Optional future:** detached signature (`*.qcow2.sig`) and a
  pinned public key. Not implemented; reserved.

## 4. Operational Assumptions

- The appliance has outbound HTTPS to the configured artifact host
  at the moment of `download`.
- Disk under `/opt/xdr-lab/` has enough free space for base +
  runtime (rule of thumb: `2 × sum(disk_size_gb)`).
- The operator can pre-warm caches by running `download all` on a
  separate appliance and copying `/opt/xdr-lab/images/` into the
  production appliance (the runtime layer treats existing files
  as cache hits).

## 5. Runtime Flow

```
download_vm_image <vm>
 ├─ assert L4 config present
 ├─ assert vm is a known key
 ├─ read type
 ├─ if sensor:
 │    ├─ read sensor_cache_dir, virt_deploy_script_url,
 │    │      image_url, virt_deploy_script_name
 │    ├─ mkdir -p sensor_cache_dir
 │    ├─ download_to script_url → ${sensor_cache_dir}/${script_name}
 │    ├─ chmod a+x …
 │    └─ download_to image_url → ${sensor_cache_dir}/$(basename image_url)
 └─ else:
      ├─ read image_url, disk_filename
      ├─ mkdir -p /opt/xdr-lab/images/<vm>
      └─ download_to image_url → /opt/xdr-lab/images/<vm>/<disk_filename>
```

## 6. Failure Handling Philosophy

- Network failure → `curl -fL` non-zero → `set -euo pipefail`
  aborts → structured log entry exists (begin without matching
  end). Operator retries.
- Wrong URL → 404 → curl non-zero → same as above. Operator fixes
  `lab-vms.json` (or the URL is fixed upstream) and retries.
- Disk full → `curl` exits non-zero on write → same as above.
- Checksum mismatch (when implemented) → file is deleted before
  exit so retry starts clean.

## 7. Recovery Philosophy

- A corrupt or partial base file is recovered by simply re-running
  `download <vm>` (idempotent, overwrites the same path).
- If `chmod a+x` failed on the sensor script (e.g. filesystem
  oddity), operator inspects logs, re-runs `download sensor-vm`.
- A wholly bad cache is recovered by deleting **only** the
  affected VM's subdirectory (or, for sensor, the affected file),
  then re-running `download`. Operators MUST NOT
  `rm -rf /opt/xdr-lab/images` (constitution P-10).

## 8. Image Caching Policy

- `download` is **idempotent** — re-running with the same config
  re-fetches and overwrites in place.
- L2 SHOULD NOT short-circuit a download just because the file
  exists; existing files are overwritten. (Rationale: the operator
  explicitly asked to `download`, so a re-download is the
  expected behavior.)
- Deploy, by contrast, **does** consume the cache: if a base image
  is present, deploy uses it as-is and does NOT re-download.
- The `--nodownload` flag (today: sensor only) MUST always
  consume the cache without re-downloading the sensor script /
  sensor qcow2.

## 9. Image Update Policy

- Images are updated via an explicit operator action:
  1. Update `image_url` in `lab-vms.json` (and `sha256` once that
     field exists).
  2. Run `aella_cli lab download <vm>`.
  3. Run `aella_cli lab destroy <vm>` (releases the old runtime
     qcow2).
  4. Run `aella_cli lab deploy <vm>`.
- L2 MUST NOT silently re-download a base image because its URL
  changed; the operator initiates downloads.
- Sensor script updates follow the same pattern via
  `virt_deploy_script_url`.

## 10. Checksum Philosophy (forward-looking)

When implemented (next iteration):

- `lab-vms.json` gains, per VM, optional `sha256` and (for sensor)
  `script_sha256` fields.
- L2 computes `sha256sum` after every download.
- Mismatch is a hard failure: file is deleted, structured error
  is emitted, exit non-zero.
- Match is a structured log line `image_checksum_ok vm=<vm>`.
- The absence of `sha256` is allowed during the MVP phase but
  MUST emit a `WARN` structured log so operators know they are
  trusting the transport only.

## 11. Image Versioning Philosophy

- `image_url` SHOULD encode an immutable version in the path or
  query string (e.g. `…/sensor-base-2026.05.qcow2`). Mutable
  "latest" URLs are discouraged because they break reproducibility.
- A future `version` field per VM in `lab-vms.json` MAY be added
  for human readability; it does NOT replace the URL.
- The appliance does NOT maintain its own version registry; the
  authoritative version is whatever the URL points at.

## 12. Future Extensibility Guidance

- A future "mirror cache" feature (LAN-local artifact host) MUST
  be modelled by changing `image_url` to point at the mirror; the
  runtime layer does not learn about mirrors.
- A future signed-image flow MUST add a separate verification
  step after sha256 verification.
- A future "purge unused images" verb is acceptable, but it MUST
  enumerate the lab inventory and only delete subdirectories of
  `/opt/xdr-lab/images/` that match removed inventory entries
  (spec 011).

## 13. Forbidden Implementation Patterns

- Shipping qcow2 inside the Python wheel, the deb, or any tarball
  produced by `setup.py` (constitution P-1).
- Reaching for `apt install`/`dnf install` to obtain an image
  (constitution P-9). Images come from declared URLs.
- Auto-deleting unknown qcow2 files under
  `/opt/xdr-lab/images/` (constitution P-4). Cleanup is
  inventory-scoped and operator-initiated.
- Writing to base images post-download (`qemu-img resize` against
  the L3 base; that is the runtime's job in L5 — spec 002).
- Using insecure transports (HTTP without TLS, FTP). All
  `image_url`s MUST be `https://`.

## 14. Validation Philosophy

A change to image handling is valid only if:

1. `download <vm>` is idempotent and overwrites in place.
2. `download all` continues past per-VM failures with `WARN`
   logs.
3. No base image is shipped in any release artifact.
4. After `deploy <vm>`, the file at
   `/opt/xdr-lab/images/<vm>/<disk_filename>` is byte-identical
   to what was downloaded.
5. Sensor cache layout is exactly
   `${sensor_cache_dir}/${virt_deploy_script_name}` and
   `${sensor_cache_dir}/<basename(image_url)>` — the sensor deploy
   script depends on this.
6. Once `sha256` is added to `lab-vms.json`, every successful
   download produces an `image_checksum_ok` event and every
   mismatch produces an `image_checksum_failed` event followed by
   file removal.
