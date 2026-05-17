#!/usr/bin/env bash
# Enable CALDERA auth debug logging (journal: caldera.xdr.auth) and apply runtime patches.
#
# Usage:
#   sudo ./bootstrap/enable-caldera-auth-debug.sh [--restart]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_runtime-validation-lib.sh
. "${SCRIPT_DIR}/_runtime-validation-lib.sh"

DO_RESTART=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --restart) DO_RESTART=1 ;;
    -h|--help)
      echo "Usage: sudo $0 [--restart]"
      exit 0
      ;;
    *) rv_log ERROR "unknown argument: $1"; exit 1 ;;
  esac
  shift
done

if [[ "$(id -u)" -ne 0 ]]; then
  rv_log ERROR "run as root: sudo $0"
  exit 2
fi

CALDERA_HOME="$(rv_caldera_home)"
VENV_PY="${CALDERA_HOME}/.venv/bin/python3"
PATCH_PY="${SCRIPT_DIR}/../scripts/patch_caldera_auth_debug.py"
DROPIN_SRC="${SCRIPT_DIR}/../installer/caldera.service.d/xdr-auth-debug.conf"
DROPIN_DIR="/etc/systemd/system/caldera.service.d"

rv_step_begin "install auth debug patches"
"${VENV_PY}" "${PATCH_PY}" --caldera-home "${CALDERA_HOME}" || true
"${VENV_PY}" "${PATCH_PY}" --caldera-home "${CALDERA_HOME}" --upgrade || true
rv_step_end "install auth debug patches" 0

rv_step_begin "systemd drop-in XDR_CALDERA_AUTH_DEBUG"
mkdir -p "${DROPIN_DIR}"
install -m 0644 "${DROPIN_SRC}" "${DROPIN_DIR}/xdr-auth-debug.conf"
systemctl daemon-reload
rv_step_end "systemd drop-in XDR_CALDERA_AUTH_DEBUG" 0

if [[ "${DO_RESTART}" -eq 1 ]]; then
  rv_caldera_kill_stale_servers || true
  rv_caldera_restart_service "enable-caldera-auth-debug" || exit 1
fi

rv_log INFO "Auth debug enabled. Probe then: journalctl -u caldera.service -n 100 | grep caldera.xdr.auth"
exit 0
