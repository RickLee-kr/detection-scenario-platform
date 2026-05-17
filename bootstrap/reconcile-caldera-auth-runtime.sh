#!/usr/bin/env bash
# Reconcile CALDERA disk config with runtime auth: kill stale server.py, patch debug hooks, restart.
#
# Usage:
#   sudo ./bootstrap/reconcile-caldera-auth-runtime.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_runtime-validation-lib.sh
. "${SCRIPT_DIR}/_runtime-validation-lib.sh"

if [[ "$(id -u)" -ne 0 ]]; then
  rv_log ERROR "run as root: sudo $0"
  exit 2
fi

CALDERA_HOME="$(rv_caldera_home)"
VENV_PY="${CALDERA_HOME}/.venv/bin/python3"
PATCH_PY="${SCRIPT_DIR}/../scripts/patch_caldera_auth_debug.py"
DIAG_PY="${SCRIPT_DIR}/../scripts/caldera_runtime_auth_diag.py"

rv_log INFO "=== runtime auth reconcile (pre) ==="
"${VENV_PY}" "${DIAG_PY}" --caldera-home "${CALDERA_HOME}" 2>/dev/null | while read -r line; do
  rv_log INFO "  ${line}"
done || true

rv_caldera_kill_stale_servers || true

if [[ -f "${PATCH_PY}" ]]; then
  "${VENV_PY}" "${PATCH_PY}" --caldera-home "${CALDERA_HOME}"
fi

UNIT_PATH="$(rv_caldera_service_unit_path)"
if grep -q 'XDR_CALDERA_AUTH_DEBUG' "${UNIT_PATH}" 2>/dev/null; then
  rv_log INFO "caldera.service already has XDR_CALDERA_AUTH_DEBUG"
else
  rv_log INFO "add Environment=XDR_CALDERA_AUTH_DEBUG=1 via repair-caldera-service.sh --start"
fi

rv_caldera_restart_service "reconcile-caldera-auth-runtime" || exit 1
sleep 5
rv_caldera_assert_listener_is_systemd || exit 1

rv_log INFO "=== runtime auth reconcile (post) ==="
"${VENV_PY}" "${DIAG_PY}" --caldera-home "${CALDERA_HOME}" 2>/dev/null | while read -r line; do
  rv_log INFO "  ${line}"
done || true

exec "${SCRIPT_DIR}/ensure-caldera-api-key.sh" "$@"
