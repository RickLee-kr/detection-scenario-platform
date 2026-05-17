#!/usr/bin/env bash
# Validate sensor-vm identity and whether real Stellar Sensor artifacts are present.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_runtime-validation-lib.sh
. "${SCRIPT_DIR}/_runtime-validation-lib.sh"

cfg="${XDR_LAB_VMS_JSON:-${XDR_ROOT}/config/lab-vms.json}"
sensor="${XDR_LAB_SENSOR_VM:-sensor-vm}"

fail() {
  rv_check_fail sensor_identity "$1"
  exit 42
}

pass() {
  rv_check_pass sensor_identity "$1"
  exit 0
}

[[ -f "${cfg}" ]] || fail "lab-vms.json missing: ${cfg}"

if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 missing"
fi

read -r declared_type cache_dir script_name image_url qcow2_name < <(python3 - "${cfg}" "${sensor}" <<'PY'
import json, sys
path, sensor = sys.argv[1:3]
with open(path, encoding="utf-8") as fh:
    cfg = json.load(fh)
vm = (cfg.get("vms") or {}).get(sensor) or {}
print(
    vm.get("type", ""),
    vm.get("sensor_cache_dir", ""),
    vm.get("virt_deploy_script_name", ""),
    vm.get("image_url", ""),
    vm.get("qcow2_name", ""),
)
PY
)

resolved_cache="${cache_dir}"
if [[ -n "${resolved_cache}" && "${resolved_cache}" != /* ]]; then
  resolved_cache="${XDR_ROOT}/${resolved_cache}"
fi

script_path="${resolved_cache}/${script_name}"
image_name="${qcow2_name:-$(basename "${image_url:-aella-modular-ds.qcow2}")}"
image_path="${resolved_cache}/${image_name}"
if [[ "${image_name}" == *.zst ]]; then
  image_path="${image_path%.zst}"
fi

script_ok=0
image_ok=0
[[ -n "${script_name}" && -x "${script_path}" ]] && script_ok=1
[[ -f "${image_path}" ]] && image_ok=1

stellar_sensor_artifact_found=false
if [[ "${script_ok}" -eq 1 && "${image_ok}" -eq 1 ]]; then
  stellar_sensor_artifact_found=true
fi
stellar_sensor_ready="${stellar_sensor_artifact_found}"

runtime_looks_generic=0
if command -v virsh >/dev/null 2>&1 && virsh dominfo "${sensor}" >/dev/null 2>&1; then
  xml="$(virsh dumpxml "${sensor}" 2>/dev/null || true)"
  if grep -Eiq 'ubuntu|cloud|ubuntu-[0-9].*cloud|cloud\.img' <<<"${xml}"; then
    runtime_looks_generic=1
  fi
  state="$(virsh domstate "${sensor}" 2>/dev/null | tr -d '\r' || true)"
else
  state=""
fi

sensor_type="stellar_sensor"

detail="sensor_type=${sensor_type} stellar_sensor_artifact_found=${stellar_sensor_artifact_found} stellar_sensor_ready=${stellar_sensor_ready}"

if [[ "${declared_type}" != "sensor" ]]; then
  fail "${detail} sensor-vm declared type must be sensor, got ${declared_type:-missing}"
fi

if [[ "${runtime_looks_generic}" -eq 1 ]]; then
  fail "${detail} deprecated Ubuntu cloud-image runtime detected for sensor-vm; deploy Stellar Cyber Modular Data Sensor artifacts"
fi

if [[ -n "${state}" && "${state}" != "running" ]]; then
  fail "${detail} sensor domain defined but not running: ${state:-unknown}"
fi

if [[ "${stellar_sensor_artifact_found}" != "true" ]]; then
  cat <<EOF
Missing required Stellar Sensor artifacts:
  ${script_path}
  ${image_path}
Remediation:
  sudo install -D -m 0755 <artifact>/virt_deploy_modular_ds.sh ${script_path}
  sudo install -D -m 0644 <artifact>/aella-modular-ds-<version>.qcow2 ${image_path}
EOF
  fail "${detail} Missing required Stellar Sensor artifacts: ${script_path}; ${image_path}"
fi

pass "${detail} sensor-vm declared type=${declared_type:-missing} and Stellar artifacts are present"
