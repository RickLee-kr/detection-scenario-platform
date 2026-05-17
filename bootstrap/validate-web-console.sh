#!/usr/bin/env bash
# Validate Windows VM web consoles (websockify + noVNC -> 127.0.0.1:QEMU-VNC).
# Read-only — does not start or stop websockify.
#
# Usage:
#   ./bootstrap/validate-web-console.sh [--json]
#
# Exit codes:
#   0   all probed running VMs passed web-console verify
#   10  one or more running VMs failed verify
#   11  VM manager or verify subcommand unavailable
#   20  no VMs configured (empty PORT_MAP and no default VM)
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
      sed -n '1,16p' "$0" | tail -n +2
      exit 0
      ;;
    *) rv_log ERROR "unknown argument: $1"; exit 2 ;;
  esac
  shift
done

declare -a RESULTS=()
declare -a FAIL_CODES=()
declare -a TARGET_VMS=()
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

record_skip() {
  local id="$1" detail="$2"
  RESULTS+=("$(rv_check_skip "${id}" "${detail}")")
}

# Parse XDR_LAB_WEB_CONSOLE_PORT_MAP="vm=port,..." or "vm:port".
wc_parse_port_map_vms() {
  local map="${XDR_LAB_WEB_CONSOLE_PORT_MAP:-}" entry k
  TARGET_VMS=()
  [[ -n "${map}" ]] || return 0
  local IFS=,
  for entry in $map; do
    entry="${entry#"${entry%%[![:space:]]*}"}"
    entry="${entry%"${entry##*[![:space:]]}"}"
    [[ -n "${entry}" ]] || continue
    if [[ "$entry" == *=* ]]; then
      k="${entry%%=*}"
    elif [[ "$entry" == *:* ]]; then
      k="${entry%%:*}"
    else
      continue
    fi
    k="${k#"${k%%[![:space:]]*}"}"
    k="${k%"${k##*[![:space:]]}"}"
    [[ -n "${k}" ]] && TARGET_VMS+=("${k}")
  done
}

wc_default_vms() {
  TARGET_VMS=("${XDR_LAB_NAT_WEB_CONSOLE_VM:-windows-victim}")
}

wc_vm_manager() {
  local candidate
  for candidate in \
    "${XDR_SCRIPTS_DIR:-}/xdr-lab-vm-manager.sh" \
    "${XDR_ROOT}/scripts/xdr-lab-vm-manager.sh" \
    "${SCRIPT_DIR}/../scripts/xdr-lab-vm-manager.sh"; do
    [[ -f "${candidate}" ]] || continue
    echo "${candidate}"
    return 0
  done
  return 1
}

wc_domstate() {
  local vm="$1" st
  command -v virsh &>/dev/null || return 1
  st="$(virsh domstate "$vm" 2>/dev/null | tr -d '\r' || true)"
  [[ "${st}" == "running" ]]
}

rv_log INFO "validate-web-console start port_map=${XDR_LAB_WEB_CONSOLE_PORT_MAP:-<default>}"

wc_parse_port_map_vms
if [[ "${#TARGET_VMS[@]}" -eq 0 ]]; then
  wc_default_vms
fi

mgr="$(wc_vm_manager || true)"
if [[ -z "${mgr}" ]]; then
  record web_console_tooling 0 "xdr-lab-vm-manager.sh not found" 11
  OVERALL_RC=11
else
  for vm in "${TARGET_VMS[@]}"; do
    id="web_console_${vm}"
    rv_probe_begin "${id}"
    if ! wc_domstate "${vm}"; then
      record_skip "${id}" "${vm} not running (skipped)"
      rv_probe_end "${id}" 1
      continue
    fi
    verify_out=""
    verify_rc=0
    set +e
    verify_out="$(rv_run_with_timeout "${XDR_LAB_PROBE_TIMEOUT_SECS}" \
      "web-console verify ${vm}" \
      bash "${mgr}" web-console verify "${vm}" 2>&1)"
    verify_rc=$?
    set -e
    if [[ "${verify_rc}" -eq 0 ]]; then
      record "${id}" 1 "${vm} web-console verify ok" 0
      rv_probe_end "${id}" 1
    elif [[ "${verify_rc}" -eq 124 ]]; then
      record "${id}" 0 "${vm} verify timed out (${XDR_LAB_PROBE_TIMEOUT_SECS}s)" 10
      rv_probe_end "${id}" 0
    else
      detail="${vm} web-console verify failed"
      if [[ -n "${verify_out}" ]]; then
        detail="${detail}: $(printf '%s' "${verify_out}" | tr '\n' ' ' | head -c 200)"
      fi
      record "${id}" 0 "${detail}" 10
      rv_probe_end "${id}" 0
    fi
  done
fi

if [[ "${#FAIL_CODES[@]}" -gt 1 ]]; then
  OVERALL_RC=50
elif [[ "${#FAIL_CODES[@]}" -eq 1 ]]; then
  OVERALL_RC="${FAIL_CODES[0]}"
else
  OVERALL_RC=0
fi

if [[ "${JSON_MODE}" -eq 1 ]]; then
  python3 - "${OVERALL_RC}" <<'PY' "${RESULTS[@]}"
import json, sys
rc = int(sys.argv[1])
rows = sys.argv[2:]
checks = []
for row in rows:
    parts = row.split("\t", 2)
    if len(parts) < 3:
        continue
    status, cid, detail = parts[0], parts[1], parts[2]
    checks.append({"id": cid, "status": status, "detail": detail})
print(json.dumps({"result": "PASS" if rc == 0 else "FAIL", "exit_code": rc, "checks": checks}, indent=2))
PY
else
  echo "=== validate-web-console ==="
  for row in "${RESULTS[@]}"; do
    IFS=$'\t' read -r st id detail <<<"${row}"
    echo "[${st}] ${id}: ${detail}"
  done
  echo
  echo "RESULT: $([[ "${OVERALL_RC}" -eq 0 ]] && echo PASS || echo FAIL)"
fi

rv_log INFO "validate-web-console finished exit=${OVERALL_RC}"
exit "${OVERALL_RC}"
