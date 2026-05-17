#!/usr/bin/env bash
# Golden Image persistence (systemd oneshot): restore br0 + ovs-net + NAT contract
# after reboot without operator manual ip commands.
#
# Chosen persistence model: systemd oneshot after openvswitch-switch.service
# (see installer/xdr-lab-host-network.service).
#
# Usage:
#   sudo ./bootstrap/ensure-host-network.sh [--dry-run]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_runtime-validation-lib.sh
. "${SCRIPT_DIR}/_runtime-validation-lib.sh"

DRY_RUN=0
OVS_WAIT_SECS="${XDR_LAB_OVS_WAIT_SECS:-90}"
BRIDGE_RETRY_SECS="${XDR_LAB_BRIDGE_RETRY_SECS:-90}"
NAT_CONTRACT_TIMEOUT_SECS="${XDR_LAB_NAT_CONTRACT_TIMEOUT_SECS:-120}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      sed -n '1,14p' "$0" | tail -n +2
      exit 0
      ;;
    *) rv_log ERROR "unknown argument: $1"; exit 2 ;;
  esac
  shift
done

if [[ "${DRY_RUN}" -eq 0 && "$(id -u)" -ne 0 ]]; then
  rv_log ERROR "ensure-host-network requires root (sudo)"
  exit 2
fi

run_fix() {
  local desc="$1" rc
  shift
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    rv_log INFO "DRY-RUN would: ${desc} — $*"
    return 0
  fi
  rv_log INFO "ACTION: ${desc} — $*"
  set +e
  "$@"
  rc=$?
  set -e
  return "${rc}"
}

wait_for_bridge() {
  local deadline=$((SECONDS + OVS_WAIT_SECS))
  while ! rv_iface_exists; do
    if (( SECONDS >= deadline )); then
      rv_log ERROR "timeout waiting for ${LAB_BRIDGE} (${OVS_WAIT_SECS}s)"
      return 1
    fi
    sleep 1
  done
  return 0
}

restore_bridge_runtime() {
  local deadline attempt
  deadline=$((SECONDS + BRIDGE_RETRY_SECS))
  attempt=0
  while (( SECONDS < deadline )); do
    attempt=$((attempt + 1))
    if ! rv_iface_oper_up; then
      run_fix "bring ${LAB_BRIDGE} up (attempt ${attempt})" \
        ip link set "${LAB_BRIDGE}" up || true
    fi
    if ! rv_iface_has_gateway_ip; then
      run_fix "assign ${LAB_GATEWAY}/24 on ${LAB_BRIDGE} (attempt ${attempt})" \
        ip addr add "${LAB_GATEWAY}/24" dev "${LAB_BRIDGE}" || true
    fi
    if rv_iface_oper_up && rv_iface_has_gateway_ip; then
      rv_log INFO "${LAB_BRIDGE} runtime restored (attempt ${attempt})"
      return 0
    fi
    sleep 2
  done
  rv_log ERROR "timeout restoring ${LAB_BRIDGE} UP + ${LAB_GATEWAY}/24 (${BRIDGE_RETRY_SECS}s)"
  return 1
}

restore_nat_contract() {
  local ensure_nat rc
  # paths.sh exports SCRIPT_DIR (repo scripts/); use bootstrap resolver instead.
  ensure_nat="$(rv_script_path ensure-nat-contract.sh || true)"
  [[ -n "${ensure_nat}" && -x "${ensure_nat}" ]] || {
    rv_log ERROR "missing executable: bootstrap/ensure-nat-contract.sh (checked ${_XDR_BOOTSTRAP_DIR:-?} and ${XDR_ROOT}/bootstrap)"
    return 1
  }
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    bash "${ensure_nat}" --dry-run
    return 0
  fi
  rv_run_with_timeout "${NAT_CONTRACT_TIMEOUT_SECS}" \
    "ensure-nat-contract.sh" \
    bash "${ensure_nat}"
  rc=$?
  [[ "${rc}" -eq 0 ]]
}

restore_ovs_net() {
  local rc
  if ! rv_virsh_net_defined; then
    rc=$?
    if [[ "${rc}" -eq 124 ]]; then
      rv_log ERROR "virsh net-info ${LAB_OVS_NETWORK} timed out (${XDR_LAB_VIRSH_TIMEOUT_SECS}s)"
    else
      rv_log INFO "libvirt network ${LAB_OVS_NETWORK} not defined — skipping net-start"
    fi
    return 0
  fi
  if rv_virsh_net_active; then
    return 0
  fi
  run_fix "start libvirt network ${LAB_OVS_NETWORK}" \
    rv_run_with_timeout "${XDR_LAB_VIRSH_TIMEOUT_SECS}" \
      "virsh net-start ${LAB_OVS_NETWORK}" \
      virsh net-start "${LAB_OVS_NETWORK}" || {
      rv_log ERROR "virsh net-start ${LAB_OVS_NETWORK} failed or timed out (non-fatal to br0/NAT)"
      return 0
    }
}

verify_contract() {
  local ok=1 rc
  rv_step_begin verify_contract
  if ! rv_iface_oper_up; then
    rv_log ERROR "contract check failed: ${LAB_BRIDGE} not UP/UNKNOWN"
    ok=0
  fi
  if ! rv_iface_has_gateway_ip; then
    rv_log ERROR "contract check failed: missing ${LAB_GATEWAY}/24 on ${LAB_BRIDGE}"
    ok=0
  fi
  if ! rv_ip_forward_enabled; then
    rv_log ERROR "contract check failed: net.ipv4.ip_forward disabled"
    ok=0
  fi
  if ! rv_masquerade_present; then
    rv_log ERROR "contract check failed: MASQUERADE missing for ${LAB_SUBNET_CIDR}"
    ok=0
  fi
  if ! rv_reverse_nat_present; then
    rc=$?
    if [[ "${rc}" -eq 124 ]]; then
      rv_log ERROR "contract check failed: nat_state.py verify timed out (${XDR_LAB_NAT_VERIFY_TIMEOUT_SECS}s)"
    else
      rv_log ERROR "contract check failed: reverse NAT contract not satisfied"
    fi
    ok=0
  fi
  rv_step_end verify_contract "$((1 - ok))"
  [[ "${ok}" -eq 1 ]]
}

rv_log INFO "ensure-host-network start bridge=${LAB_BRIDGE} dry_run=${DRY_RUN} boot_id=$(rv_current_boot_id 2>/dev/null || echo unknown)"

run_step() {
  local name="$1" rc
  shift
  rv_step_begin "${name}"
  "$@"
  rc=$?
  rv_step_end "${name}" "${rc}"
  return "${rc}"
}

if [[ "${DRY_RUN}" -eq 0 ]]; then
  run_step wait_for_bridge wait_for_bridge || exit 1
  run_step restore_bridge_runtime restore_bridge_runtime || exit 1
  rv_step_begin enable_ip_forward
  sysctl -w net.ipv4.ip_forward=1 >/dev/null
  rv_step_end enable_ip_forward 0
  run_step restore_nat_contract restore_nat_contract || exit 1
  run_step restore_ovs_net restore_ovs_net || true
  if ! verify_contract; then
    rv_log ERROR "ensure-host-network finished with contract verification failure"
    exit 1
  fi
  run_step write_boot_marker rv_write_host_network_boot_marker
else
  run_step wait_for_bridge wait_for_bridge || exit 1
  run_step restore_bridge_runtime restore_bridge_runtime || exit 1
  run_step restore_nat_contract restore_nat_contract || exit 1
fi

rv_log INFO "ensure-host-network finished"
exit 0
