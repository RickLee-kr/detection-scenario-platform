#!/usr/bin/env bash
# Idempotent CALDERA runtime preparation (venv, deps, ownership).
#
# Usage:
#   sudo ./bootstrap/ensure-caldera-runtime.sh [--apt-repair]
#
# Exit codes:
#   0   runtime ready
#   2   CALDERA_HOME/server.py missing
#   3   requirements.txt missing
#   4   python3-venv unavailable (use --apt-repair as root)
#   5   venv creation failed
#   6   pip bootstrap failed
#   7   pip requirements install failed
#   8   runtime user could not be resolved
#   9   ownership adjustment failed
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_runtime-validation-lib.sh
. "${SCRIPT_DIR}/_runtime-validation-lib.sh"

APT_REPAIR=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apt-repair) APT_REPAIR=1 ;;
    -h|--help)
      sed -n '1,18p' "$0" | tail -n +2
      exit 0
      ;;
    *) rv_log ERROR "unknown argument: $1"; exit 1 ;;
  esac
  shift
done

CALDERA_HOME="$(rv_caldera_home)"
SERVER_PY="${CALDERA_HOME}/server.py"
VENV_PY="${CALDERA_HOME}/.venv/bin/python3"
REQ_FILE="${CALDERA_HOME}/requirements.txt"
RUNTIME_USER=""

rv_log INFO "ensure-caldera-runtime start home=${CALDERA_HOME}"

rv_step_begin "resolve runtime user"
if ! RUNTIME_USER="$(rv_resolve_caldera_runtime_user)"; then
  rv_step_end "resolve runtime user" 8
  rv_log ERROR "could not resolve CALDERA runtime user — set XDR_LAB_CALDERA_USER to a valid account"
  exit 8
fi
rv_step_end "resolve runtime user" 0
rv_log INFO "runtime user=${RUNTIME_USER}"

rv_step_begin "verify server.py"
if [[ ! -f "${SERVER_PY}" ]]; then
  rv_step_end "verify server.py" 2
  rv_log ERROR "missing ${SERVER_PY} — install CALDERA first (bootstrap/caldera-server-bootstrap.sh)"
  exit 2
fi
rv_step_end "verify server.py" 0

rv_step_begin "ensure ownership"
if [[ "$(id -u)" -eq 0 ]]; then
  current_owner="$(stat -c '%U' "${CALDERA_HOME}" 2>/dev/null || echo "")"
  if [[ "${current_owner}" != "${RUNTIME_USER}" ]]; then
    if ! rv_run_with_timeout 60 "chown ${CALDERA_HOME}" \
        chown -R "${RUNTIME_USER}:${RUNTIME_USER}" "${CALDERA_HOME}"; then
      rv_step_end "ensure ownership" 9
      rv_log ERROR "chown failed for ${CALDERA_HOME}"
      exit 9
    fi
    rv_log INFO "adjusted ownership of ${CALDERA_HOME} to ${RUNTIME_USER}"
  else
    rv_log INFO "ownership already ${RUNTIME_USER} — skipped"
  fi
else
  rv_log INFO "not root — skipped ownership adjustment"
fi
rv_step_end "ensure ownership" 0

run_as_runtime() {
  if [[ "$(id -u)" -eq 0 ]]; then
    rv_run_with_timeout "$1" "$2" sudo -u "${RUNTIME_USER}" -H bash -lc "$3"
  else
    rv_run_with_timeout "$1" "$2" bash -lc "$3"
  fi
}

venv_module_ok() {
  python3 -c 'import venv' &>/dev/null
}

rv_step_begin "verify python3 venv module"
if ! venv_module_ok; then
  if [[ "${APT_REPAIR}" -eq 1 && "$(id -u)" -eq 0 ]]; then
    rv_log INFO "installing python3-venv (--apt-repair)"
    if ! rv_run_with_timeout 300 "apt install python3-venv" \
        env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv; then
      rv_step_end "verify python3 venv module" 4
      rv_log ERROR "apt install python3-venv failed"
      exit 4
    fi
  else
    rv_step_end "verify python3 venv module" 4
    rv_log ERROR "python3-venv unavailable — install: apt install python3-venv  OR re-run as root with --apt-repair"
    exit 4
  fi
fi
rv_step_end "verify python3 venv module" 0

rv_step_begin "verify venv python"
if [[ ! -x "${VENV_PY}" ]]; then
  rv_log INFO "creating venv at ${CALDERA_HOME}/.venv"
  if ! run_as_runtime "${XDR_LAB_VENV_TIMEOUT_SECS}" "python3 -m venv" \
      "python3 -m venv '${CALDERA_HOME}/.venv'"; then
    rv_step_end "verify venv python" 5
    rv_log ERROR "venv creation failed"
    exit 5
  fi
fi
if [[ ! -x "${VENV_PY}" ]]; then
  rv_step_end "verify venv python" 5
  rv_log ERROR "${VENV_PY} still missing after venv create"
  exit 5
fi
rv_step_end "verify venv python" 0

rv_step_begin "upgrade pip setuptools wheel"
if ! run_as_runtime "${XDR_LAB_PIP_TIMEOUT_SECS}" "pip bootstrap" \
    "'${VENV_PY}' -m pip install -U pip setuptools wheel"; then
  rv_step_end "upgrade pip setuptools wheel" 6
  rv_log ERROR "pip bootstrap failed"
  exit 6
fi
rv_step_end "upgrade pip setuptools wheel" 0

rv_step_begin "install requirements.txt"
if [[ ! -f "${REQ_FILE}" ]]; then
  rv_step_end "install requirements.txt" 3
  rv_log ERROR "missing ${REQ_FILE}"
  exit 3
fi
if ! run_as_runtime "${XDR_LAB_PIP_TIMEOUT_SECS}" "pip install requirements" \
    "cd '${CALDERA_HOME}' && '${VENV_PY}' -m pip install -r requirements.txt"; then
  rv_step_end "install requirements.txt" 7
  rv_log ERROR "pip install -r requirements.txt failed"
  exit 7
fi
rv_step_end "install requirements.txt" 0

rv_log INFO "ensure-caldera-runtime finished ok user=${RUNTIME_USER} venv=${VENV_PY}"
exit 0
