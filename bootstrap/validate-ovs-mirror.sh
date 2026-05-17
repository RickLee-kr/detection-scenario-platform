#!/usr/bin/env bash
# Validate OVS mirror telemetry path (br0 → sensor VM tap).
# Read-only — does not mutate host state.
#
# Usage:
#   ./bootstrap/validate-ovs-mirror.sh [--json]
#
# Exit codes:
#   0   all checks passed
#   10  br0 / OVS bridge missing
#   20  ovs-vsctl unavailable or failed
#   30  sensor VM not running
#   31  sensor vnet not resolved
#   40  mirror missing
#   41  mirror output-port mismatch
#   42  mirror select_all not enabled
#   50  multiple failures
#   77  root-only probes skipped (privilege constraints; not a runtime failure)
#
set -euo pipefail

REQUIRE_ROOT=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_runtime-validation-lib.sh
. "${SCRIPT_DIR}/_runtime-validation-lib.sh"

: "${XDR_LAB_MIRROR_NAME:=mirror-to-sensor}"

JSON_MODE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) JSON_MODE=1 ;;
    -h|--help)
      sed -n '1,22p' "$0" | tail -n +2
      exit 0
      ;;
    *) rv_log ERROR "unknown argument: $1"; exit 2 ;;
  esac
  shift
done

declare -a RESULTS=()
declare -a FAIL_CODES=()
OVERALL_RC=0
PRIVILEGE_SKIP=0

rv_reexec_as_root_if_needed "$@" || true

record() {
  local id="$1" ok="$2" detail="$3" code="$4"
  if [[ "${ok}" == "1" ]]; then
    RESULTS+=("$(rv_check_pass "${id}" "${detail}")")
  else
    RESULTS+=("$(rv_check_fail "${id}" "${detail}")")
    FAIL_CODES+=("${code}")
  fi
}

record_skip() {
  local id="$1" detail="$2"
  RESULTS+=("$(rv_check_skip "${id}" "${detail}")")
  PRIVILEGE_SKIP=1
}

SENSOR_VM="$(rv_resolve_sensor_vm)"
rv_log INFO "validate-ovs-mirror start sensor_vm=${SENSOR_VM} bridge=${LAB_BRIDGE} mirror=${XDR_LAB_MIRROR_NAME}"

# br0 / OVS bridge exists
rv_probe_begin br0_exists
br0_ok=0
br0_detail="OVS bridge ${LAB_BRIDGE} missing"
br0_out=""
br0_rc=0
if ! command -v ovs-vsctl &>/dev/null; then
  br0_detail="ovs-vsctl not in PATH"
else
  set +e
  br0_out="$(rv_run_with_timeout "${XDR_LAB_OVS_VSCTL_TIMEOUT_SECS}" \
    "ovs-vsctl br-exists ${LAB_BRIDGE}" \
    ovs-vsctl br-exists "${LAB_BRIDGE}" 2>&1)"
  br0_rc=$?
  set -e
  if [[ "${br0_rc}" -eq 0 ]]; then
    br0_ok=1
    br0_detail="OVS bridge ${LAB_BRIDGE} present"
  elif [[ "${br0_rc}" -eq 124 ]]; then
    br0_detail="ovs-vsctl timed out (${XDR_LAB_OVS_VSCTL_TIMEOUT_SECS}s)"
  elif rv_text_is_ovs_permission_denied "${br0_out}"; then
    br0_detail="requires root privileges (ovs-vsctl)"
    record_skip br0_exists "${br0_detail}"
    br0_ok=-1
  fi
fi
if [[ "${br0_ok}" -ne -1 ]]; then
  rv_probe_end br0_exists "${br0_ok}"
  record br0_exists "${br0_ok}" "${br0_detail}" 10
else
  rv_probe_end br0_exists 0
fi

# sensor VM running
rv_probe_begin sensor_vm_running
sensor_run_ok=0
sensor_run_detail="sensor VM ${SENSOR_VM} not running"
sensor_state=""
sensor_out=""
sensor_rc=0
set +e
sensor_out="$(rv_virsh_system domstate "${SENSOR_VM}" 2>&1)"
sensor_rc=$?
set -e
sensor_state="$(printf '%s' "${sensor_out}" | tr -d '\r' | awk 'END{print $0}')"
if [[ "${sensor_rc}" -eq 0 && "${sensor_state}" == "running" ]]; then
  sensor_run_ok=1
  sensor_run_detail="${SENSOR_VM} domstate=running"
elif rv_text_is_virsh_permission_denied "${sensor_out}"; then
  sensor_run_detail="requires root privileges (virsh)"
  record_skip sensor_vm_running "${sensor_run_detail}"
  sensor_run_ok=-1
elif [[ "${sensor_rc}" -eq 124 ]]; then
  sensor_run_detail="virsh domstate timed out (${XDR_LAB_VIRSH_TIMEOUT_SECS}s)"
else
  if [[ -z "${sensor_state}" ]]; then
    sensor_run_detail="${SENSOR_VM} not defined or virsh domstate failed"
  else
    sensor_run_detail="${SENSOR_VM} domstate=${sensor_state}"
  fi
fi
if [[ "${sensor_run_ok}" -ne -1 ]]; then
  rv_probe_end sensor_vm_running "${sensor_run_ok}"
  record sensor_vm_running "${sensor_run_ok}" "${sensor_run_detail}" 30
else
  rv_probe_end sensor_vm_running 0
fi

# sensor vnet resolved
rv_probe_begin sensor_vnet
sensor_vnet_ok=0
sensor_vnet_detail="sensor vnet not resolved on ${LAB_BRIDGE}"
sensor_iface=""
sensor_vnet_out=""
sensor_vnet_rc=0
if [[ "${sensor_run_ok}" -eq 1 ]]; then
  set +e
  sensor_vnet_out="$(rv_sensor_vnet_on_bridge "${SENSOR_VM}" "${LAB_BRIDGE}" 2>&1)"
  sensor_vnet_rc=$?
  set -e
  if [[ "${sensor_vnet_rc}" -eq 0 && -n "${sensor_vnet_out}" ]]; then
    sensor_iface="${sensor_vnet_out}"
    sensor_vnet_ok=1
    sensor_vnet_detail="sensor iface=${sensor_iface} on ${LAB_BRIDGE}"
  elif rv_text_is_virsh_permission_denied "${sensor_vnet_out}" \
      || rv_text_is_ovs_permission_denied "${sensor_vnet_out}"; then
    sensor_vnet_detail="requires root privileges (virsh / ovs-vsctl)"
    record_skip sensor_vnet "${sensor_vnet_detail}"
    sensor_vnet_ok=-1
  elif [[ "${sensor_vnet_rc}" -eq 124 ]]; then
    sensor_vnet_detail="sensor vnet probe timed out"
  elif [[ -n "${sensor_vnet_out}" ]]; then
    sensor_vnet_detail="${sensor_vnet_out}"
  else
    sensor_vnet_detail="No libvirt vnet interface found for ${SENSOR_VM}"
  fi
  if [[ "${sensor_vnet_ok}" -ne -1 ]]; then
    rv_probe_end sensor_vnet "${sensor_vnet_ok}"
    record sensor_vnet "${sensor_vnet_ok}" "${sensor_vnet_detail}" 31
  else
    rv_probe_end sensor_vnet 0
  fi
else
  sensor_vnet_detail="skipped — sensor VM not running"
  rv_probe_end sensor_vnet 0
  record_skip sensor_vnet "${sensor_vnet_detail}"
fi

SENSOR_CHECKS_USABLE=0
if [[ "${sensor_run_ok}" -eq 1 && "${sensor_vnet_ok}" -eq 1 ]]; then
  SENSOR_CHECKS_USABLE=1
fi

# mirror exists / output-port / select_all
rv_probe_begin mirror_exists
mirror_ok=0
mirror_detail="mirror ${XDR_LAB_MIRROR_NAME} missing on ${LAB_BRIDGE}"
output_ok=0
output_detail="skipped — mirror missing"
select_ok=0
select_detail="skipped — mirror missing"
mirror_uuid=""
output_name=""
ovs_vsctl_out=""
ovs_vsctl_rc=0

if [[ "${br0_ok}" -eq -1 ]]; then
  mirror_detail="requires root privileges (ovs-vsctl)"
  output_detail="requires root privileges (ovs-vsctl)"
  select_detail="requires root privileges (ovs-vsctl)"
  record_skip mirror_exists "${mirror_detail}"
  record_skip mirror_output_port "${output_detail}"
  record_skip mirror_select_all "${select_detail}"
  rv_probe_end mirror_exists 0
  rv_probe_end mirror_output_port 0
  rv_probe_end mirror_select_all 0
elif [[ "${SENSOR_CHECKS_USABLE}" -eq 0 ]]; then
  mirror_detail="skipped — sensor VM/vnet unavailable"
  output_detail="skipped — sensor VM/vnet unavailable"
  select_detail="skipped — sensor VM/vnet unavailable"
  rv_probe_end mirror_exists 0
  record_skip mirror_exists "${mirror_detail}"
  rv_probe_end mirror_output_port 0
  record_skip mirror_output_port "${output_detail}"
  rv_probe_end mirror_select_all 0
  record_skip mirror_select_all "${select_detail}"
else
  set +e
  ovs_vsctl_out="$(rv_ovs_vsctl_show)"
  ovs_vsctl_rc=$?
  set -e
  if [[ "${ovs_vsctl_rc}" -eq 124 ]]; then
    mirror_detail="ovs-vsctl timed out (${XDR_LAB_OVS_VSCTL_TIMEOUT_SECS}s)"
    output_detail="skipped — ovs-vsctl timed out"
    select_detail="skipped — ovs-vsctl timed out"
    rv_probe_end mirror_exists 0
    record mirror_exists 0 "${mirror_detail}" 20
    rv_probe_end mirror_output_port 0
    record mirror_output_port 0 "${output_detail}" 20
    rv_probe_end mirror_select_all 0
    record mirror_select_all 0 "${select_detail}" 20
  elif [[ "${ovs_vsctl_rc}" -ne 0 ]]; then
    if rv_text_is_ovs_permission_denied "${ovs_vsctl_out}"; then
      mirror_detail="requires root privileges (ovs-vsctl)"
      output_detail="requires root privileges (ovs-vsctl)"
      select_detail="requires root privileges (ovs-vsctl)"
      record_skip mirror_exists "${mirror_detail}"
      record_skip mirror_output_port "${output_detail}"
      record_skip mirror_select_all "${select_detail}"
      rv_probe_end mirror_exists 0
      rv_probe_end mirror_output_port 0
      rv_probe_end mirror_select_all 0
    else
      mirror_detail="ovs-vsctl runtime error: ${ovs_vsctl_out}"
      output_detail="skipped — ovs-vsctl failed"
      select_detail="skipped — ovs-vsctl failed"
      rv_probe_end mirror_exists 0
      record mirror_exists 0 "${mirror_detail}" 20
      rv_probe_end mirror_output_port 0
      record mirror_output_port 0 "${output_detail}" 20
      rv_probe_end mirror_select_all 0
      record mirror_select_all 0 "${select_detail}" 20
    fi
  elif [[ "${br0_ok}" -eq 0 ]]; then
    mirror_detail="skipped — ${LAB_BRIDGE} missing"
    output_detail="skipped — ${LAB_BRIDGE} missing"
    select_detail="skipped — ${LAB_BRIDGE} missing"
    rv_probe_end mirror_exists 0
    record mirror_exists 0 "${mirror_detail}" 10
    rv_probe_end mirror_output_port 0
    record mirror_output_port 0 "${output_detail}" 10
    rv_probe_end mirror_select_all 0
    record mirror_select_all 0 "${select_detail}" 10
  else
    mirror_uuid="$(rv_ovs_mirror_uuid_by_name "${XDR_LAB_MIRROR_NAME}" || true)"
    if [[ -n "${mirror_uuid}" ]] && rv_ovs_mirror_attached_to_bridge "${mirror_uuid}" "${LAB_BRIDGE}"; then
      mirror_ok=1
      mirror_detail="mirror ${XDR_LAB_MIRROR_NAME} present on ${LAB_BRIDGE}"
    fi
    rv_probe_end mirror_exists "${mirror_ok}"
    record mirror_exists "${mirror_ok}" "${mirror_detail}" 40

    if [[ "${mirror_ok}" -eq 1 ]]; then
      output_name="$(rv_ovs_mirror_output_port_name "${mirror_uuid}" || true)"
      if [[ -n "${output_name}" && -n "${sensor_iface}" && "${output_name}" == "${sensor_iface}" ]]; then
        output_ok=1
        output_detail="output-port=${output_name}"
      elif [[ -z "${sensor_iface}" ]]; then
        output_detail="cannot verify output-port — sensor vnet unknown"
      elif [[ -z "${output_name}" ]]; then
        output_detail="mirror output-port unresolved"
      else
        output_detail="output-port=${output_name:-unknown} expected ${sensor_iface}"
      fi
      rv_probe_end mirror_output_port "${output_ok}"
      record mirror_output_port "${output_ok}" "${output_detail}" 41

      if rv_ovs_mirror_select_all_enabled "${mirror_uuid}"; then
        select_ok=1
        select_detail="select_all=true"
      else
        select_detail="select_all is not true"
      fi
      rv_probe_end mirror_select_all "${select_ok}"
      record mirror_select_all "${select_ok}" "${select_detail}" 42
    else
      rv_probe_end mirror_output_port 0
      record_skip mirror_output_port "${output_detail}"
      rv_probe_end mirror_select_all 0
      record_skip mirror_select_all "${select_detail}"
    fi
  fi
fi

if [[ "${#FAIL_CODES[@]}" -gt 1 ]]; then
  OVERALL_RC=50
elif [[ "${#FAIL_CODES[@]}" -eq 1 ]]; then
  OVERALL_RC="${FAIL_CODES[0]}"
elif [[ "${PRIVILEGE_SKIP}" -eq 1 ]]; then
  OVERALL_RC="${RV_EXIT_PRIVILEGE_SKIP}"
else
  OVERALL_RC=0
fi

if [[ "${JSON_MODE}" -eq 1 ]]; then
  python3 - "${OVERALL_RC}" "${LAB_BRIDGE}" "${SENSOR_VM}" "${XDR_LAB_MIRROR_NAME}" <<'PY' "${RESULTS[@]}"
import json, sys
rc = int(sys.argv[1])
bridge, sensor_vm, mirror_name = sys.argv[2], sys.argv[3], sys.argv[4]
rows = sys.argv[5:]
checks = []
for row in rows:
    status, cid, detail = row.split("\t", 2)
    checks.append({
        "id": cid,
        "ok": status == "PASS",
        "skipped": status == "SKIP",
        "detail": detail,
    })
print(json.dumps({
    "script": "validate-ovs-mirror",
    "ok": rc == 0,
    "exit_code": rc,
    "bridge": bridge,
    "sensor_vm": sensor_vm,
    "mirror_name": mirror_name,
    "checks": checks,
}, indent=2, sort_keys=True))
PY
else
  echo "=== validate-ovs-mirror (${LAB_BRIDGE} → ${SENSOR_VM}) ==="
  for row in "${RESULTS[@]}"; do
    IFS=$'\t' read -r status id detail <<<"${row}"
    printf '[%s] %-22s %s\n' "${status}" "${id}" "${detail}"
  done
  echo "---"
  if [[ "${OVERALL_RC}" -eq "${RV_EXIT_PRIVILEGE_SKIP}" ]]; then
    echo "RESULT: SKIP (exit ${OVERALL_RC})"
  elif [[ "${OVERALL_RC}" -eq 0 ]]; then
    echo "RESULT: PASS (exit 0)"
  else
    echo "RESULT: FAIL (exit ${OVERALL_RC})"
  fi
fi

rv_log INFO "validate-ovs-mirror finished exit=${OVERALL_RC}"
exit "${OVERALL_RC}"
