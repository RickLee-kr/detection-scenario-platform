#!/usr/bin/env bash
# Align caldera.service with the live CALDERA runtime (user, venv python, deps).
#
# Usage:
#   sudo ./bootstrap/repair-caldera-service.sh [--dry-run] [--start]
#
# Exit codes:
#   0   unit written/reloaded (and started when --start)
#   2   runtime user unresolved
#   3   server.py missing
#   4   venv python missing (run ensure-caldera-runtime.sh)
#   5   not root (required except --dry-run)
#   6   systemctl failed
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_runtime-validation-lib.sh
. "${SCRIPT_DIR}/_runtime-validation-lib.sh"

DRY_RUN=0
DO_START=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --start) DO_START=1 ;;
    -h|--help)
      sed -n '1,16p' "$0" | tail -n +2
      exit 0
      ;;
    *) rv_log ERROR "unknown argument: $1"; exit 1 ;;
  esac
  shift
done

CALDERA_HOME="$(rv_caldera_home)"
SERVER_PY="${CALDERA_HOME}/server.py"
VENV_PY="${CALDERA_HOME}/.venv/bin/python3"
UNIT_PATH="$(rv_caldera_service_unit_path)"
DOC_URL="file:///opt/xdr-lab/docs/caldera-integration.md"
if [[ -n "${XDR_ROOT:-}" ]]; then
  DOC_URL="file://${XDR_ROOT}/docs/caldera-integration.md"
fi

RUNTIME_USER=""
rv_step_begin "resolve runtime user"
if ! RUNTIME_USER="$(rv_resolve_caldera_runtime_user)"; then
  rv_step_end "resolve runtime user" 2
  rv_log ERROR "could not resolve CALDERA runtime user — set XDR_LAB_CALDERA_USER"
  exit 2
fi
rv_step_end "resolve runtime user" 0

rv_step_begin "verify server.py"
if [[ ! -f "${SERVER_PY}" ]]; then
  rv_step_end "verify server.py" 3
  rv_log ERROR "missing ${SERVER_PY}"
  exit 3
fi
rv_step_end "verify server.py" 0

rv_step_begin "verify venv python"
if [[ ! -x "${VENV_PY}" ]]; then
  rv_step_end "verify venv python" 4
  rv_log ERROR "missing ${VENV_PY} — run bootstrap/ensure-caldera-runtime.sh first"
  exit 4
fi
rv_step_end "verify venv python" 0

UNIT_BODY="$(cat <<EOF
[Unit]
Description=MITRE CALDERA (XDR Lab)
Documentation=${DOC_URL}
After=network-online.target xdr-lab-host-network.service
Wants=network-online.target xdr-lab-host-network.service
ConditionPathExists=${SERVER_PY}

[Service]
Type=simple
User=${RUNTIME_USER}
Group=${RUNTIME_USER}
WorkingDirectory=${CALDERA_HOME}
Environment=PYTHONUNBUFFERED=1
Environment=XDR_CALDERA_AUTH_DEBUG=1
ExecStart=${VENV_PY} ${SERVER_PY} --insecure --build
Restart=on-failure
RestartSec=5
TimeoutStartSec=900
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF
)"

if [[ "${DRY_RUN}" -eq 1 ]]; then
  rv_log INFO "dry-run: would write ${UNIT_PATH} user=${RUNTIME_USER}"
  printf '%s\n' "${UNIT_BODY}"
  exit 0
fi

if [[ "$(id -u)" -ne 0 ]]; then
  rv_log ERROR "run as root (sudo) to install systemd unit"
  exit 5
fi

rv_step_begin "write systemd unit"
install -m 0644 /dev/null "${UNIT_PATH}.tmp"
printf '%s\n' "${UNIT_BODY}" >"${UNIT_PATH}.tmp"
mv "${UNIT_PATH}.tmp" "${UNIT_PATH}"
rv_step_end "write systemd unit" 0

rv_step_begin "systemctl daemon-reload"
if ! rv_run_with_timeout "${XDR_LAB_SYSTEMCTL_TIMEOUT_SECS}" \
    "systemctl daemon-reload" systemctl daemon-reload; then
  rv_step_end "systemctl daemon-reload" 6
  exit 6
fi
rv_step_end "systemctl daemon-reload" 0

rv_step_begin "systemctl enable caldera.service"
if ! rv_run_with_timeout "${XDR_LAB_SYSTEMCTL_TIMEOUT_SECS}" \
    "systemctl enable caldera.service" systemctl enable caldera.service; then
  rv_step_end "systemctl enable caldera.service" 6
  exit 6
fi
rv_step_end "systemctl enable caldera.service" 0

if [[ "${DO_START}" -eq 1 ]]; then
  rv_step_begin "kill stale CALDERA processes"
  rv_caldera_kill_stale_servers || true
  rv_step_end "kill stale CALDERA processes" 0
  rv_step_begin "patch CALDERA auth debug hooks"
  PATCH_PY="${SCRIPT_DIR}/../scripts/patch_caldera_auth_debug.py"
  if [[ -f "${PATCH_PY}" ]]; then
    "${VENV_PY}" "${PATCH_PY}" --caldera-home "${CALDERA_HOME}" || rv_log WARN "patch_caldera_auth_debug failed (non-fatal)"
  fi
  rv_step_end "patch CALDERA auth debug hooks" 0
  rv_step_begin "restart caldera.service"
  systemctl reset-failed caldera.service 2>/dev/null || true
  if ! rv_caldera_restart_service "repair-caldera-service --start"; then
    rv_log WARN "caldera restart helper returned non-zero — service may still be starting (TimeoutStartSec=900)"
  fi
  rv_caldera_assert_listener_is_systemd || true
  rv_caldera_log_runtime_auth_diag || true
  rv_step_end "restart caldera.service" 0
fi

rv_log INFO "repair-caldera-service finished user=${RUNTIME_USER} start=${DO_START}"
exit 0
