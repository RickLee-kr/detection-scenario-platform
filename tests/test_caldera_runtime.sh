#!/usr/bin/env bash
# Shell tests for CALDERA bootstrap / validation scripts (no live CALDERA required).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOOT="${ROOT}/bootstrap"
PASS=0
FAIL=0

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [[ "${actual}" == "${expected}" ]]; then
    echo "PASS ${label}"
    PASS=$((PASS + 1))
  else
    echo "FAIL ${label} expected=${expected} actual=${actual}" >&2
    FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local label="$1" needle="$2" haystack="$3"
  if grep -Fq "${needle}" <<<"${haystack}"; then
    echo "PASS ${label}"
    PASS=$((PASS + 1))
  else
    echo "FAIL ${label} missing '${needle}' in output" >&2
    FAIL=$((FAIL + 1))
  fi
}

assert_not_contains() {
  local label="$1" needle="$2" haystack="$3"
  if grep -Fq "${needle}" <<<"${haystack}"; then
    echo "FAIL ${label} unexpected '${needle}' in output" >&2
    FAIL=$((FAIL + 1))
  else
    echo "PASS ${label}"
    PASS=$((PASS + 1))
  fi
}

setup_fake_caldera() {
  local tmp="$1"
  local user="$2"
  mkdir -p "${tmp}/caldera/conf"
  printf '#!/usr/bin/env python3\nprint("ok")\n' >"${tmp}/caldera/server.py"
  printf 'requests\n' >"${tmp}/caldera/requirements.txt"
  mkdir -p "${tmp}/bin" "${tmp}/etc/systemd/system"
  cat >"${tmp}/bin/systemctl" <<'MOCK'
#!/usr/bin/env bash
case "$*" in
  *"show caldera.service -p ActiveState"*) echo active; exit 0 ;;
  *"show caldera.service -p SubState"*) echo running; exit 0 ;;
  *"show caldera.service -p Result"*) echo success; exit 0 ;;
  *"show caldera.service -p ExecMainStatus"*) echo 0; exit 0 ;;
  *"show caldera.service -p ExecMainCode"*) echo 0; exit 0 ;;
  *"is-enabled caldera.service"*) exit 0 ;;
  *"is-active caldera.service"*) exit 0 ;;
  *) exit 0 ;;
esac
MOCK
  cat >"${tmp}/bin/ss" <<'MOCK'
#!/usr/bin/env bash
# no listeners
exit 0
MOCK
  cat >"${tmp}/bin/curl" <<'MOCK'
#!/usr/bin/env bash
echo 000
exit 0
MOCK
  chmod +x "${tmp}/bin/"*
  cat >"${tmp}/etc/systemd/system/caldera.service" <<EOF
[Service]
User=${user}
Group=${user}
ExecStart=${tmp}/caldera/.venv/bin/python3 ${tmp}/caldera/server.py --insecure --build
WorkingDirectory=${tmp}/caldera
EOF
}

test_validate_missing_user_217() {
  local tmp
  tmp="$(mktemp -d)"
  setup_fake_caldera "${tmp}" "nobody-caldera-missing"
  local out rc
  set +e
  out="$(CALDERA_HOME="${tmp}/caldera" \
    XDR_LAB_CALDERA_SERVICE_UNIT="${tmp}/etc/systemd/system/caldera.service" \
    PATH="${tmp}/bin:${PATH}" \
    bash "${BOOT}/validate-caldera.sh" 2>&1)"
  rc=$?
  set -e
  assert_contains "validate 217/USER diagnostic" "217/USER" "${out}"
  assert_contains "validate user check FAIL" "[FAIL] caldera_service_user" "${out}"
  if [[ "${rc}" == "6" || "${rc}" == "50" ]]; then
    echo "PASS validate missing user exit (${rc})"
    PASS=$((PASS + 1))
  else
    echo "FAIL validate missing user exit expected=6|50 actual=${rc}" >&2
    FAIL=$((FAIL + 1))
  fi
  rm -rf "${tmp}"
}

test_validate_missing_venv_203() {
  local tmp
  tmp="$(mktemp -d)"
  setup_fake_caldera "${tmp}" "$(id -un)"
  local out rc
  set +e
  out="$(CALDERA_HOME="${tmp}/caldera" \
    XDR_LAB_CALDERA_SERVICE_UNIT="${tmp}/etc/systemd/system/caldera.service" \
    PATH="${tmp}/bin:${PATH}" \
    bash "${BOOT}/validate-caldera.sh" 2>&1)"
  rc=$?
  set -e
  assert_contains "validate 203/EXEC diagnostic" "203/EXEC" "${out}"
  assert_contains "validate exec binary FAIL" "[FAIL] caldera_exec_binary" "${out}"
  if [[ "${rc}" == "7" || "${rc}" == "50" ]]; then
    echo "PASS validate missing venv exit (${rc})"
    PASS=$((PASS + 1))
  else
    echo "FAIL validate missing venv exit expected=7|50 actual=${rc}" >&2
    FAIL=$((FAIL + 1))
  fi
  rm -rf "${tmp}"
}

test_validate_no_false_process_pass() {
  local tmp
  tmp="$(mktemp -d)"
  setup_fake_caldera "${tmp}" "$(id -un)"
  mkdir -p "${tmp}/caldera/.venv/bin"
  printf '#!/bin/sh\n' >"${tmp}/caldera/.venv/bin/python3"
  chmod +x "${tmp}/caldera/.venv/bin/python3"
  local out
  set +e
  out="$(CALDERA_HOME="${tmp}/caldera" \
    XDR_LAB_CALDERA_SERVICE_UNIT="${tmp}/etc/systemd/system/caldera.service" \
    PATH="${tmp}/bin:${PATH}" \
    bash "${BOOT}/validate-caldera.sh" 2>&1)"
  set -e
  assert_contains "process FAIL when port down" "[FAIL] caldera_process" "${out}"
  assert_not_contains "process false PASS" "[PASS] caldera_process" "${out}"
  rm -rf "${tmp}"
}

test_ensure_creates_venv() {
  local tmp
  tmp="$(mktemp -d)"
  mkdir -p "${tmp}/caldera"
  printf '# stub\n' >"${tmp}/caldera/server.py"
  printf '\n' >"${tmp}/caldera/requirements.txt"
  local rc
  set +e
  CALDERA_HOME="${tmp}/caldera" XDR_LAB_CALDERA_USER="$(id -un)" \
    bash "${BOOT}/ensure-caldera-runtime.sh"
  rc=$?
  set -e
  assert_eq "ensure venv exit" "0" "${rc}"
  if [[ -x "${tmp}/caldera/.venv/bin/python3" ]]; then
    echo "PASS ensure created venv python"
    PASS=$((PASS + 1))
  else
    echo "FAIL ensure created venv python" >&2
    FAIL=$((FAIL + 1))
  fi
  rm -rf "${tmp}"
}

test_repair_no_hardcoded_aella() {
  if grep -Eq '(^|[^_])aella([^_]|$)|User=aella|Group=aella' "${BOOT}/repair-caldera-service.sh"; then
    echo "FAIL repair script hardcodes aella" >&2
    FAIL=$((FAIL + 1))
  else
    echo "PASS repair script does not hardcode aella"
    PASS=$((PASS + 1))
  fi
  if grep -Eq '(^|[^_])aella([^_]|$)|User=aella|Group=aella' "${BOOT}/ensure-caldera-runtime.sh"; then
    echo "FAIL ensure script hardcodes aella" >&2
    FAIL=$((FAIL + 1))
  else
    echo "PASS ensure script does not hardcode aella"
    PASS=$((PASS + 1))
  fi
}

test_validate_appliance_aggregation() {
  local tmp
  tmp="$(mktemp -d)"
  mkdir -p "${tmp}/bootstrap"
  install -m 0755 "${BOOT}/_runtime-validation-lib.sh" "${tmp}/bootstrap/"
  cat >"${tmp}/bootstrap/validate-host-network.sh" <<'EOS'
#!/usr/bin/env bash
exit 0
EOS
  cat >"${tmp}/bootstrap/validate-caldera.sh" <<'EOS'
#!/usr/bin/env bash
exit 10
EOS
  chmod +x "${tmp}/bootstrap/"*.sh
  local out rc
  set +e
  out="$(XDR_ROOT="${tmp}" XDR_LAB_BOOTSTRAP_DIR="${tmp}/bootstrap" \
    bash "${BOOT}/validate-appliance.sh" 2>&1)"
  rc=$?
  set -e
  assert_eq "validate-appliance fail exit" "10" "${rc}"
  assert_contains "appliance host PASS" "[PASS] host_network" "${out}"
  assert_contains "appliance caldera FAIL" "[FAIL] caldera" "${out}"
  rm -rf "${tmp}"
}

echo "=== test_caldera_runtime ==="
test_validate_missing_user_217
test_validate_missing_venv_203
test_validate_no_false_process_pass
test_ensure_creates_venv
test_repair_no_hardcoded_aella
test_validate_appliance_aggregation

echo "---"
echo "passed=${PASS} failed=${FAIL}"
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
