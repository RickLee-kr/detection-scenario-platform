# Spec 004 — Sensor Deployment

> Binds to: constitution §2, §3, §4, M-12, M-13, P-2. Refines the
> sensor branch of L2 (spec 002) and the sensor cache layout in L3
> (spec 003).

## 1. Goal

Define how the **Sensor VM** is deployed. The sensor is the XDR/NDR
sensor under test; its deploy path is intentionally **different
from generic VMs**:

- It uses a dedicated, externally-delivered modular deploy script
  (`virt_deploy_modular_ds.sh`).
- It has a **fixed bridge** (`br0`), a **fixed internal IP**
  (today `10.10.10.10`), and a **fixed hostname**.
- It does **not** use SPAN/mirror as part of its own deploy;
  mirror configuration is a separate concern (spec 007).

This spec exists because the sensor's onboarding contract is owned
upstream and cannot be re-implemented inside the appliance.

## 2. Architecture

```
config (lab-vms.json :: vms.sensor-vm)
  ├─ type               = "sensor"
  ├─ hostname           = "sensor-vm"
  ├─ bridge             = "br0"          (M-10)
  ├─ internal_ip        = "10.10.10.10"  (in 10.10.10.0/24, M-11)
  ├─ virt_deploy_script_url
  ├─ virt_deploy_script_name = "virt_deploy_modular_ds.sh"
  ├─ image_url          (sensor base qcow2)
  └─ sensor_cache_dir   = "/opt/xdr-lab/images/sensor"

L3 sensor cache:
  /opt/xdr-lab/images/sensor/
    ├── virt_deploy_modular_ds.sh   (chmod a+x)
    └── <sensor-base>.qcow2

L2 sensor deploy:
  cd /opt/xdr-lab/images/sensor && \
    bash ./virt_deploy_modular_ds.sh \
       [--nodownload] \
       --bridge br0 \
       --ip 10.10.10.10 \
       --netmask 255.255.255.0 \
       --gw 10.10.10.1 \
       --dns 10.10.10.1 \
       --hostname sensor-vm

Post-deploy validation:
  virsh dominfo sensor-vm   (must succeed; otherwise WARN)
  ping -c1 -W2 10.10.10.10  (best-effort; WARN on failure)
```

## 3. Component Responsibilities

### 3.1 L4 — Configuration

`lab-vms.json::vms.sensor-vm` declares all sensor-specific fields.
It MUST contain at minimum:

- `name = "sensor-vm"` and `type = "sensor"` (either is sufficient
  for L2 to route to the sensor path; both SHOULD be set).
- `hostname`, `bridge`, `internal_ip`.
- `virt_deploy_script_url`, `virt_deploy_script_name`,
  `image_url`, `sensor_cache_dir`.
- `cpu`, `memory_mb`, `disk_size_gb` (advisory; honored by the
  upstream deploy script).
- `external_nat_port_mapping` (spec 010).
- `autostart`.

The fixed networking values (`netmask`, `gateway`, `dns`) are read
from the top-level `lab-vms.json::network` block (`netmask`,
`gateway`, `dns`) so the lab uses one declared subnet.

### 3.2 L3 — Sensor cache

Owned by `download_vm_image sensor-vm` (spec 003):

- Downloads the script to `${sensor_cache_dir}/${virt_deploy_script_name}`
  and makes it executable.
- Downloads the sensor base qcow2 to
  `${sensor_cache_dir}/$(basename image_url)`.
- Both files are overwritten on re-download.

### 3.3 L2 — Sensor deploy

`deploy_vm sensor-vm [nodownload]` MUST:

1. Determine that the VM is of sensor type
   (`name == "sensor-vm" || type == "sensor"`).
2. Unless `nodownload == 1`, invoke `download_vm_image sensor-vm`
   first.
3. Require `virsh` (the upstream script defines a libvirt domain
   under the hood).
4. Read sensor fields: `sensor_cache_dir`,
   `virt_deploy_script_name`, `bridge`, `internal_ip`, `hostname`.
5. Read network fields: `netmask`, `gateway`, `dns`.
6. Verify the deploy script is executable at
   `${sensor_cache_dir}/${virt_deploy_script_name}`; if not →
   `die "Sensor deploy script missing: … (run download first)"`.
7. Build the argument vector:
   ```
   args=( )
   if nodownload: args+=(--nodownload)
   args+=(--bridge "$bridge"
          --ip "$internal_ip"
          --netmask "$mask"
          --gw "$gateway"
          --dns "$dns"
          --hostname "$hostname")
   ```
   **SPAN flags are intentionally NOT passed.** (See §6 below and
   spec 007.)
8. `cd "$sensor_cache_dir" && bash "./${script_name}" "${args[@]}"`.
9. Call `validate_sensor_deployment` (see §3.4).
10. Reconcile autostart with `apply_autostart sensor-vm`.

### 3.4 Post-deploy validation

`validate_sensor_deployment <vm> <ip> <hostname>`:

- If `virsh dominfo <vm>` succeeds → log
  `validate_sensor_deployment virsh_ok`.
- If it fails → log `validate_sensor_deployment virsh_missing`
  (WARN). This is a soft failure: the upstream script may have
  used a different domain name; the operator inspects logs.
- If `ping -c1 -W2 <ip>` succeeds → log
  `validate_sensor_deployment ping_ok`.
- If it fails → log `validate_sensor_deployment_ping_failed`
  (WARN). Sensor may be still booting; not a deploy failure.

Validation is observability, not gating.

## 4. Operational Assumptions

- `br0` exists and carries `10.10.10.0/24`.
- The sensor deploy script's contract is stable:
  `--bridge --ip --netmask --gw --dns --hostname [--nodownload]`.
  If upstream introduces new required flags, this spec MUST be
  updated before the runtime changes.
- The operator has network access to download the deploy script
  and the sensor base qcow2 (or has pre-warmed the cache).

## 5. Runtime Flow

```
aella_cli lab deploy sensor-vm [--nodownload]
       │
       ▼
xdr-lab-vm-manager.sh deploy sensor-vm [nodownload]
       │
       ├─ if !nodownload → download_vm_image sensor-vm
       │       (writes script + qcow2 into sensor_cache_dir)
       │
       ├─ deploy_sensor_vm sensor-vm nodownload
       │       │
       │       ├─ assert deploy script is executable
       │       ├─ build args
       │       ├─ cd sensor_cache_dir && bash ./virt_deploy_modular_ds.sh …
       │       └─ validate_sensor_deployment sensor-vm 10.10.10.10 sensor-vm
       │
       └─ apply_autostart sensor-vm
```

## 6. No-SPAN Policy

The sensor deploy script supports a SPAN mode upstream. In this
appliance, **SPAN configuration is NOT performed at sensor deploy
time**. Rationale:

- Mirror configuration is a separate, non-destructive operation
  governed by spec 007.
- Coupling SPAN to sensor deploy makes mirror recovery require a
  sensor redeploy, which is unacceptable.
- The sensor's interface for receiving mirrored traffic is the
  same `br0`-attached NIC; OVS mirror (spec 007) delivers the
  copy without involving the sensor's deploy CLI.

Implementer rules:

- L2 MUST NOT pass `--span` (or equivalent) to
  `virt_deploy_modular_ds.sh`.
- L2 MUST NOT add SPAN-related arguments to the sensor's argument
  vector.
- A future "mirror enable" command (spec 007) configures OVS, not
  the sensor.

## 7. Failure Handling Philosophy

- Missing deploy script → `die` early with explicit remediation
  pointer (`run download first`).
- Deploy script non-zero exit → `set -euo pipefail` propagates;
  operator inspects upstream script logs alongside
  `vm-manager.log`.
- `virsh dominfo` post-validate failure → WARN, **not** fatal.
  The upstream script may have produced a different domain name;
  the operator must reconcile.
- Ping post-validate failure → WARN, **not** fatal. Sensor may
  still be booting.

## 8. Recovery Philosophy

- **Bad sensor cache.** Re-run
  `aella_cli lab download sensor-vm`, then
  `aella_cli lab deploy sensor-vm`.
- **Half-deployed sensor.** `aella_cli lab destroy sensor-vm` to
  remove the libvirt domain and the runtime qcow2 the upstream
  script created (if it lives at `/opt/xdr-lab/runtime/`; if the
  upstream script writes elsewhere, the operator follows upstream
  remediation), then redeploy.
- **Sensor cannot ping.** Operator confirms `br0` is up, the
  sensor's interface inside the VM has the declared IP, the
  default route points at `10.10.10.1`, and no firewall is
  blocking. The lab redeploy is **not** the first remediation.
- **Sensor IP change.** Edit `internal_ip` in `lab-vms.json`,
  `destroy`, redeploy. Update any reverse-NAT mappings (spec 010)
  in the same change.

## 9. Sensor Uniqueness Rules

- There is exactly **one** sensor VM in the lab at a time.
  `lab-vms.json` MUST have at most one entry with
  `type == "sensor"`.
- The reserved VM key `sensor-vm` (and the type `sensor`) is
  load-bearing across multiple specs (002, 003, 004, 007).
  Changing the key requires updating all four specs and the
  runtime.
- The sensor cache dir (`/opt/xdr-lab/images/sensor/`) is sensor-
  only. No other VM type writes there.

## 10. Future Extensibility Guidance

- A future "multi-sensor" lab MUST first amend this spec; it is
  currently single-sensor by design.
- A future "sensor upgrade" verb MUST be additive:
  `aella_cli lab sensor upgrade` → calls a new L2 helper that
  re-downloads + re-deploys without touching unrelated VMs.
- A future sensor health probe (richer than ping) MUST be
  optional and gated behind a flag; it MUST NOT block deploy.

## 11. Forbidden Implementation Patterns

- Implementing the sensor's onboarding logic inside the
  appliance, in either L1 or L2 (constitution P-2 and
  M-13).
- Passing SPAN/mirror flags to the sensor deploy script (this
  spec §6).
- Hard-coding sensor parameters anywhere except
  `lab-vms.json::vms.sensor-vm` and
  `lab-vms.json::network` (M-11 keeps the subnet declarative).
- Auto-recreating `br0` when the sensor's `bridge` field cannot
  be resolved (constitution P-11).
- Letting the sensor deploy run from outside the sensor cache
  dir (the script expects to find sibling assets relative to its
  own `cwd`).

## 12. Validation Philosophy

A sensor-deployment change is valid only if:

1. `aella_cli lab deploy sensor-vm` is end-to-end idempotent:
   re-run produces a `deploy_sensor_vm_exec` log and the existing
   domain remains.
2. `aella_cli lab deploy sensor-vm --nodownload` does NOT touch
   the sensor cache dir and still produces the domain or
   reconciles autostart.
3. The sensor's NIC is bridged to `br0` and the sensor reaches
   `10.10.10.10` after boot (verified by the post-deploy ping
   WARN/INFO transition).
4. The sensor deploy script command line contains, in order:
   optional `--nodownload`, `--bridge br0`, `--ip 10.10.10.10`,
   `--netmask 255.255.255.0`, `--gw 10.10.10.1`,
   `--dns 10.10.10.1`, `--hostname sensor-vm` — and nothing
   else.
5. No SPAN flag is ever present.
