#!/usr/bin/env bash
# Ensure XDR Lab CALDERA REST API key at /etc/xdr-lab/caldera-api-key (synced with conf/default.yml).
#
# CALDERA stores api_key_red as an argon2 hash — plaintext cannot be recovered from default.yml.
# When the key file is missing, this script generates a new key, updates default.yml, and
# optionally restarts caldera.service.
#
# CALDERA 5.x REST auth: HTTP header KEY (not Authorization/Bearer). GET /api/agents is protected.
# Main config: conf/default.yml when caldera.service uses server.py --insecure (no local.yml override).
#
# Usage:
#   sudo ./bootstrap/ensure-caldera-api-key.sh [--dry-run] [--verify-only] [--wait] [--no-restart]
#   ./bootstrap/ensure-caldera-api-key.sh --verify-only --wait   # wait for build, then probe
#
# Exit codes:
#   0   key file present and GET /api/agents returns 200 with KEY header
#   1   generic failure
#   2   CALDERA config missing or python helper unavailable
#   3   verify-only: key missing or API not authenticated
#   4   dry-run would rotate (hashed config, no key file)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_runtime-validation-lib.sh
. "${SCRIPT_DIR}/_runtime-validation-lib.sh"

API_KEY_FILE="${API_KEY_FILE:-/etc/xdr-lab/caldera-api-key}"
CALDERA_HOME="${CALDERA_HOME:-$(rv_caldera_home)}"
MAIN_YML="$(rv_caldera_main_config_path)"
DEF_YML="${CALDERA_MAIN_CONFIG:-${MAIN_YML}}"
CONFIG_KEY_FIELD="api_key_red"
BASE_URL="$(rv_caldera_base_url)"
AGENTS_URL="$(rv_url_join_path "${BASE_URL}" "api/agents")"
DRY_RUN=0
VERIFY_ONLY=0
WAIT_FOR_READY=0
RESTART=1
QUIET=0
LAST_CONFIG_UPDATE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --verify-only) VERIFY_ONLY=1 ;;
    --wait|--wait-ready) WAIT_FOR_READY=1 ;;
    --no-restart) RESTART=0 ;;
    --quiet) QUIET=1 ;;
    -h|--help)
      sed -n '1,26p' "$0" | tail -n +2
      exit 0
      ;;
    *) rv_log ERROR "unknown argument: $1"; exit 1 ;;
  esac
  shift
done

log() {
  [[ "${QUIET}" -eq 1 ]] || rv_log INFO "$*"
}

err() {
  rv_log ERROR "$*"
}

caldera_python() {
  local venv_py="${CALDERA_HOME}/.venv/bin/python3"
  if [[ -x "${venv_py}" ]]; then
    echo "${venv_py}"
    return 0
  fi
  if command -v python3 &>/dev/null; then
    echo python3
    return 0
  fi
  return 1
}

util_script() {
  local root="${XDR_ROOT:-${SCRIPT_DIR}/..}"
  local p="${root}/scripts/caldera_api_key_util.py"
  if [[ -f "${p}" ]]; then
    echo "${p}"
    return 0
  fi
  p="${SCRIPT_DIR}/../scripts/caldera_api_key_util.py"
  [[ -f "${p}" ]] && echo "${p}" && return 0
  return 1
}

probe_key_http() {
  local key="$1" _hn code _loc _ct
  [[ -n "${key}" ]] || return 1
  IFS=$'\t' read -r _hn code _loc _ct < <(rv_caldera_auth_probe "${BASE_URL}" "${key}")
  [[ "${code}" == "200" ]]
}

log_auth_probe_failure() {
  local key="$1" label="${2:-auth probe}"
  local _hn code _loc _ct detail
  IFS=$'\t' read -r _hn code _loc _ct < <(rv_caldera_auth_probe "${BASE_URL}" "${key}")
  detail="$(rv_caldera_format_auth_failure "${_hn}" "${code}" "${_loc}" "${_ct}")"
  err "${label}: ${detail} url=${AGENTS_URL}"
  if [[ -n "${LAST_CONFIG_UPDATE}" ]]; then
    err "last_config_update: ${LAST_CONFIG_UPDATE}"
  fi
  rv_caldera_log_config_diag
  rv_caldera_log_auth_journal 60
  err "reload_key: sudo tr -d '\\n\\r' < ${API_KEY_FILE}  (unset stale XDR_CALDERA_API_KEY)"
}

read_key_file() {
  local kf="$1"
  [[ -f "${kf}" ]] || return 1
  tr -d '\n\r' <"${kf}"
}

diag_script() {
  local root="${XDR_ROOT:-${SCRIPT_DIR}/..}"
  local p="${root}/scripts/caldera_config_diag.py"
  if [[ -f "${p}" ]]; then
    echo "${p}"
    return 0
  fi
  p="${SCRIPT_DIR}/../scripts/caldera_config_diag.py"
  [[ -f "${p}" ]] && echo "${p}" && return 0
  return 1
}

key_matches_config_hash() {
  local key="$1" py util tmp_plain diag
  [[ -n "${key}" ]] || return 1
  py="$(caldera_python)" || return 1
  util="$(util_script)" || return 1
  tmp_plain="$(mktemp)"
  printf '%s' "${key}" >"${tmp_plain}"
  if ! "${py}" "${util}" verify --config "${DEF_YML}" --plaintext "${tmp_plain}"; then
    rm -f "${tmp_plain}"
    return 1
  fi
  rm -f "${tmp_plain}"
  diag="$(diag_script)" || return 0
  "${py}" "${diag}" \
    --caldera-home "${CALDERA_HOME}" \
    --config "${DEF_YML}" \
    --key-file "${API_KEY_FILE}" \
    --require-key-match >/dev/null 2>&1
}

require_key_hash_match() {
  local label="${1:-api_key_red}"
  local key=""
  key="$(read_key_file "${API_KEY_FILE}" 2>/dev/null || true)"
  if [[ -z "${key}" ]]; then
    err "${label}: ${API_KEY_FILE} missing or unreadable"
    return 1
  fi
  if ! key_matches_config_hash "${key}"; then
    err "${label}: key_matches_api_key_red=False (${API_KEY_FILE} vs ${DEF_YML})"
    rv_caldera_log_config_diag
    return 1
  fi
  log "${label}: key_matches_api_key_red=True (${DEF_YML})"
  return 0
}

probe_key_http_if_hash_ok() {
  local key="$1" label="${2:-auth probe}"
  require_key_hash_match "${label} (pre-probe)" || return 1
  if probe_key_http "${key}"; then
    return 0
  fi
  log_auth_probe_failure "${key}" "${label}"
  return 1
}

extract_plaintext_from_config() {
  local py util_dir cfg="$1"
  py="$(caldera_python)" || return 1
  util_dir="$(dirname "$(util_script)")"
  CALDERA_HOME="${CALDERA_HOME}" PYTHONPATH="${util_dir}${PYTHONPATH:+:${PYTHONPATH}}" \
    "${py}" - "${cfg}" <<'PY' 2>/dev/null || return 1
import sys
from pathlib import Path
from caldera_key_crypto import is_hashed, load_config, normalize_plaintext_key

cfg = load_config(Path(sys.argv[1]))
val = str(cfg.get("api_key_red") or "")
if val and not is_hashed(val):
    print(normalize_plaintext_key(val))
PY
}

ensure_root_for_write() {
  if [[ "$(id -u)" -ne 0 ]]; then
    err "root required to create ${API_KEY_FILE} — run: sudo $0"
    return 1
  fi
  return 0
}

install_key_file() {
  local key="$1" xdr_root="${XDR_ROOT:-/opt/xdr-lab}" resolver sync_rc=0
  ensure_root_for_write || return 1
  mkdir -p /etc/xdr-lab
  chmod 0750 /etc/xdr-lab
  install -m 0640 -o root -g root /dev/null "${API_KEY_FILE}"
  printf '%s' "${key}" >"${API_KEY_FILE}"
  if getent group xdr-lab >/dev/null 2>&1; then
    chown root:xdr-lab "${API_KEY_FILE}"
    chmod 0640 "${API_KEY_FILE}"
    log "Wrote ${API_KEY_FILE} (mode 0640, group xdr-lab)"
  else
    chmod 0600 "${API_KEY_FILE}"
    log "Wrote ${API_KEY_FILE} (mode 0600)"
  fi
  resolver="${xdr_root}/scripts/caldera_api_key_resolve.py"
  if [[ ! -f "${resolver}" && -f "${SCRIPT_DIR}/../scripts/caldera_api_key_resolve.py" ]]; then
    resolver="${SCRIPT_DIR}/../scripts/caldera_api_key_resolve.py"
  fi
  if [[ -f "${resolver}" ]]; then
    python3 "${resolver}" --sync-runtime --xdr-root "${xdr_root}" --source "${API_KEY_FILE}" || sync_rc=$?
    if [[ "${sync_rc}" -eq 0 ]]; then
      log "Synced runtime API key copy: ${xdr_root}/runtime/caldera-api-key"
    else
      rv_log WARN "runtime API key copy sync failed (CLI may need sudo installer or re-run ensure)"
    fi
  fi
}

sync_runtime_key_copy() {
  local xdr_root="${XDR_ROOT:-/opt/xdr-lab}" resolver sync_rc=0
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "DRY-RUN: would sync runtime API key copy"
    return 0
  fi
  resolver="${xdr_root}/scripts/caldera_api_key_resolve.py"
  if [[ ! -f "${resolver}" && -f "${SCRIPT_DIR}/../scripts/caldera_api_key_resolve.py" ]]; then
    resolver="${SCRIPT_DIR}/../scripts/caldera_api_key_resolve.py"
  fi
  [[ -f "${resolver}" ]] || return 0
  python3 "${resolver}" --sync-runtime --xdr-root "${xdr_root}" --source "${API_KEY_FILE}" || sync_rc=$?
  if [[ "${sync_rc}" -eq 0 ]]; then
    log "Synced runtime API key copy: ${xdr_root}/runtime/caldera-api-key"
  else
    rv_log WARN "runtime API key copy sync failed"
  fi
}

sync_config_and_file() {
  local mode="$1" py util extra=()
  py="$(caldera_python)" || { err "python3 not found (install CALDERA venv)"; return 2; }
  util="$(util_script)" || { err "missing scripts/caldera_api_key_util.py"; return 2; }
  [[ -f "${DEF_YML}" ]] || { err "missing ${DEF_YML}"; return 2; }
  case "${mode}" in
    generate) extra+=(--generate) ;;
    plaintext) extra+=(--plaintext "${API_KEY_FILE}") ;;
    file) extra=() ;;
  esac
  "${py}" "${util}" sync --config "${DEF_YML}" --key-file "${API_KEY_FILE}" "${extra[@]}"
}

record_config_update() {
  local action="$1"
  LAST_CONFIG_UPDATE="file=${DEF_YML} key=${CONFIG_KEY_FIELD} action=${action}"
  log "updated ${DEF_YML} (${CONFIG_KEY_FIELD}, ${action})"
}

restart_caldera_service() {
  local reason="$1" key="${2:-}"
  [[ "${RESTART}" -eq 1 ]] || return 0
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "DRY-RUN: would systemctl restart caldera.service (${reason})"
    return 0
  fi
  if ! rv_caldera_restart_service "${reason}"; then
    err "caldera.service must be restarted to load ${CONFIG_KEY_FIELD} from ${DEF_YML} — run: sudo systemctl restart caldera.service"
    return 1
  fi
  rv_caldera_wait_ready || true
  if [[ -n "${key}" ]]; then
    rv_caldera_wait_api_authenticated "${key}" || true
  fi
}

# --- main ---

wait_for_caldera_ready_if_requested() {
  local key="${1:-}" ready_msg auth_msg
  [[ "${WAIT_FOR_READY}" -eq 1 ]] || return 0
  log "waiting for CALDERA HTTP ready (timeout=${XDR_LAB_CALDERA_READY_TIMEOUT_SECS}s)…"
  if ! ready_msg="$(rv_caldera_wait_ready "${XDR_LAB_CALDERA_READY_TIMEOUT_SECS}")"; then
    err "CALDERA not ready: ${ready_msg}"
    rv_caldera_log_auth_journal 80
    return 1
  fi
  log "CALDERA HTTP ready: ${ready_msg}"
  if [[ -n "${key}" ]]; then
    if auth_msg="$(rv_caldera_wait_api_authenticated "${key}" "${XDR_LAB_CALDERA_READY_TIMEOUT_SECS}")"; then
      log "CALDERA API authenticated: ${auth_msg}"
      return 0
    fi
    err "CALDERA API not authenticated after wait: ${auth_msg:-timeout}"
    rv_caldera_log_auth_journal 80
    return 1
  fi
  return 0
}

log "ensure-caldera-api-key start base_url=${BASE_URL} key_file=${API_KEY_FILE} main_config=${DEF_YML}"
rv_caldera_log_runtime_auth_diag || true
if [[ "${DRY_RUN}" -eq 0 ]] && [[ "$(id -u)" -eq 0 ]]; then
  if ! rv_caldera_stale_grace_active && ! rv_caldera_startup_in_progress; then
    rv_caldera_kill_stale_servers || true
  else
    log "stale cleanup skipped at start (grace or startup/build in progress)"
  fi
fi
rv_caldera_log_config_diag

if [[ ! -f "${DEF_YML}" ]]; then
  err "api_key_missing: CALDERA main config not found (${DEF_YML}) — expected for --insecure: ${CALDERA_HOME}/conf/default.yml"
  exit 2
fi

if [[ -f "${CALDERA_HOME}/conf/local.yml" ]]; then
  log "NOTE: conf/local.yml exists but is NOT loaded when caldera.service uses --insecure (only default.yml)"
fi

existing_key=""
if existing_key="$(read_key_file "${API_KEY_FILE}" 2>/dev/null)"; then
  :
else
  existing_key=""
fi

if [[ "${VERIFY_ONLY}" -eq 1 ]]; then
  if [[ -z "${existing_key}" ]]; then
    err "api_key_missing: ${API_KEY_FILE} not readable"
    exit 3
  fi
  if ! require_key_hash_match "verify-only"; then
    exit 3
  fi
  wait_for_caldera_ready_if_requested "${existing_key}" || exit 3
  if probe_key_http_if_hash_ok "${existing_key}" "verify-only"; then
    log "API key OK — GET ${AGENTS_URL} http_code=200"
    exit 0
  fi
  log_auth_probe_failure "${existing_key}" "api_key_invalid"
  exit 3
fi

if [[ -n "${existing_key}" ]]; then
  if probe_key_http_if_hash_ok "${existing_key}" "existing key"; then
    sync_runtime_key_copy
    log "API key OK — GET ${AGENTS_URL} http_code=200 header=${RV_CALDERA_API_AUTH_HEADER}"
    exit 0
  fi
  if key_matches_config_hash "${existing_key}"; then
    log "Key file matches ${CONFIG_KEY_FIELD} hash but HTTP probe failed — re-syncing / restart"
  else
    log "API key file present but key_matches_api_key_red=False — re-syncing"
  fi
fi

plain_from_cfg=""
plain_from_cfg="$(extract_plaintext_from_config "${DEF_YML}" || true)"

if [[ -n "${plain_from_cfg}" ]]; then
  log "Recovered plaintext ${CONFIG_KEY_FIELD} from ${DEF_YML}"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "DRY-RUN: would write ${API_KEY_FILE} and skip rotation"
    exit 0
  fi
  install_key_file "${plain_from_cfg}"
  record_config_update "plaintext_recovery"
  require_key_hash_match "after plaintext_recovery" || exit 1
  restart_caldera_service "reload plaintext ${CONFIG_KEY_FIELD}" "${plain_from_cfg}"
  require_key_hash_match "after plaintext_recovery restart" || exit 1
  if probe_key_http_if_hash_ok "${plain_from_cfg}" "api_key after plaintext recovery"; then
    exit 0
  fi
  exit 1
fi

if [[ -n "${existing_key}" ]] && key_matches_config_hash "${existing_key}"; then
  log "Key file matches ${CONFIG_KEY_FIELD} hash in ${DEF_YML} but HTTP probe failed — restarting caldera.service"
  restart_caldera_service "reload ${CONFIG_KEY_FIELD} from disk" "${existing_key}"
  require_key_hash_match "after hash-match restart" || exit 1
  if probe_key_http_if_hash_ok "${existing_key}" "api_key after restart"; then
    log "CALDERA API authenticated after service restart"
    exit 0
  fi
  exit 1
fi

if [[ "${DRY_RUN}" -eq 1 ]]; then
  err "DRY-RUN: would generate new API key (${CONFIG_KEY_FIELD} hashed, ${API_KEY_FILE} missing/invalid)"
  exit 4
fi

ensure_root_for_write || exit 1

if [[ "${RESTART}" -eq 1 ]] && systemctl is-active --quiet caldera.service 2>/dev/null; then
  log "stopping caldera.service before api_key_red sync (avoid teardown clobbering default.yml)"
  systemctl stop caldera.service || true
fi

action="$(sync_config_and_file generate)" || {
  err "failed to sync API key into ${DEF_YML} (${CONFIG_KEY_FIELD}) and ${API_KEY_FILE}"
  exit 1
}
record_config_update "${action}"
log "caldera_api_key_util: ${action}"

require_key_hash_match "after ${action}" || exit 1

new_key="$(read_key_file "${API_KEY_FILE}")"
restart_caldera_service "api_key_${action}" "${new_key}"

require_key_hash_match "after caldera restart" || exit 1

if probe_key_http_if_hash_ok "${new_key}" "api_key after rotate"; then
  log "CALDERA API authenticated — export XDR_CALDERA_API_KEY from ${API_KEY_FILE}"
  exit 0
fi

exit 1
