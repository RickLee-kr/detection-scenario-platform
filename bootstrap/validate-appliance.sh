#!/usr/bin/env bash
# Aggregate appliance runtime validation (host network, CALDERA, libvirt, optional mirror).
#
# Usage:
#   ./bootstrap/validate-appliance.sh [options]
#
# Options:
#   --strict
#   --json
#   --wait
#   --timeout SECONDS
#   --help
#
# Exit codes:
#   0   all required validators passed (WARN-only issues are non-fatal in non-strict mode)
#   1+  one or more required validators failed (lowest failing component code in human mode)
#   2   unknown argument or invalid option value
#
set -euo pipefail

_BOOTSTRAP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_runtime-validation-lib.sh
. "${_BOOTSTRAP_DIR}/_runtime-validation-lib.sh"

JSON_MODE=0
STRICT_MODE=0
WAIT_MODE=0
COMPONENT_TIMEOUT_SECS=120

print_usage() {
  cat <<'EOF'
Usage:
  validate-appliance.sh [options]

Options:
  --strict
  --json
  --wait
  --timeout SECONDS
  --help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) JSON_MODE=1 ;;
    --strict) STRICT_MODE=1 ;;
    --wait) WAIT_MODE=1 ;;
    --timeout)
      shift
      if [[ $# -eq 0 ]]; then
        rv_log ERROR "--timeout requires a value"
        exit 2
      fi
      if ! [[ "$1" =~ ^[0-9]+$ ]] || [[ "$1" -eq 0 ]]; then
        rv_log ERROR "invalid --timeout value: $1"
        exit 2
      fi
      COMPONENT_TIMEOUT_SECS="$1"
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *) rv_log ERROR "unknown argument: $1"; exit 2 ;;
  esac
  shift
done

mode_label() {
  if [[ "${STRICT_MODE}" -eq 1 ]]; then
    echo "strict"
  else
    echo "non-strict"
  fi
}

declare -a COMPONENTS=()
declare -a COMPONENT_RCS=()
declare -a COMPONENT_REQUIRED=()
declare -a COMPONENT_STATUS=()
declare -a COMPONENT_REASON=()

OVERALL_RC=0
OVERALL_RESULT="PASS"

component_status_by_id() {
  local want="$1" i
  for i in "${!COMPONENTS[@]}"; do
    if [[ "${COMPONENTS[$i]}" == "${want}" ]]; then
      echo "${COMPONENT_STATUS[$i]}"
      return 0
    fi
  done
  echo "SKIP"
}

classify_component() {
  local idx="$1"
  local rc="${COMPONENT_RCS[$idx]}"
  local required="${COMPONENT_REQUIRED[$idx]}"
  local status reason

  if [[ "${rc}" -eq "${RV_EXIT_PRIVILEGE_SKIP}" ]]; then
    if [[ "${required}" == "1" ]]; then
      if [[ "${STRICT_MODE}" -eq 1 ]]; then
        status="FAIL"
        reason="required validator skipped due to privilege constraints (strict mode)"
      else
        status="WARN"
        reason="requires root privileges (sudo -n unavailable)"
      fi
    else
      status="SKIP"
      reason="requires root privileges (sudo -n unavailable)"
    fi
  elif [[ "${rc}" -eq 0 ]]; then
    status="PASS"
    reason=""
  elif [[ "${required}" == "0" ]]; then
    if [[ "${STRICT_MODE}" -eq 1 ]]; then
      status="FAIL"
      reason="optional validator failed (strict mode)"
    else
      status="WARN"
      reason="optional validator failed"
    fi
  else
    status="FAIL"
    reason="required validator failed"
  fi

  COMPONENT_STATUS[$idx]="${status}"
  COMPONENT_REASON[$idx]="${reason}"
}

compute_overall() {
  local i status has_fail=0 has_warn=0 fail_rc=0 fail_count=0
  OVERALL_RC=0
  OVERALL_RESULT="PASS"

  for i in "${!COMPONENTS[@]}"; do
    status="${COMPONENT_STATUS[$i]}"
    case "${status}" in
      FAIL)
        has_fail=1
        fail_count=$((fail_count + 1))
        if [[ "${fail_rc}" -eq 0 || "${COMPONENT_RCS[$i]}" -lt "${fail_rc}" ]]; then
          fail_rc="${COMPONENT_RCS[$i]}"
        fi
        ;;
      WARN) has_warn=1 ;;
    esac
  done

  if [[ "${has_fail}" -eq 1 ]]; then
    OVERALL_RC="${fail_rc}"
    if [[ "${fail_count}" -gt 1 ]]; then
      OVERALL_RC=50
    fi
    OVERALL_RESULT="FAIL"
  elif [[ "${has_warn}" -eq 1 ]]; then
    OVERALL_RC=0
    OVERALL_RESULT="WARN"
  else
    OVERALL_RC=0
    OVERALL_RESULT="PASS"
  fi
}

readiness_label() {
  local id="$1" status="$2"
  case "${id}:${status}" in
    host_network:PASS) echo "READY" ;;
    host_network:SKIP|host_network:WARN) echo "NOT VALIDATED" ;;
    host_network:*) echo "NOT READY" ;;
    caldera:PASS) echo "READY" ;;
    caldera:SKIP|caldera:WARN) echo "NOT VALIDATED" ;;
    caldera:*) echo "NOT READY" ;;
    libvirt:PASS) echo "READY" ;;
    libvirt:SKIP|libvirt:WARN) echo "NOT VALIDATED" ;;
    libvirt:*) echo "NOT READY" ;;
    ovs_mirror:PASS) echo "READY" ;;
    ovs_mirror:SKIP|ovs_mirror:WARN) echo "NOT VALIDATED" ;;
    ovs_mirror:*) echo "NOT READY" ;;
    web_console:PASS) echo "READY" ;;
    web_console:SKIP|web_console:WARN) echo "NOT VALIDATED" ;;
    web_console:*) echo "NOT READY" ;;
    *) echo "NOT VALIDATED" ;;
  esac
}

wait_for_caldera_if_requested() {
  local line wait_rc=0
  if [[ "${WAIT_MODE}" -eq 0 ]]; then
    return 0
  fi
  rv_log INFO "caldera wait enabled timeout=${COMPONENT_TIMEOUT_SECS}s"
  set +e
  while IFS= read -r line; do
    [[ -n "${line}" ]] && rv_log INFO "caldera wait: ${line}"
  done < <(rv_caldera_wait_ready "${COMPONENT_TIMEOUT_SECS}")
  wait_rc=$?
  set -e
  if [[ "${wait_rc}" -ne 0 ]]; then
    rv_log WARN "caldera wait finished without HTTP READY (rc=${wait_rc})"
  fi
  return 0
}

run_component() {
  local id="$1" script="$2" required="$3" rc=0 path idx
  if ! path="$(rv_script_path "${script}")"; then
    COMPONENTS+=("${id}")
    COMPONENT_REQUIRED+=("${required}")
    if [[ "${required}" == "1" ]]; then
      COMPONENT_RCS+=(127)
      rv_log ERROR "required validator missing: ${script}"
      idx=$((${#COMPONENTS[@]} - 1))
      COMPONENT_STATUS+=("")
      COMPONENT_REASON+=("")
      classify_component "${idx}"
    else
      COMPONENT_RCS+=(0)
      COMPONENT_STATUS+=("SKIP")
      COMPONENT_REASON+=("validator missing")
      rv_log INFO "optional validator skipped (missing): ${script}"
    fi
    return 0
  fi
  rv_probe_begin "${id}"
  set +e
  rv_run_with_timeout "${COMPONENT_TIMEOUT_SECS}" "${id}" bash -c '
    # shellcheck source=_runtime-validation-lib.sh
    . "'"${_BOOTSTRAP_DIR}"'/_runtime-validation-lib.sh"
    rv_exec_validator "$1"
  ' _ "${path}"
  rc=$?
  set -e
  if [[ "${rc}" -eq 124 ]]; then
    rc=124
  fi
  rv_probe_end "${id}" "$([[ "${rc}" -eq 0 ]] && echo 1 || echo 0)"
  COMPONENTS+=("${id}")
  COMPONENT_RCS+=("${rc}")
  COMPONENT_REQUIRED+=("${required}")
  COMPONENT_STATUS+=("")
  COMPONENT_REASON+=("")
  idx=$((${#COMPONENTS[@]} - 1))
  classify_component "${idx}"
}

rv_log INFO "validate-appliance start mode=$(mode_label) wait=${WAIT_MODE} timeout=${COMPONENT_TIMEOUT_SECS}"

run_component host_network validate-host-network.sh 1
wait_for_caldera_if_requested
run_component caldera validate-caldera.sh 1
run_component libvirt validate-libvirt.sh 0
run_component ovs_mirror validate-ovs-mirror.sh 0
run_component web_console validate-web-console.sh 0

compute_overall

if [[ "${JSON_MODE}" -eq 1 ]]; then
  json_data_file="$(mktemp)"
  {
    printf '%s\n' "${COMPONENTS[@]}"
    printf -- '---\n'
    printf '%s\n' "${COMPONENT_RCS[@]}"
    printf -- '---\n'
    printf '%s\n' "${COMPONENT_REQUIRED[@]}"
    printf -- '---\n'
    printf '%s\n' "${COMPONENT_STATUS[@]}"
  } >"${json_data_file}"
  python3 - "${OVERALL_RESULT}" "$(mode_label)" "${json_data_file}" <<'PY'
import json, sys
overall = sys.argv[1]
mode = sys.argv[2]
with open(sys.argv[3], encoding="utf-8") as fh:
    lines = [line.rstrip("\n") for line in fh]
sep = lines.index("---")
names = lines[:sep]
lines = lines[sep + 1:]
sep = lines.index("---")
rcs = [int(x) for x in lines[:sep]]
lines = lines[sep + 1:]
sep = lines.index("---")
req = [x == "1" for x in lines[:sep]]
statuses = lines[sep + 1:]
components = {}
for name, comp_rc, required, status in zip(names, rcs, req, statuses):
    components[name] = {
        "status": status,
        "exit_code": comp_rc,
        "required": required,
    }
print(json.dumps({
    "result": overall,
    "mode": mode,
    "components": components,
}, indent=2, sort_keys=True))
PY
  rm -f "${json_data_file}"
else
  echo "=== validate-appliance ==="
  echo "Mode: $(mode_label)"
  echo
  for i in "${!COMPONENTS[@]}"; do
    line="[${COMPONENT_STATUS[$i]}] ${COMPONENTS[$i]}"
    if [[ -n "${COMPONENT_REASON[$i]}" ]]; then
      line="${line} (${COMPONENT_REASON[$i]})"
    fi
    echo "${line}"
  done
  echo
  echo "Operational readiness:"
  echo "- Infrastructure: $(readiness_label host_network "$(component_status_by_id host_network)")"
  echo "- CALDERA: $(readiness_label caldera "$(component_status_by_id caldera)")"
  echo "- Runtime persistence: $(readiness_label host_network "$(component_status_by_id host_network)")"
  echo "- Attack orchestration: $(readiness_label caldera "$(component_status_by_id caldera)")"
  echo "- OVS mirror telemetry: $(readiness_label ovs_mirror "$(component_status_by_id ovs_mirror)")"
  echo "- Windows web console: $(readiness_label web_console "$(component_status_by_id web_console)")"
  echo
  echo "RESULT: ${OVERALL_RESULT}"
fi

rv_log INFO "validate-appliance finished result=${OVERALL_RESULT} exit=${OVERALL_RC}"
exit "${OVERALL_RC}"
