#!/usr/bin/env bash
# Tests for validate-appliance.sh CLI parsing, JSON output, and strict aggregation.
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
  if grep -Fq -- "${needle}" <<<"${haystack}"; then
    echo "PASS ${label}"
    PASS=$((PASS + 1))
  else
    echo "FAIL ${label} missing '${needle}' in output" >&2
    FAIL=$((FAIL + 1))
  fi
}

setup_appliance_stub_dir() {
  local tmp="$1"
  mkdir -p "${tmp}/bootstrap"
  install -m 0755 "${BOOT}/_runtime-validation-lib.sh" "${tmp}/bootstrap/"
}

stub_all_validators_pass() {
  local tmp="$1"
  cat >"${tmp}/bootstrap/validate-host-network.sh" <<'EOS'
#!/usr/bin/env bash
REQUIRE_ROOT=0
exit 0
EOS
  cat >"${tmp}/bootstrap/validate-caldera.sh" <<'EOS'
#!/usr/bin/env bash
REQUIRE_ROOT=0
exit 0
EOS
  cat >"${tmp}/bootstrap/validate-libvirt.sh" <<'EOS'
#!/usr/bin/env bash
REQUIRE_ROOT=0
exit 0
EOS
  cat >"${tmp}/bootstrap/validate-ovs-mirror.sh" <<'EOS'
#!/usr/bin/env bash
REQUIRE_ROOT=0
exit 0
EOS
  cat >"${tmp}/bootstrap/validate-web-console.sh" <<'EOS'
#!/usr/bin/env bash
REQUIRE_ROOT=0
exit 0
EOS
  chmod +x "${tmp}/bootstrap/"*.sh
}

test_cli_accepts_strict() {
  local tmp out rc
  tmp="$(mktemp -d)"
  setup_appliance_stub_dir "${tmp}"
  stub_all_validators_pass "${tmp}"
  set +e
  out="$(XDR_ROOT="${tmp}" XDR_LAB_BOOTSTRAP_DIR="${tmp}/bootstrap" \
    bash "${BOOT}/validate-appliance.sh" --strict 2>&1)"
  rc=$?
  set -e
  assert_eq "strict parser exit" "0" "${rc}"
  assert_contains "strict mode banner" "Mode: strict" "${out}"
  rm -rf "${tmp}"
}

test_cli_unknown_argument() {
  local out rc
  set +e
  out="$(bash "${BOOT}/validate-appliance.sh" --not-a-real-flag 2>&1)"
  rc=$?
  set -e
  assert_eq "unknown argument exit" "2" "${rc}"
  assert_contains "unknown argument message" "unknown argument: --not-a-real-flag" "${out}"
}

test_cli_help() {
  local out rc
  set +e
  out="$(bash "${BOOT}/validate-appliance.sh" --help 2>&1)"
  rc=$?
  set -e
  assert_eq "help exit" "0" "${rc}"
  assert_contains "help usage" "Usage:" "${out}"
  assert_contains "help strict option" "--strict" "${out}"
  assert_contains "help timeout option" "--timeout SECONDS" "${out}"
}

test_cli_json_mode() {
  local tmp out rc parsed
  tmp="$(mktemp -d)"
  setup_appliance_stub_dir "${tmp}"
  stub_all_validators_pass "${tmp}"
  set +e
  out="$(XDR_ROOT="${tmp}" XDR_LAB_BOOTSTRAP_DIR="${tmp}/bootstrap" \
    bash "${BOOT}/validate-appliance.sh" --json 2>/dev/null)"
  rc=$?
  set -e
  assert_eq "json mode exit" "0" "${rc}"
  parsed="$(python3 -c 'import json,sys; json.loads(sys.stdin.read())' <<<"${out}" && echo ok || echo bad)"
  assert_eq "json parses" "ok" "${parsed}"
  assert_contains "json result pass" '"result": "PASS"' "${out}"
  assert_contains "json mode non-strict" '"mode": "non-strict"' "${out}"
  assert_contains "json host network component" '"host_network"' "${out}"
  assert_contains "json host network status" '"status": "PASS"' "${out}"
  rm -rf "${tmp}"
}

test_cli_json_strict_mode_field() {
  local tmp out
  tmp="$(mktemp -d)"
  setup_appliance_stub_dir "${tmp}"
  stub_all_validators_pass "${tmp}"
  out="$(XDR_ROOT="${tmp}" XDR_LAB_BOOTSTRAP_DIR="${tmp}/bootstrap" \
    bash "${BOOT}/validate-appliance.sh" --json --strict 2>/dev/null)"
  assert_contains "json strict mode field" '"mode": "strict"' "${out}"
  rm -rf "${tmp}"
}

test_strict_optional_fail_fails() {
  local tmp out rc
  tmp="$(mktemp -d)"
  setup_appliance_stub_dir "${tmp}"
  stub_all_validators_pass "${tmp}"
  cat >"${tmp}/bootstrap/validate-libvirt.sh" <<'EOS'
#!/usr/bin/env bash
REQUIRE_ROOT=0
exit 10
EOS
  chmod +x "${tmp}/bootstrap/validate-libvirt.sh"
  set +e
  out="$(XDR_ROOT="${tmp}" XDR_LAB_BOOTSTRAP_DIR="${tmp}/bootstrap" \
    bash "${BOOT}/validate-appliance.sh" --strict 2>&1)"
  rc=$?
  set -e
  assert_contains "strict optional fail status" "[FAIL] libvirt" "${out}"
  assert_contains "strict optional fail overall" "RESULT: FAIL" "${out}"
  if [[ "${rc}" -ne 0 ]]; then
    echo "PASS strict optional fail non-zero exit (${rc})"
    PASS=$((PASS + 1))
  else
    echo "FAIL strict optional fail expected non-zero exit actual=${rc}" >&2
    FAIL=$((FAIL + 1))
  fi
  rm -rf "${tmp}"
}

test_non_strict_optional_fail_warns() {
  local tmp out rc
  tmp="$(mktemp -d)"
  setup_appliance_stub_dir "${tmp}"
  stub_all_validators_pass "${tmp}"
  cat >"${tmp}/bootstrap/validate-libvirt.sh" <<'EOS'
#!/usr/bin/env bash
REQUIRE_ROOT=0
exit 10
EOS
  chmod +x "${tmp}/bootstrap/validate-libvirt.sh"
  set +e
  out="$(XDR_ROOT="${tmp}" XDR_LAB_BOOTSTRAP_DIR="${tmp}/bootstrap" \
    bash "${BOOT}/validate-appliance.sh" 2>&1)"
  rc=$?
  set -e
  assert_eq "non-strict optional fail exit" "0" "${rc}"
  assert_contains "non-strict optional fail warn" "[WARN] libvirt" "${out}"
  assert_contains "non-strict optional fail overall warn" "RESULT: WARN" "${out}"
  rm -rf "${tmp}"
}

test_timeout_requires_value() {
  local out rc
  set +e
  out="$(bash "${BOOT}/validate-appliance.sh" --timeout 2>&1)"
  rc=$?
  set -e
  assert_eq "timeout missing value exit" "2" "${rc}"
  assert_contains "timeout missing value message" "--timeout requires a value" "${out}"
}

test_timeout_invalid_value() {
  local out rc
  set +e
  out="$(bash "${BOOT}/validate-appliance.sh" --timeout abc 2>&1)"
  rc=$?
  set -e
  assert_eq "timeout invalid value exit" "2" "${rc}"
  assert_contains "timeout invalid value message" "invalid --timeout value: abc" "${out}"
}

test_timeout_zero_rejected() {
  local out rc
  set +e
  out="$(bash "${BOOT}/validate-appliance.sh" --timeout 0 2>&1)"
  rc=$?
  set -e
  assert_eq "timeout zero exit" "2" "${rc}"
  assert_contains "timeout zero message" "invalid --timeout value: 0" "${out}"
}

test_timeout_parsing_logged() {
  local tmp out
  tmp="$(mktemp -d)"
  setup_appliance_stub_dir "${tmp}"
  stub_all_validators_pass "${tmp}"
  out="$(XDR_ROOT="${tmp}" XDR_LAB_BOOTSTRAP_DIR="${tmp}/bootstrap" \
    bash "${BOOT}/validate-appliance.sh" --timeout 45 2>&1)"
  assert_contains "timeout value logged" "timeout=45" "${out}"
  rm -rf "${tmp}"
}

test_non_strict_mode_banner() {
  local tmp out
  tmp="$(mktemp -d)"
  setup_appliance_stub_dir "${tmp}"
  stub_all_validators_pass "${tmp}"
  out="$(XDR_ROOT="${tmp}" XDR_LAB_BOOTSTRAP_DIR="${tmp}/bootstrap" \
    bash "${BOOT}/validate-appliance.sh" 2>&1)"
  assert_contains "non-strict mode banner" "Mode: non-strict" "${out}"
  rm -rf "${tmp}"
}

echo "=== test_validate_appliance_cli ==="
test_cli_accepts_strict
test_cli_unknown_argument
test_cli_help
test_cli_json_mode
test_cli_json_strict_mode_field
test_strict_optional_fail_fails
test_non_strict_optional_fail_warns
test_timeout_requires_value
test_timeout_invalid_value
test_timeout_zero_rejected
test_timeout_parsing_logged
test_non_strict_mode_banner

echo "---"
echo "passed=${PASS} failed=${FAIL}"
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
