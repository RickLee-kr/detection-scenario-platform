#!/usr/bin/env bash
# XDR Lab — Operational Runtime Console (non-destructive validation + safe self-healing).
# This is NOT an infrastructure installer. Golden Image bootstrap owns OVS/libvirt/NAT install.
#
# Usage:
#   ./xdr-lab.sh                          # interactive menu
#   ./xdr-lab.sh host-validate-network
#   ./xdr-lab.sh host-validate-libvirt
#   ./xdr-lab.sh host-validate-caldera
#   ./xdr-lab.sh host-validate-ovs-mirror
#   ./xdr-lab.sh host-validate-appliance
#   ./xdr-lab.sh host-apply-ovs-mirror [--dry-run]
#   ./xdr-lab.sh host-show-vms
#   ./xdr-lab.sh host-access-info
#   ./xdr-lab.sh host-fix-runtime [--dry-run]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/config/paths.sh" ]]; then
  # shellcheck source=config/paths.sh
  . "${SCRIPT_DIR}/config/paths.sh"
fi

: "${XDR_ROOT:=${XDR_BASE:-/opt/xdr-lab}}"
BOOTSTRAP_DIR="${XDR_ROOT}/bootstrap"
if [[ ! -d "${BOOTSTRAP_DIR}" ]]; then
  BOOTSTRAP_DIR="${SCRIPT_DIR}/bootstrap"
fi

if [[ -f "${BOOTSTRAP_DIR}/_runtime-validation-lib.sh" ]]; then
  # shellcheck source=bootstrap/_runtime-validation-lib.sh
  . "${BOOTSTRAP_DIR}/_runtime-validation-lib.sh"
fi

: "${XDR_LAB_VIRSH_TIMEOUT_SECS:=15}"
: "${XDR_LAB_SENSOR_VM:=sensor-vm}"
: "${XDR_LAB_LINUX_VM:=victim-linux}"

run_validate_network() {
  bash "${BOOTSTRAP_DIR}/validate-host-network.sh" "$@"
}

run_validate_libvirt() {
  bash "${BOOTSTRAP_DIR}/validate-libvirt.sh" "$@"
}

run_validate_caldera() {
  bash "${BOOTSTRAP_DIR}/validate-caldera.sh" "$@"
}

run_validate_ovs_mirror() {
  bash "${BOOTSTRAP_DIR}/validate-ovs-mirror.sh" "$@"
}

run_validate_appliance() {
  bash "${BOOTSTRAP_DIR}/validate-appliance.sh" --strict "$@"
}

run_apply_ovs_mirror() {
  if [[ "$(id -u)" -ne 0 ]]; then
    sudo bash "${BOOTSTRAP_DIR}/ensure-ovs-mirror.sh" "$@"
  else
    bash "${BOOTSTRAP_DIR}/ensure-ovs-mirror.sh" "$@"
  fi
}

run_fix_runtime() {
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "Runtime self-healing requires root. Re-run: sudo $0 host-fix-runtime $*" >&2
    exit 2
  fi
  bash "${BOOTSTRAP_DIR}/fix-runtime-state.sh" "$@"
}

xdr_run_with_timeout() {
  local secs="$1" label="$2" rc
  shift 2
  if declare -F rv_run_with_timeout &>/dev/null; then
    rv_run_with_timeout "${secs}" "${label}" "$@"
    return $?
  fi
  if command -v timeout &>/dev/null; then
    timeout --foreground "${secs}" "$@"
    rc=$?
    [[ "${rc}" -eq 124 ]] && echo "timeout (${secs}s): ${label}" >&2
    return "${rc}"
  fi
  "$@"
}

xdr_virsh_domstate() {
  local vm="$1" out rc state
  set +e
  if declare -F rv_virsh_system &>/dev/null; then
    out="$(rv_virsh_system domstate "${vm}" 2>&1)"
    rc=$?
  else
    out="$(xdr_run_with_timeout "${XDR_LAB_VIRSH_TIMEOUT_SECS}" \
      "virsh domstate ${vm}" \
      virsh -c qemu:///system domstate "${vm}" 2>&1)"
    rc=$?
  fi
  set -e
  state="$(printf '%s' "${out}" | tr -d '\r' | awk 'END{print $0}')"
  if [[ "${rc}" -eq 0 && -n "${state}" ]]; then
    echo "${state}"
    return 0
  fi
  if [[ "${rc}" -eq 124 ]]; then
    echo "timed out"
    return 124
  fi
  if declare -F rv_text_is_virsh_permission_denied &>/dev/null \
      && rv_text_is_virsh_permission_denied "${out}"; then
    echo "permission denied"
    return 77
  fi
  if grep -qiE 'failed to get domain|no domain with matching name|domain not found' <<<"${out}"; then
    echo "not defined"
    return 1
  fi
  if [[ -z "${state}" ]]; then
    echo "unknown"
    return 1
  fi
  echo "${state}"
  return "${rc}"
}

resolve_host_ip() {
  local ip dev
  if command -v hostname &>/dev/null; then
    for ip in $(hostname -I 2>/dev/null); do
      [[ -n "${ip}" && "${ip}" != "127.0.0.1" ]] || continue
      echo "${ip}"
      return 0
    done
  fi
  dev="$(ip -4 route show default 2>/dev/null | awk '{
    for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit }
  }')"
  if [[ -n "${dev}" ]]; then
    ip="$(ip -4 addr show dev "${dev}" 2>/dev/null \
      | awk '/inet / { sub(/\/.*/, "", $2); print $2; exit }')"
    if [[ -n "${ip}" && "${ip}" != "127.0.0.1" ]]; then
      echo "${ip}"
      return 0
    fi
  fi
  dev="$(ip -4 route get 203.0.113.1 2>/dev/null | awk '{
    for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit }
  }')"
  if [[ -n "${dev}" ]]; then
    ip="$(ip -4 addr show dev "${dev}" 2>/dev/null \
      | awk '/inet / { sub(/\/.*/, "", $2); print $2; exit }')"
    if [[ -n "${ip}" && "${ip}" != "127.0.0.1" ]]; then
      echo "${ip}"
      return 0
    fi
  fi
  echo "127.0.0.1"
  return 1
}

run_show_vm_status() {
  local -a vms=(
    "${XDR_LAB_SENSOR_VM}"
    "${XDR_LAB_LINUX_VM}"
    "windows-victim"
  )
  local vm state list_rc=0 list_out=""

  echo "=== VM Runtime Status ==="
  echo

  if ! command -v virsh &>/dev/null; then
    echo "virsh not available — cannot query VM state." >&2
    return 1
  fi

  set +e
  if declare -F rv_virsh_system &>/dev/null; then
    list_out="$(rv_virsh_system list --all 2>&1)"
    list_rc=$?
  else
    list_out="$(xdr_run_with_timeout "${XDR_LAB_VIRSH_TIMEOUT_SECS}" \
      "virsh list --all" \
      virsh -c qemu:///system list --all 2>&1)"
    list_rc=$?
  fi
  set -e

  if [[ "${list_rc}" -eq 0 ]]; then
    printf '%s\n' "${list_out}"
    echo
  elif [[ "${list_rc}" -eq 124 ]]; then
    echo "(virsh list --all timed out after ${XDR_LAB_VIRSH_TIMEOUT_SECS}s)" >&2
    echo
  elif declare -F rv_text_is_virsh_permission_denied &>/dev/null \
      && rv_text_is_virsh_permission_denied "${list_out}"; then
    echo "(virsh list --all: permission denied — try sudo or libvirt group)" >&2
    echo
  else
    echo "(virsh list --all failed: ${list_out})" >&2
    echo
  fi

  for vm in "${vms[@]}"; do
    set +e
    state="$(xdr_virsh_domstate "${vm}")"
  set -e
    printf '%-16s %s\n' "${vm}" "${state}"
  done
}

run_show_access_info() {
  local host_ip ssh_user
  host_ip="$(resolve_host_ip)" || true
  ssh_user="${SUDO_USER:-${USER:-lab}}"

  echo "=== Access Information ==="
  echo
  if [[ "${host_ip}" == "127.0.0.1" ]]; then
    echo "Host IP: ${host_ip} (no routable address detected — use localhost or set LAB access manually)"
  else
    echo "Host IP: ${host_ip}"
  fi
  echo
  echo "Sensor SSH:"
  echo "  ssh -p 1022 lab@${host_ip}"
  echo
  echo "Linux SSH:"
  echo "  ssh -p 2022 lab@${host_ip}"
  echo
  echo "Windows RDP:"
  echo "  ${host_ip}:3389"
  echo
  echo "Windows VNC:"
  echo "  ssh -L 5900:127.0.0.1:5900 ${ssh_user}@${host_ip}"
}

show_menu() {
  cat <<'MENU'

XDR Lab — Operational Runtime Console
=====================================

Infrastructure Validation
-------------------------
 1) Validate Host Network
 2) Validate libvirt Runtime
 3) Validate CALDERA Runtime
 4) Validate OVS Mirror
 5) Validate Full Appliance (--strict)

Operational Actions
-------------------
 6) Apply / Repair OVS Mirror
 7) Show VM Status
 8) Show Access Information

Runtime Recovery
----------------
 9) Attempt Runtime Self-Healing

 q) Quit

MENU
}

interactive_loop() {
  local choice
  while true; do
    show_menu
    read -r -p "Select [1-9/q]: " choice
    case "${choice}" in
      1) run_validate_network || true; echo ;;
      2) run_validate_libvirt || true; echo ;;
      3) run_validate_caldera || true; echo ;;
      4) run_validate_ovs_mirror || true; echo ;;
      5) run_validate_appliance || true; echo ;;
      6) run_apply_ovs_mirror || true; echo ;;
      7) run_show_vm_status || true; echo ;;
      8) run_show_access_info || true; echo ;;
      9)
        if [[ "$(id -u)" -ne 0 ]]; then
          echo "Self-healing requires sudo. Running: sudo ${BOOTSTRAP_DIR}/fix-runtime-state.sh" >&2
          sudo bash "${BOOTSTRAP_DIR}/fix-runtime-state.sh" || true
        else
          run_fix_runtime || true
        fi
        echo
        ;;
      q|Q) exit 0 ;;
      *) echo "Invalid choice." ;;
    esac
  done
}

case "${1:-}" in
  ""|-h|--help)
    sed -n '1,18p' "$0" | tail -n +2
    echo
    interactive_loop
    ;;
  host-validate-network) shift; run_validate_network "$@" ;;
  host-validate-libvirt) shift; run_validate_libvirt "$@" ;;
  host-validate-caldera) shift; run_validate_caldera "$@" ;;
  host-validate-ovs-mirror) shift; run_validate_ovs_mirror "$@" ;;
  host-validate-appliance) shift; run_validate_appliance "$@" ;;
  host-apply-ovs-mirror) shift; run_apply_ovs_mirror "$@" ;;
  host-show-vms) shift; run_show_vm_status "$@" ;;
  host-access-info) shift; run_show_access_info "$@" ;;
  host-fix-runtime) shift; run_fix_runtime "$@" ;;
  *)
    echo "Unknown command: $1" >&2
    echo "Try: $0 --help" >&2
    exit 2
    ;;
esac
