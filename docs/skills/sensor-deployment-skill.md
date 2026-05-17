# Skill — Sensor Deployment

Operational memory for any task that touches sensor VM deployment.
Governed by spec 004. Read before changing the sensor branch in
`xdr-lab-vm-manager.sh::deploy_sensor_vm`, the sensor entry in
`lab-vms.json`, or anything that downloads the sensor assets.

## Hard rules

- The sensor is a **special deploy type**, identified by
  `name == "sensor-vm" || type == "sensor"` (M-12).
- The sensor deploy script `virt_deploy_modular_ds.sh` is **owned
  upstream** and MUST NOT be re-implemented inside the appliance
  (M-13, constitution P-2).
- The sensor is deployed by invoking the upstream script from
  its cache dir `/opt/xdr-lab/images/sensor/`:
  `cd "$sensor_cache_dir" && bash "./${script_name}" "${args[@]}"`.
- The sensor is the **only** consumer of
  `/opt/xdr-lab/images/sensor/`.
- The sensor's networking values are read from `lab-vms.json`:
  `bridge=br0` (M-10), `internal_ip=10.10.10.10`,
  `netmask`/`gateway`/`dns` from `lab-vms.json::network`,
  `hostname` from `lab-vms.json::vms.sensor-vm.hostname`.

## Mandatory argument vector

```text
[--nodownload]
--bridge "$bridge"
--ip "$internal_ip"
--netmask "$netmask"
--gw "$gateway"
--dns "$dns"
--hostname "$hostname"
```

Exactly these flags, in this order. No SPAN flags. No extra flags.

## No-SPAN policy

The sensor deploy path MUST NOT pass SPAN-mode flags (spec 004
§6). Mirror configuration is a separate, non-destructive operation
governed by spec 007. Coupling SPAN to sensor deploy makes mirror
recovery require a sensor redeploy, which is unacceptable.

## Download / cache invariants

`download_vm_image sensor-vm` (spec 003 §3.1) MUST place:

- `${sensor_cache_dir}/${virt_deploy_script_name}` (chmod a+x).
- `${sensor_cache_dir}/$(basename "$image_url")`.

`deploy_sensor_vm` requires both to exist; missing the script →
`die "Sensor deploy script missing: … (run download first)"`.

Placeholder URLs (`REPLACE_ME.example.invalid`, `REPLACE_ME`, or other
placeholder markers) are configuration errors. Download paths MUST stop with
`CONFIG_PLACEHOLDER_ERROR` instead of attempting network access.

When upstream Stellar Sensor artifacts are absent, report the mode explicitly:

- `sensor_type=generic_linux`
- `stellar_sensor_artifact_found=false`
- `stellar_sensor_ready=false`

The required upstream artifacts are:

```text
/opt/xdr-lab/images/sensor/virt_deploy_modular_ds.sh
/opt/xdr-lab/images/sensor/sensor-base.qcow2
```

Operator remediation:

```bash
sudo install -D -m 0755 <artifact>/virt_deploy_modular_ds.sh /opt/xdr-lab/images/sensor/virt_deploy_modular_ds.sh
sudo install -D -m 0644 <artifact>/sensor-base.qcow2 /opt/xdr-lab/images/sensor/sensor-base.qcow2
```

## Post-deploy validation

`validate_sensor_deployment` is observability, not gating:

- `virsh dominfo sensor-vm` succeeds → `validate_sensor_deployment
  virsh_ok`.
- `virsh dominfo` fails → `validate_sensor_deployment virsh_missing`
  (WARN, soft failure — the upstream script might use a different
  domain name).
- `ping -c1 -W2 10.10.10.10` succeeds → `validate_sensor_deployment
  ping_ok`.
- Ping fails → `validate_sensor_deployment_ping_failed` (WARN, the
  sensor may still be booting).

## Sensor uniqueness

- Exactly one VM of `type == "sensor"` in `lab-vms.json`.
- The reserved key `sensor-vm` is load-bearing across specs 002,
  003, 004, 007; do not rename it.

## When you would otherwise be tempted to…

- **…inline `virt-install` into the sensor path:** stop. The
  upstream script owns the libvirt-define step (M-13).
- **…pass `--span ...` "because the sensor needs to see traffic":**
  stop. Mirror configuration is spec 007's job.
- **…hard-code `10.10.10.10` outside `lab-vms.json`:** stop. It's
  declared once.
- **…re-download the sensor script during `deploy` when
  `--nodownload` is set:** stop. `--nodownload` MUST use the
  cache as-is.

## Recovery patterns

- **Bad cache →** `aella_cli lab download sensor-vm`, then
  `aella_cli lab deploy sensor-vm`.
- **Half-deployed →** `aella_cli lab destroy sensor-vm`, then
  redeploy.
- **Sensor IP change →** edit `internal_ip` in `lab-vms.json`,
  destroy + redeploy. Also update reverse-NAT mappings (spec
  010).

## Related specs and skills

- Spec 002 (KVM runtime), spec 003 (image policy), spec 004
  (primary), spec 006 (network), spec 010 (reverse NAT — sensor
  exposes ssh/https/ui externally).
- Companion skills: `kvm-runtime-skill.md`,
  `ovs-mirror-skill.md`, `reverse-nat-skill.md`,
  `appliance-cli-skill.md`.
