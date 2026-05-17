#!/usr/bin/env bash
# Read-only CALDERA runtime verification for operator CLI paths.
set -euo pipefail

BOOTSTRAP_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_runtime-validation-lib.sh
. "${BOOTSTRAP_SCRIPT_DIR}/_runtime-validation-lib.sh"

WAIT_MODE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --wait) WAIT_MODE=1 ;;
    -h|--help)
      echo "Usage: verify-caldera-runtime.sh [--wait]"
      exit 0
      ;;
    *)
      rv_log ERROR "unknown argument: $1"
      exit 2
      ;;
  esac
  shift
done

if [[ "${WAIT_MODE}" -eq 1 ]]; then
  wait_failed=0
  key="$(rv_caldera_api_key || true)"
  if [[ -n "${key}" ]]; then
    rv_caldera_wait_ready "${XDR_LAB_CALDERA_READY_TIMEOUT_SECS}" || wait_failed=1
    rv_caldera_wait_api_authenticated "${key}" "${XDR_LAB_CALDERA_READY_TIMEOUT_SECS}" || wait_failed=1
  else
    rv_caldera_wait_ready "${XDR_LAB_CALDERA_READY_TIMEOUT_SECS}" || wait_failed=1
  fi
  if [[ "${wait_failed}" -eq 0 ]]; then
    echo "OPERATION_READY true startup_in_progress=false"
  elif rv_caldera_startup_in_progress; then
    echo "OPERATION_READY false startup_in_progress=true"
  fi
  if [[ "${wait_failed}" -ne 0 ]]; then
    exit "${RV_EXIT_CALDERA_NOT_READY}"
  fi
fi

exec "${BOOTSTRAP_SCRIPT_DIR}/validate-caldera.sh"
