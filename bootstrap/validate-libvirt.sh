#!/usr/bin/env bash
# Validate libvirt runtime on the KVM host appliance.
# Read-only — does not mutate host state.
#
# Usage:
#   ./bootstrap/validate-libvirt.sh [--json]
#
# Exit codes:
#   0   all checks passed
#   10  libvirtd not active
#   20  qemu:///system not reachable
#   30  ovs-net missing
#   31  ovs-net inactive
#   40  virsh list failed
#   50  multiple failures
#
set -euo pipefail

REQUIRE_ROOT=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_runtime-validation-lib.sh
. "${SCRIPT_DIR}/_runtime-validation-lib.sh"

JSON_MODE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) JSON_MODE=1 ;;
    -h|--help)
      sed -n '1,18p' "$0" | tail -n +2
      exit 0
      ;;
    *) rv_log ERROR "unknown argument: $1"; exit 2 ;;
  esac
  shift
done

declare -a RESULTS=()
declare -a FAIL_CODES=()
OVERALL_RC=0

record() {
  local id="$1" ok="$2" detail="$3" code="$4"
  if [[ "${ok}" == "1" ]]; then
    RESULTS+=("$(rv_check_pass "${id}" "${detail}")")
  else
    RESULTS+=("$(rv_check_fail "${id}" "${detail}")")
    FAIL_CODES+=("${code}")
  fi
}

rv_log INFO "validate-libvirt start"

# libvirtd
if systemctl is-active --quiet libvirtd 2>/dev/null; then
  record libvirtd_active 1 "libvirtd is active" 0
else
  record libvirtd_active 0 "libvirtd is not active (systemctl is-active)" 10
fi

# qemu:///system
if virsh -c qemu:///system version &>/dev/null; then
  ver="$(virsh -c qemu:///system version 2>/dev/null | head -n1 || true)"
  record qemu_system 1 "qemu:///system reachable (${ver})" 0
else
  record qemu_system 0 "qemu:///system not reachable" 20
fi

# ovs-net
if virsh net-info "${LAB_OVS_NETWORK}" &>/dev/null; then
  record ovs_net_present 1 "${LAB_OVS_NETWORK} defined" 0
  if rv_virsh_net_active; then
    record ovs_net_active 1 "${LAB_OVS_NETWORK} Active=yes" 0
  else
    record ovs_net_active 0 "${LAB_OVS_NETWORK} inactive" 31
  fi
else
  record ovs_net_present 0 "${LAB_OVS_NETWORK} not defined" 30
  record ovs_net_active 0 "skipped — network missing" 31
fi

# virsh list
if virsh list --all &>/dev/null; then
  dom_count="$(virsh list --all 2>/dev/null | awk 'NR>2 && $2!="" {c++} END{print c+0}')"
  record virsh_list 1 "virsh list --all ok (${dom_count} domains)" 0
else
  record virsh_list 0 "virsh list --all failed" 40
fi

if [[ "${#FAIL_CODES[@]}" -gt 1 ]]; then
  OVERALL_RC=50
elif [[ "${#FAIL_CODES[@]}" -eq 1 ]]; then
  OVERALL_RC="${FAIL_CODES[0]}"
else
  OVERALL_RC=0
fi

if [[ "${JSON_MODE}" -eq 1 ]]; then
  python3 - "${OVERALL_RC}" "${LAB_OVS_NETWORK}" <<'PY' "${RESULTS[@]}"
import json, sys
rc = int(sys.argv[1])
net = sys.argv[2]
rows = sys.argv[3:]
checks = []
for row in rows:
    status, cid, detail = row.split("\t", 2)
    checks.append({"id": cid, "ok": status == "PASS", "detail": detail})
print(json.dumps({
    "script": "validate-libvirt",
    "ok": rc == 0,
    "exit_code": rc,
    "ovs_network": net,
    "checks": checks,
}, indent=2, sort_keys=True))
PY
else
  echo "=== validate-libvirt ==="
  for row in "${RESULTS[@]}"; do
    IFS=$'\t' read -r status id detail <<<"${row}"
    printf '[%s] %-18s %s\n' "${status}" "${id}" "${detail}"
  done
  echo "---"
  if [[ "${OVERALL_RC}" -eq 0 ]]; then
    echo "RESULT: PASS (exit 0)"
  else
    echo "RESULT: FAIL (exit ${OVERALL_RC})"
  fi
fi

rv_log INFO "validate-libvirt finished exit=${OVERALL_RC}"
exit "${OVERALL_RC}"
