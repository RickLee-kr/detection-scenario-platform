#!/usr/bin/env bash
# Golden Image persistence: idempotently restore the XDR Lab NAT contract.
# Mutates only lab-owned chains (XDR_LAB_DNAT / XDR_LAB_FWD) plus one
# MASQUERADE rule and PREROUTING/FORWARD jumps — never global iptables flush.
#
# Usage:
#   sudo ./bootstrap/ensure-nat-contract.sh [--dry-run]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_runtime-validation-lib.sh
. "${SCRIPT_DIR}/_runtime-validation-lib.sh"

DRY_RUN=0
IPTABLES_WAIT_SECS="${XDR_LAB_IPTABLES_WAIT_SECS:-60}"

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
  rv_log ERROR "ensure-nat-contract requires root (sudo)"
  exit 2
fi

run_ipt() {
  local desc="$1"
  shift
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    rv_log INFO "DRY-RUN would: ${desc} — $*"
    return 0
  fi
  rv_log INFO "ACTION: ${desc} — $*"
  "$@"
}

ensure_chain() {
  local table="$1" chain="$2"
  if iptables -t "${table}" -nL "${chain}" &>/dev/null; then
    return 0
  fi
  run_ipt "create chain ${table}/${chain}" iptables -t "${table}" -N "${chain}"
}

wait_for_iptables() {
  local deadline=$((SECONDS + IPTABLES_WAIT_SECS))
  while ! iptables -t nat -nL POSTROUTING &>/dev/null; do
    if (( SECONDS >= deadline )); then
      rv_log ERROR "timeout waiting for iptables/nat (${IPTABLES_WAIT_SECS}s)"
      return 1
    fi
    sleep 1
  done
  return 0
}

apply_masquerade() {
  local wan
  wan="$(rv_uplink_iface)" || {
    rv_log ERROR "cannot detect uplink interface for MASQUERADE (set LAB_UPLINK_IFACE or network.uplink_interface)"
    return 1
  }
  # Drop legacy lab MASQUERADE without -o so -C/-A stay aligned with nat_state.py.
  while iptables -t nat -C POSTROUTING -s "${LAB_SUBNET_CIDR}" -j MASQUERADE 2>/dev/null; do
    run_ipt "remove legacy MASQUERADE for ${LAB_SUBNET_CIDR} (no -o)" \
      iptables -t nat -D POSTROUTING -s "${LAB_SUBNET_CIDR}" -j MASQUERADE || break
  done
  if ! iptables -t nat -C POSTROUTING -s "${LAB_SUBNET_CIDR}" -o "${wan}" -j MASQUERADE 2>/dev/null; then
    run_ipt "MASQUERADE for ${LAB_SUBNET_CIDR} via ${wan}" \
      iptables -t nat -A POSTROUTING -s "${LAB_SUBNET_CIDR}" -o "${wan}" -j MASQUERADE
  fi
}

apply_nat_rules() {
  apply_masquerade || return 1

  ensure_chain nat XDR_LAB_DNAT
  run_ipt "flush XDR_LAB_DNAT" iptables -t nat -F XDR_LAB_DNAT

  declare -a DNAT_RULES=(
    "tcp:1022:10.10.10.10:22"
    "tcp:2022:10.10.10.20:22"
    "tcp:3389:10.10.10.30:3389"
  )
  for spec in "${DNAT_RULES[@]}"; do
    IFS=: read -r proto ext ip port <<<"${spec}"
    run_ipt "DNAT ${proto}/${ext} -> ${ip}:${port}" \
      iptables -t nat -A XDR_LAB_DNAT \
        -p "${proto}" --dport "${ext}" \
        -j DNAT --to-destination "${ip}:${port}"
  done

  if ! iptables -t nat -C PREROUTING -j XDR_LAB_DNAT 2>/dev/null; then
    run_ipt "PREROUTING jump to XDR_LAB_DNAT" \
      iptables -t nat -A PREROUTING -j XDR_LAB_DNAT
  fi

  ensure_chain filter XDR_LAB_FWD
  run_ipt "flush XDR_LAB_FWD" iptables -F XDR_LAB_FWD
  run_ipt "XDR_LAB_FWD RELATED,ESTABLISHED ACCEPT" \
    iptables -A XDR_LAB_FWD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
  run_ipt "XDR_LAB_FWD -o ${LAB_BRIDGE} ACCEPT" \
    iptables -A XDR_LAB_FWD -o "${LAB_BRIDGE}" -j ACCEPT
  if ! iptables -C FORWARD -j XDR_LAB_FWD 2>/dev/null; then
    run_ipt "FORWARD jump to XDR_LAB_FWD" iptables -I FORWARD -j XDR_LAB_FWD
  fi
}

rv_log INFO "ensure-nat-contract start subnet=${LAB_SUBNET_CIDR}"

if [[ "${DRY_RUN}" -eq 0 ]]; then
  wait_for_iptables || exit 1
fi

apply_nat_rules

if [[ "${DRY_RUN}" -eq 0 ]]; then
  if ! rv_masquerade_present || ! rv_reverse_nat_present; then
    rv_log ERROR "NAT contract not satisfied after apply"
    exit 1
  fi
fi

rv_log INFO "ensure-nat-contract finished"
exit 0
