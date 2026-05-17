#!/usr/bin/env bash
# Validate CALDERA server runtime on the KVM host appliance.
# Read-only — does not start or install CALDERA.
#
# Usage:
#   ./bootstrap/validate-caldera.sh [--json]
#
# Exit codes:
#   0   all checks passed
#   5   caldera.service unit file missing
#   15  caldera.service not enabled
#   6   configured User/Group invalid (systemd 217/USER)
#   7   ExecStart python missing/not executable (systemd 203/EXEC)
#   8   /opt/caldera/server.py missing
#   10  caldera.service not active (or auto-restart loop)
#   20  configured port not listening
#   30  local HTTP probe failed
#   35  CALDERA HTTP reachable but REST API not authenticated (GET /api/agents)
#   40  HTTP probe via lab gateway failed
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
      sed -n '1,22p' "$0" | tail -n +2
      exit 0
      ;;
    *) rv_log ERROR "unknown argument: $1"; exit 2 ;;
  esac
  shift
done

CALDERA_HOME="$(rv_caldera_home)"
SERVER_PY="${CALDERA_HOME}/server.py"
UNIT_PATH="$(rv_caldera_service_unit_path)"
BASE_URL="$(rv_caldera_base_url)"
PORT="$(rv_caldera_port)"

declare -a RESULTS=()
declare -a FAIL_CODES=()

record() {
  local id="$1" ok="$2" detail="$3" code="$4"
  if [[ "${ok}" == "1" ]]; then
    RESULTS+=("$(rv_check_pass "${id}" "${detail}")")
  else
    RESULTS+=("$(rv_check_fail "${id}" "${detail}")")
    FAIL_CODES+=("${code}")
  fi
}

http_probe_reachable() {
  local url="$1" code
  read -r code _loc _ct < <(rv_caldera_agents_http_meta "${url}")
  [[ "${code}" =~ ^(200|302|401|403)$ ]]
}

rv_log INFO "validate-caldera start home=${CALDERA_HOME} base_url=${BASE_URL} port=${PORT}"

# (a) service file exists
if [[ -f "${UNIT_PATH}" ]]; then
  record caldera_service_file 1 "${UNIT_PATH} exists" 0
else
  record caldera_service_file 0 "${UNIT_PATH} missing — run repair-caldera-service.sh" 5
fi

# (b) unit enabled
rv_probe_begin caldera_unit_enabled
enabled_ok=0
enabled_detail=""
if rv_systemd_unit_enabled caldera.service; then
  enabled_ok=1
  enabled_detail="caldera.service is enabled"
else
  enabled_detail="caldera.service not enabled — run repair-caldera-service.sh"
fi
rv_probe_end caldera_unit_enabled "${enabled_ok}"
record caldera_unit_enabled "${enabled_ok}" "${enabled_detail}" 15

# (c) configured User exists
service_user="$(rv_caldera_service_user_from_unit)"
user_ok=0
user_detail=""
if [[ -z "${service_user}" ]]; then
  user_detail="caldera.service has no User= (or unit missing)"
elif rv_user_exists "${service_user}"; then
  user_ok=1
  user_detail="User=${service_user} exists"
else
  user_detail="User=${service_user} missing (systemd 217/USER) — run ensure-caldera-runtime.sh and repair-caldera-service.sh"
fi
record caldera_service_user "${user_ok}" "${user_detail}" 6

# (d) ExecStart binary exists and executable
exec_py="$(rv_caldera_execstart_python || true)"
exec_ok=0
exec_detail=""
if [[ -z "${exec_py}" ]]; then
  exec_detail="could not parse ExecStart from ${UNIT_PATH}"
elif [[ -x "${exec_py}" ]]; then
  exec_ok=1
  exec_detail="ExecStart python executable: ${exec_py}"
else
  exec_detail="${exec_py} missing or not executable (systemd 203/EXEC) — run ensure-caldera-runtime.sh"
fi
record caldera_exec_binary "${exec_ok}" "${exec_detail}" 7

# (e) server.py exists
if [[ -f "${SERVER_PY}" ]]; then
  record caldera_server_py 1 "${SERVER_PY} exists" 0
else
  record caldera_server_py 0 "${SERVER_PY} missing" 8
fi

# (f) service active state + systemd diagnostics
active_ok=0
active_detail=""
active_state="$(rv_systemd_show_field caldera.service ActiveState)"
sub_state="$(rv_systemd_show_field caldera.service SubState)"
result="$(rv_systemd_show_field caldera.service Result)"
exec_status="$(rv_systemd_show_field caldera.service ExecMainStatus)"
exec_code="$(rv_systemd_show_field caldera.service ExecMainCode)"
diag="ActiveState=${active_state:-unknown} SubState=${sub_state:-unknown} Result=${result:-none} ExecMainStatus=${exec_status:-0} ExecMainCode=${exec_code:-0}"

if [[ "${active_state}" == "active" && "${sub_state}" == "running" ]]; then
  active_ok=1
  active_detail="caldera.service active (running); ${diag}"
elif [[ "${active_state}" == "activating" && "${sub_state}" == "auto-restart" ]]; then
  decoded="$(rv_decode_systemd_exec_failure "${exec_status}" "${exec_code}")"
  active_detail="caldera.service auto-restart loop — ${decoded}; ${diag}"
elif [[ "${active_state}" == "failed" || "${result}" == "exit-code" ]]; then
  decoded="$(rv_decode_systemd_exec_failure "${exec_status}" "${exec_code}")"
  active_detail="caldera.service failed — ${decoded}; ${diag}"
else
  active_detail="caldera.service not active — ${diag}"
fi
record caldera_service_active "${active_ok}" "${active_detail}" 10

# (g) tcp/PORT listening — never skip; no false PASS without ss/netstat
listen_ok=0
listen_detail=""
if command -v ss &>/dev/null || command -v netstat &>/dev/null; then
  if rv_caldera_port_listening "${PORT}"; then
    listen_ok=1
    listen_detail="tcp/${PORT} listening"
  else
    listen_detail="tcp/${PORT} not listening"
  fi
else
  listen_detail="ss/netstat unavailable — cannot verify tcp/${PORT}"
fi
record caldera_port_listen "${listen_ok}" "${listen_detail}" 20

# caldera_process: legacy id — PASS only when service active AND port listening (no pgrep)
proc_ok=0
proc_detail=""
if [[ "${active_ok}" -eq 1 && "${listen_ok}" -eq 1 ]]; then
  proc_ok=1
  proc_detail="caldera.service active and tcp/${PORT} listening"
else
  proc_detail="runtime not healthy — requires active service and listening port (no pgrep shortcut)"
fi
record caldera_process "${proc_ok}" "${proc_detail}" 10

# (h) local HTTP probe — reachable vs API-authenticated
read -r local_code local_loc local_ct < <(rv_caldera_agents_http_meta "${BASE_URL}")
rv_log INFO "validate-caldera http_local probe http_code=${local_code} location=${local_loc:-} content_type=${local_ct:-}"
if http_probe_reachable "${BASE_URL}"; then
  record http_local 1 "HTTP reachable at $(rv_url_join_path "${BASE_URL}" api/agents) (http_code=${local_code} location=${local_loc:-none})" 0
else
  record http_local 0 "HTTP probe failed for $(rv_url_join_path "${BASE_URL}" api/agents) (http_code=${local_code})" 30
fi

main_cfg="$(rv_caldera_main_config_path)"
api_key="$(rv_caldera_api_key)"
if [[ -z "${api_key}" ]]; then
  record http_api_authenticated 0 "api_key_missing — run: sudo bootstrap/ensure-caldera-api-key.sh (config ${main_cfg} api_key_red)" 35
else
  read -r auth_hdr auth_code auth_loc auth_ct < <(rv_caldera_auth_probe "${BASE_URL}" "${api_key}")
  rv_log INFO "validate-caldera http_api_authenticated config=${main_cfg} $(rv_caldera_format_auth_failure "${auth_hdr}" "${auth_code}" "${auth_loc}" "${auth_ct}")"
  if [[ "${auth_code}" != "200" ]] && rv_systemd_unit_active caldera.service; then
    rv_log INFO "validate-caldera: KEY auth not 200; running config diag"
    rv_caldera_log_config_diag
  fi
  if [[ "${auth_code}" == "200" ]]; then
    record http_api_authenticated 1 "GET /api/agents authenticated (config=${main_cfg} api_key_red header=${auth_hdr} http_code=200)" 0
  elif [[ "${auth_code}" == "302" && "${auth_loc}" == *login* ]]; then
    record http_api_authenticated 0 "GET /api/agents redirected to login (config=${main_cfg} header=${auth_hdr} http_code=302 location=${auth_loc}) — sudo bootstrap/ensure-caldera-api-key.sh; unset stale XDR_CALDERA_API_KEY" 35
    rv_caldera_log_auth_journal 60
  elif [[ "${auth_code}" == "401" || "${auth_code}" == "403" ]]; then
    record http_api_authenticated 0 "GET /api/agents rejected (config=${main_cfg} header=${auth_hdr} http_code=${auth_code}) — API key mismatch" 35
    rv_caldera_log_auth_journal 60
  else
    record http_api_authenticated 0 "GET /api/agents not authenticated (config=${main_cfg} header=${auth_hdr} http_code=${auth_code} location=${auth_loc:-none})" 35
    rv_caldera_log_auth_journal 60
  fi
fi

# guest path via lab gateway
gw_url="http://${LAB_GATEWAY}:${PORT}"
gw_required=1
if [[ "${BASE_URL}" =~ ^https?://(127\.0\.0\.1|localhost)(:|/|$) ]]; then
  gw_required=0
fi
if [[ "${gw_required}" -eq 0 ]]; then
  record http_via_gateway 1 "skipped — CALDERA binds loopback (${BASE_URL})" 0
elif http_probe_reachable "${gw_url}"; then
  read -r gw_code gw_loc _gw_ct < <(rv_caldera_agents_http_meta "${gw_url}")
  record http_via_gateway 1 "HTTP reachable at $(rv_url_join_path "${gw_url}" api/agents) (http_code=${gw_code} location=${gw_loc:-none})" 0
else
  record http_via_gateway 0 "HTTP probe failed for $(rv_url_join_path "${gw_url}" api/agents) (guests may not reach CALDERA)" 40
fi

if [[ "${#FAIL_CODES[@]}" -gt 1 ]]; then
  OVERALL_RC=50
elif [[ "${#FAIL_CODES[@]}" -eq 1 ]]; then
  OVERALL_RC="${FAIL_CODES[0]}"
else
  OVERALL_RC=0
fi

if [[ "${JSON_MODE}" -eq 1 ]]; then
  python3 - "${OVERALL_RC}" "${BASE_URL}" "${PORT}" "${LAB_GATEWAY}" "${CALDERA_HOME}" <<'PY' "${RESULTS[@]}"
import json, sys
rc = int(sys.argv[1])
base, port, gw, home = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
rows = sys.argv[6:]
checks = []
for row in rows:
    status, cid, detail = row.split("\t", 2)
    checks.append({"id": cid, "ok": status == "PASS", "detail": detail})
print(json.dumps({
    "script": "validate-caldera",
    "ok": rc == 0,
    "exit_code": rc,
    "caldera_home": home,
    "base_url": base,
    "port": int(port),
    "lab_gateway": gw,
    "checks": checks,
}, indent=2, sort_keys=True))
PY
else
  echo "=== validate-caldera (${BASE_URL}) ==="
  for row in "${RESULTS[@]}"; do
    IFS=$'\t' read -r status id detail <<<"${row}"
    printf '[%s] %-22s %s\n' "${status}" "${id}" "${detail}"
  done
  echo "---"
  if [[ "${OVERALL_RC}" -eq 0 ]]; then
    echo "RESULT: PASS (exit 0)"
  else
    echo "RESULT: FAIL (exit ${OVERALL_RC})"
  fi
fi

rv_log INFO "validate-caldera finished exit=${OVERALL_RC}"
exit "${OVERALL_RC}"
