#!/usr/bin/env bash
# Ensure the lab OVS port mirror on br0 targets the running sensor VM tap.
# Idempotent self-heal: removes only the named mirror object, then recreates if needed.
#
# Usage:
#   sudo ./bootstrap/ensure-ovs-mirror.sh [--dry-run]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_runtime-validation-lib.sh
. "${SCRIPT_DIR}/_runtime-validation-lib.sh"

: "${XDR_LAB_MIRROR_NAME:=mirror-to-sensor}"

DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      sed -n '1,12p' "$0" | tail -n +2
      exit 0
      ;;
    *) rv_log ERROR "unknown argument: $1"; exit 2 ;;
  esac
  shift
done

if [[ "${DRY_RUN}" -eq 0 && "$(id -u)" -ne 0 ]]; then
  rv_log ERROR "ensure-ovs-mirror requires root (sudo)"
  exit 2
fi

run_ovs() {
  local label="$1"
  shift
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    rv_log INFO "DRY-RUN would: ${label} — $*"
    return 0
  fi
  rv_run_with_timeout "${XDR_LAB_OVS_VSCTL_TIMEOUT_SECS}" "${label}" ovs-vsctl "$@"
}

run_action() {
  local desc="$1"
  shift
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    rv_log INFO "DRY-RUN would: ${desc} — $*"
    return 0
  fi
  rv_log INFO "ACTION: ${desc} — $*"
  "$@"
}

mirror_already_consistent() {
  local mirror_uuid output_name
  mirror_uuid="$(rv_ovs_mirror_uuid_by_name "${XDR_LAB_MIRROR_NAME}" || true)"
  [[ -n "${mirror_uuid}" ]] || return 1
  rv_ovs_mirror_attached_to_bridge "${mirror_uuid}" "${LAB_BRIDGE}" || return 1
  output_name="$(rv_ovs_mirror_output_port_name "${mirror_uuid}" || true)"
  [[ -n "${output_name}" && "${output_name}" == "${sensor_iface}" ]] || return 1
  rv_ovs_mirror_select_all_enabled "${mirror_uuid}"
}

remove_named_mirror() {
  local existing_uuid
  existing_uuid="$(rv_ovs_mirror_uuid_by_name "${XDR_LAB_MIRROR_NAME}" || true)"
  [[ -n "${existing_uuid}" ]] || return 0
  rv_log INFO "removing stale mirror name=${XDR_LAB_MIRROR_NAME} uuid=${existing_uuid}"
  run_ovs "remove mirror from ${LAB_BRIDGE}" \
    --if-exists remove bridge "${LAB_BRIDGE}" mirrors "${existing_uuid}"
  run_ovs "destroy mirror ${existing_uuid}" \
    --if-exists destroy mirror "${existing_uuid}"
}

create_mirror() {
  local sensor_iface="$1"
  run_ovs "create mirror ${XDR_LAB_MIRROR_NAME} output-port=${sensor_iface}" \
    -- --id=@out get port "${sensor_iface}" \
    -- --id=@m create mirror "name=${XDR_LAB_MIRROR_NAME}" select_all=true output-port=@out \
    -- set bridge "${LAB_BRIDGE}" mirrors=@m
}

SENSOR_VM="$(rv_resolve_sensor_vm)"
rv_log INFO "ensure-ovs-mirror start sensor_vm=${SENSOR_VM} bridge=${LAB_BRIDGE} mirror=${XDR_LAB_MIRROR_NAME}"

if ! command -v ovs-vsctl &>/dev/null; then
  rv_log ERROR "ovs-vsctl not in PATH"
  exit 20
fi
if ! command -v virsh &>/dev/null; then
  rv_log ERROR "virsh not in PATH"
  exit 21
fi

ovs_out=""
ovs_rc=0
ovs_out="$(rv_ovs_vsctl_show)" || ovs_rc=$?
if [[ "${ovs_rc}" -ne 0 ]]; then
  rv_log ERROR "ovs-vsctl show failed: ${ovs_out}"
  exit 20
fi

if ! rv_ovs_br_exists; then
  rv_log ERROR "OVS bridge ${LAB_BRIDGE} missing"
  exit 10
fi

dom_state="$(rv_virsh_system_domstate "${SENSOR_VM}")"
if [[ "${dom_state}" != "running" ]]; then
  rv_log ERROR "sensor VM not running vm=${SENSOR_VM} state=${dom_state:-unknown}"
  exit 30
fi

sensor_iface=""
sensor_rc=0
sensor_vnet_out=""
set +e
sensor_vnet_out="$(rv_sensor_vnet_on_bridge "${SENSOR_VM}" "${LAB_BRIDGE}" 2>&1)"
sensor_rc=$?
set -e
if [[ "${sensor_rc}" -eq 0 && -n "${sensor_vnet_out}" ]]; then
  sensor_iface="${sensor_vnet_out}"
else
  rv_log ERROR "${sensor_vnet_out:-No libvirt vnet interface found for ${SENSOR_VM}}"
  exit 31
fi
rv_log INFO "sensor vnet discovered vm=${SENSOR_VM} iface=${sensor_iface}"

if mirror_already_consistent; then
  rv_log INFO "ensure-ovs-mirror idempotent noop mirror=${XDR_LAB_MIRROR_NAME} iface=${sensor_iface}"
  exit 0
fi

remove_named_mirror
if [[ "${DRY_RUN}" -eq 1 ]]; then
  rv_log INFO "ensure-ovs-mirror dry-run would recreate mirror=${XDR_LAB_MIRROR_NAME} iface=${sensor_iface}"
  exit 0
fi
run_action "create OVS mirror ${XDR_LAB_MIRROR_NAME}" create_mirror "${sensor_iface}"

if ! mirror_already_consistent; then
  rv_log ERROR "post-apply mirror inconsistent mirror=${XDR_LAB_MIRROR_NAME} iface=${sensor_iface}"
  exit 40
fi

rv_log INFO "ensure-ovs-mirror success sensor_vm=${SENSOR_VM} iface=${sensor_iface} mirror=${XDR_LAB_MIRROR_NAME}"
exit 0
