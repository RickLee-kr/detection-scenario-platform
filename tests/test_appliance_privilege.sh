#!/usr/bin/env bash
# Tests for privilege-aware appliance validation (non-root, SKIP, strict mode).
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

setup_appliance_stub_dir() {
  local tmp="$1"
  mkdir -p "${tmp}/bootstrap"
  install -m 0755 "${BOOT}/_runtime-validation-lib.sh" "${tmp}/bootstrap/"
}

test_host_network_non_root_skips_root_probes() {
  local tmp out rc
  tmp="$(mktemp -d)"
  setup_appliance_stub_dir "${tmp}"
  mkdir -p "${tmp}/bin"
  cat >"${tmp}/bin/ovs-vsctl" <<'MOCK'
#!/usr/bin/env bash
echo "ovs-vsctl: cannot connect to /var/run/openvswitch/db.sock: Permission denied" >&2
exit 1
MOCK
  mkdir -p "${tmp}/bin"
  cat >"${tmp}/bin/sudo" <<'MOCK'
#!/usr/bin/env bash
echo "sudo: a password is required" >&2
exit 1
MOCK
  chmod +x "${tmp}/bin/"*
  set +e
  out="$(PATH="${tmp}/bin:${PATH}" \
    XDR_ROOT="${tmp}" XDR_LAB_BOOTSTRAP_DIR="${BOOT}" \
    bash "${BOOT}/validate-host-network.sh" 2>&1)"
  rc=$?
  set -e
  assert_contains "non-root ovs skip" "[SKIP] ovs_vsctl" "${out}"
  assert_contains "non-root ovs skip reason" "requires root privileges (ovs-vsctl)" "${out}"
  assert_contains "non-root nat skip" "[SKIP] nat_masquerade" "${out}"
  assert_contains "non-root reverse nat skip" "[SKIP] reverse_nat" "${out}"
  assert_not_contains "non-root ovs false fail" "[FAIL] ovs_vsctl" "${out}"
  assert_not_contains "non-root nat false fail" "[FAIL] nat_masquerade" "${out}"
  assert_not_contains "non-root reverse nat false fail" "[FAIL] reverse_nat" "${out}"
  rm -rf "${tmp}"
}

test_appliance_privilege_skip_required() {
  local tmp out rc
  tmp="$(mktemp -d)"
  setup_appliance_stub_dir "${tmp}"
  cat >"${tmp}/bootstrap/validate-host-network.sh" <<'EOS'
#!/usr/bin/env bash
REQUIRE_ROOT=1
exit 77
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
  chmod +x "${tmp}/bootstrap/"*.sh
  mkdir -p "${tmp}/bin"
  cat >"${tmp}/bin/sudo" <<'MOCK'
#!/usr/bin/env bash
exit 1
MOCK
  chmod +x "${tmp}/bin/sudo"
  set +e
  out="$(PATH="${tmp}/bin:${PATH}" \
    XDR_ROOT="${tmp}" XDR_LAB_BOOTSTRAP_DIR="${tmp}/bootstrap" \
    bash "${BOOT}/validate-appliance.sh" 2>&1)"
  rc=$?
  set -e
  assert_eq "required privilege skip exit" "0" "${rc}"
  assert_contains "host network privilege warn" "[WARN] host_network" "${out}"
  assert_contains "host network skip reason" "requires root privileges" "${out}"
  assert_contains "overall warn with required skip" "RESULT: WARN" "${out}"
  rm -rf "${tmp}"
}

test_appliance_strict_required_skip_fails() {
  local tmp out rc
  tmp="$(mktemp -d)"
  setup_appliance_stub_dir "${tmp}"
  cat >"${tmp}/bootstrap/validate-host-network.sh" <<'EOS'
#!/usr/bin/env bash
REQUIRE_ROOT=1
exit 77
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
  chmod +x "${tmp}/bootstrap/"*.sh
  mkdir -p "${tmp}/bin"
  cat >"${tmp}/bin/sudo" <<'MOCK'
#!/usr/bin/env bash
exit 1
MOCK
  chmod +x "${tmp}/bin/sudo"
  set +e
  out="$(PATH="${tmp}/bin:${PATH}" \
    XDR_ROOT="${tmp}" XDR_LAB_BOOTSTRAP_DIR="${tmp}/bootstrap" \
    bash "${BOOT}/validate-appliance.sh" --strict 2>&1)"
  rc=$?
  set -e
  assert_contains "strict required skip becomes fail" "[FAIL] host_network" "${out}"
  assert_contains "strict overall fail" "RESULT: FAIL" "${out}"
  if [[ "${rc}" -ne 0 ]]; then
    echo "PASS strict required skip non-zero exit (${rc})"
    PASS=$((PASS + 1))
  else
    echo "FAIL strict required skip expected non-zero exit actual=${rc}" >&2
    FAIL=$((FAIL + 1))
  fi
  rm -rf "${tmp}"
}

test_appliance_optional_fail_warns() {
  local tmp out rc
  tmp="$(mktemp -d)"
  setup_appliance_stub_dir "${tmp}"
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
exit 10
EOS
  chmod +x "${tmp}/bootstrap/"*.sh
  set +e
  out="$(XDR_ROOT="${tmp}" XDR_LAB_BOOTSTRAP_DIR="${tmp}/bootstrap" \
    bash "${BOOT}/validate-appliance.sh" 2>&1)"
  rc=$?
  set -e
  assert_eq "optional fail warn exit" "0" "${rc}"
  assert_contains "optional fail status warn" "[WARN] libvirt" "${out}"
  assert_contains "optional fail overall warn" "RESULT: WARN" "${out}"
  rm -rf "${tmp}"
}

test_appliance_optional_missing_skip() {
  local tmp out rc
  tmp="$(mktemp -d)"
  setup_appliance_stub_dir "${tmp}"
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
  chmod +x "${tmp}/bootstrap/"*.sh
  set +e
  out="$(XDR_ROOT="${tmp}" XDR_LAB_BOOTSTRAP_DIR="${tmp}/bootstrap" \
    bash "${BOOT}/validate-appliance.sh" 2>&1)"
  rc=$?
  set -e
  assert_eq "missing optional overall pass" "0" "${rc}"
  assert_contains "missing ovs mirror skip" "[SKIP] ovs_mirror" "${out}"
  assert_contains "missing ovs mirror reason" "validator missing" "${out}"
  assert_contains "operational summary present" "Operational readiness:" "${out}"
  rm -rf "${tmp}"
}

test_appliance_required_fail() {
  local tmp out rc
  tmp="$(mktemp -d)"
  setup_appliance_stub_dir "${tmp}"
  cat >"${tmp}/bootstrap/validate-host-network.sh" <<'EOS'
#!/usr/bin/env bash
REQUIRE_ROOT=0
exit 0
EOS
  cat >"${tmp}/bootstrap/validate-caldera.sh" <<'EOS'
#!/usr/bin/env bash
REQUIRE_ROOT=0
exit 10
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
  chmod +x "${tmp}/bootstrap/"*.sh
  set +e
  out="$(XDR_ROOT="${tmp}" XDR_LAB_BOOTSTRAP_DIR="${tmp}/bootstrap" \
    bash "${BOOT}/validate-appliance.sh" 2>&1)"
  rc=$?
  set -e
  assert_eq "required fail exit" "10" "${rc}"
  assert_contains "required caldera fail" "[FAIL] caldera" "${out}"
  assert_contains "required fail overall" "RESULT: FAIL" "${out}"
  rm -rf "${tmp}"
}

test_rv_exec_validator_privilege_skip() {
  local tmp script rc
  tmp="$(mktemp -d)"
  cat >"${tmp}/validator.sh" <<'EOS'
#!/usr/bin/env bash
REQUIRE_ROOT=1
exit 0
EOS
  chmod +x "${tmp}/validator.sh"
  mkdir -p "${tmp}/bin"
  cat >"${tmp}/bin/sudo" <<'MOCK'
#!/usr/bin/env bash
exit 1
MOCK
  chmod +x "${tmp}/bin/sudo"
  set +e
  rc="$(PATH="${tmp}/bin:${PATH}" bash -c "
    # shellcheck source=/dev/null
    . '${BOOT}/_runtime-validation-lib.sh'
    rv_exec_validator '${tmp}/validator.sh'
    echo \$?
  ")"
  set -e
  assert_eq "rv_exec_validator privilege skip code" "77" "${rc}"
  rm -rf "${tmp}"
}

test_host_network_privilege_vs_runtime_distinction() {
  local rc
  set +e
  rc="$(bash -c "
    # shellcheck source=/dev/null
    . '${BOOT}/_runtime-validation-lib.sh'
    if rv_text_is_ovs_permission_denied 'ovs-vsctl: cannot connect to /var/run/openvswitch/db.sock: Permission denied'; then
      echo privilege
    else
      echo no
    fi
    if rv_text_is_ovs_permission_denied 'ovs-vsctl: database connection failed (runtime)'; then
      echo conflate
    else
      echo distinct
    fi
  ")"
  set -e
  assert_contains "privilege text classified" "privilege" "${rc}"
  assert_contains "runtime text not classified as privilege" "distinct" "${rc}"
  assert_not_contains "runtime conflated with privilege" "conflate" "${rc}"
}

echo "=== test_appliance_privilege ==="
test_host_network_non_root_skips_root_probes
test_appliance_privilege_skip_required
test_appliance_strict_required_skip_fails
test_appliance_optional_fail_warns
test_appliance_optional_missing_skip
test_appliance_required_fail
test_rv_exec_validator_privilege_skip
test_host_network_privilege_vs_runtime_distinction

echo "---"
echo "passed=${PASS} failed=${FAIL}"
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
