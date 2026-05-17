#!/usr/bin/env bash
# Tests for validate-ovs-mirror.sh and ensure-ovs-mirror.sh (mocked virsh / ovs-vsctl).
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

assert_not_contains() {
  local label="$1" needle="$2" haystack="$3"
  if grep -Fq -- "${needle}" <<<"${haystack}"; then
    echo "FAIL ${label} unexpected '${needle}' in output" >&2
    FAIL=$((FAIL + 1))
  else
    echo "PASS ${label}"
    PASS=$((PASS + 1))
  fi
}

write_mock_virsh() {
  local bindir="$1"
  cat >"${bindir}/virsh" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
while [[ $# -gt 0 ]]; do
  case "$1" in
    -c)
      shift 2
      ;;
    domstate)
      case "${MOCK_SENSOR_STATE:-running}" in
        running) echo "running"; exit 0 ;;
        stopped) echo "shut off"; exit 0 ;;
        missing) echo "error: Domain not found" >&2; exit 1 ;;
        *) echo "${MOCK_SENSOR_STATE}"; exit 0 ;;
      esac
      ;;
    domiflist)
      if [[ "${MOCK_SENSOR_STATE:-running}" == "missing" ]]; then
        echo "error: Domain not found" >&2
        exit 1
      fi
      if [[ "${MOCK_DOMIFLIST_FORMAT:-legacy}" == "ovs-net" ]]; then
        cat <<EOF
Interface   Type     Source    Model    MAC
------------------------------------------------------------
${MOCK_SENSOR_IFACE:-vnet0}       ${MOCK_SENSOR_TYPE:-bridge}   ${MOCK_SENSOR_BRIDGE:-ovs-net}   ${MOCK_SENSOR_MODEL:-virtio}   ${MOCK_SENSOR_MAC:-52:54:00:9b:77:4c}
EOF
      else
        cat <<EOF
 Interface  Type     Source   Model       MAC
-----------------------------------------------------------
 ${MOCK_SENSOR_IFACE:-vnet3}  bridge   ${MOCK_SENSOR_BRIDGE:-br0}   virtio      52:54:00:00:00:01
EOF
      fi
      exit 0
      ;;
    net-dumpxml)
      case "${2:-}" in
        ovs-net)
          cat <<'EOF'
<network>
  <name>ovs-net</name>
  <bridge name='br0'/>
  <virtualport type='openvswitch'/>
</network>
EOF
          exit 0
          ;;
        *)
          echo "error: Network not found" >&2
          exit 1
          ;;
      esac
      ;;
    *)
      echo "unsupported virsh mock: $*" >&2
      exit 1
      ;;
  esac
done
echo "virsh mock: missing command" >&2
exit 1
MOCK
  chmod +x "${bindir}/virsh"
}

write_mock_ovs_vsctl() {
  local bindir="$1"
  cat >"${bindir}/ovs-vsctl" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${MOCK_OVS_PERMISSION:-0}" == "1" ]]; then
  echo "ovs-vsctl: cannot connect to /var/run/openvswitch/db.sock: Permission denied" >&2
  exit 1
fi
cmd="$*"
if [[ "${cmd}" == *" show"* || "${cmd}" == "show" ]]; then
  echo "Bridge br0"
  exit 0
fi
if [[ "${cmd}" == *"br-exists br0"* ]]; then
  if [[ "${MOCK_BR0_EXISTS:-1}" == "1" ]]; then exit 0; fi
  exit 2
fi
if [[ "${cmd}" == *"find mirror"* ]]; then
  if [[ "${MOCK_MIRROR_EXISTS:-0}" == "1" ]]; then
    echo "${MOCK_MIRROR_UUID:-uuid-mirror-1}"
  fi
  exit 0
fi
if [[ "${cmd}" == *"list mirror"* && "${cmd}" == *output_port* ]]; then
  echo "uuid-port-1"
  exit 0
fi
if [[ "${cmd}" == *"list mirror"* && "${cmd}" == *select_all* ]]; then
  echo "${MOCK_MIRROR_SELECT_ALL:-true}"
  exit 0
fi
if [[ "${cmd}" == *"list port uuid-port-1"* ]]; then
  echo "${MOCK_MIRROR_OUTPUT_PORT:-vnet3}"
  exit 0
fi
if [[ "${cmd}" == *mirrors* && "${cmd}" == *"list bridge br0"* ]]; then
  if [[ "${MOCK_MIRROR_EXISTS:-0}" == "1" ]]; then
    echo "${MOCK_MIRROR_UUID:-uuid-mirror-1}"
  fi
  exit 0
fi
if [[ "${cmd}" == *"list-ports br0"* ]]; then
  echo "${MOCK_OVS_PORTS:-${MOCK_SENSOR_IFACE:-vnet3}}"
  exit 0
fi
if [[ "${cmd}" == *"get port"* || "${cmd}" == *"create mirror"* || "${cmd}" == *"set bridge"* \
   || "${cmd}" == *"remove bridge"* || "${cmd}" == *"destroy mirror"* ]]; then
  exit 0
fi
echo "unhandled ovs-vsctl mock: ${cmd}" >&2
exit 1
MOCK
  chmod +x "${bindir}/ovs-vsctl"
}

write_mock_sudo_deny() {
  local bindir="$1"
  cat >"${bindir}/sudo" <<'MOCK'
#!/usr/bin/env bash
echo "sudo: a password is required" >&2
exit 1
MOCK
  chmod +x "${bindir}/sudo"
}

run_validate() {
  local bindir="$1"
  shift
  PATH="${bindir}:${PATH}" \
    XDR_ROOT="${ROOT}" \
    XDR_LAB_BOOTSTRAP_DIR="${BOOT}" \
    env -i \
      PATH="${bindir}:${PATH}" \
      HOME="${HOME:-/tmp}" \
      USER="${USER:-tester}" \
      SHELL="${SHELL:-/bin/bash}" \
      MOCK_SENSOR_STATE="${MOCK_SENSOR_STATE:-running}" \
      MOCK_SENSOR_IFACE="${MOCK_SENSOR_IFACE:-vnet3}" \
      MOCK_SENSOR_BRIDGE="${MOCK_SENSOR_BRIDGE:-br0}" \
      MOCK_DOMIFLIST_FORMAT="${MOCK_DOMIFLIST_FORMAT:-legacy}" \
      MOCK_SENSOR_TYPE="${MOCK_SENSOR_TYPE:-bridge}" \
      MOCK_SENSOR_MODEL="${MOCK_SENSOR_MODEL:-virtio}" \
      MOCK_SENSOR_MAC="${MOCK_SENSOR_MAC:-52:54:00:00:00:01}" \
      MOCK_MIRROR_EXISTS="${MOCK_MIRROR_EXISTS:-0}" \
      MOCK_MIRROR_UUID="${MOCK_MIRROR_UUID:-uuid-mirror-1}" \
      MOCK_MIRROR_OUTPUT_PORT="${MOCK_MIRROR_OUTPUT_PORT:-vnet3}" \
      MOCK_MIRROR_SELECT_ALL="${MOCK_MIRROR_SELECT_ALL:-true}" \
      MOCK_BR0_EXISTS="${MOCK_BR0_EXISTS:-1}" \
      MOCK_OVS_PERMISSION="${MOCK_OVS_PERMISSION:-0}" \
      MOCK_OVS_PORTS="${MOCK_OVS_PORTS:-}" \
      XDR_ROOT="${ROOT}" \
      XDR_LAB_BOOTSTRAP_DIR="${BOOT}" \
    bash "${BOOT}/validate-ovs-mirror.sh" "$@"
}

run_ensure() {
  local bindir="$1"
  shift
  env -i \
    PATH="${bindir}:${PATH}" \
    HOME="${HOME:-/tmp}" \
    USER="${USER:-tester}" \
    SHELL="${SHELL:-/bin/bash}" \
    MOCK_SENSOR_STATE="${MOCK_SENSOR_STATE:-running}" \
    MOCK_SENSOR_IFACE="${MOCK_SENSOR_IFACE:-vnet3}" \
    MOCK_SENSOR_BRIDGE="${MOCK_SENSOR_BRIDGE:-br0}" \
    MOCK_DOMIFLIST_FORMAT="${MOCK_DOMIFLIST_FORMAT:-legacy}" \
    MOCK_SENSOR_TYPE="${MOCK_SENSOR_TYPE:-bridge}" \
    MOCK_SENSOR_MODEL="${MOCK_SENSOR_MODEL:-virtio}" \
    MOCK_SENSOR_MAC="${MOCK_SENSOR_MAC:-52:54:00:00:00:01}" \
    MOCK_OVS_PORTS="${MOCK_OVS_PORTS:-}" \
    MOCK_MIRROR_EXISTS="${MOCK_MIRROR_EXISTS:-0}" \
    MOCK_MIRROR_UUID="${MOCK_MIRROR_UUID:-uuid-mirror-1}" \
    MOCK_MIRROR_OUTPUT_PORT="${MOCK_MIRROR_OUTPUT_PORT:-vnet3}" \
    MOCK_MIRROR_SELECT_ALL="${MOCK_MIRROR_SELECT_ALL:-true}" \
    MOCK_BR0_EXISTS="${MOCK_BR0_EXISTS:-1}" \
    MOCK_OVS_PERMISSION="${MOCK_OVS_PERMISSION:-0}" \
    XDR_ROOT="${ROOT}" \
    XDR_LAB_BOOTSTRAP_DIR="${BOOT}" \
    bash "${BOOT}/ensure-ovs-mirror.sh" "$@"
}

test_valid_mirror_pass() {
  local tmp out rc
  tmp="$(mktemp -d)"
  write_mock_virsh "${tmp}"
  write_mock_ovs_vsctl "${tmp}"
  MOCK_SENSOR_STATE=running MOCK_SENSOR_IFACE=vnet3 MOCK_MIRROR_EXISTS=1
  MOCK_MIRROR_OUTPUT_PORT=vnet3 MOCK_MIRROR_SELECT_ALL=true MOCK_BR0_EXISTS=1
  set +e
  out="$(run_validate "${tmp}" 2>&1)"
  rc=$?
  set -e
  unset MOCK_SENSOR_STATE MOCK_SENSOR_IFACE MOCK_MIRROR_EXISTS MOCK_MIRROR_OUTPUT_PORT MOCK_MIRROR_SELECT_ALL MOCK_BR0_EXISTS
  assert_eq "valid mirror exit" "0" "${rc}"
  assert_contains "valid mirror result" "RESULT: PASS" "${out}"
  assert_contains "valid mirror output port" "[PASS] mirror_output_port" "${out}"
  rm -rf "${tmp}"
}

test_sensor_vm_stopped() {
  local tmp out rc
  tmp="$(mktemp -d)"
  write_mock_virsh "${tmp}"
  write_mock_ovs_vsctl "${tmp}"
  export MOCK_SENSOR_STATE=stopped MOCK_BR0_EXISTS=1 MOCK_MIRROR_EXISTS=0
  set +e
  out="$(run_validate "${tmp}" 2>&1)"
  rc=$?
  set -e
  assert_eq "stopped sensor exit" "30" "${rc}"
  assert_contains "stopped sensor fail" "[FAIL] sensor_vm_running" "${out}"
  assert_contains "stopped sensor result" "RESULT: FAIL" "${out}"
  rm -rf "${tmp}"
}

test_sensor_vm_missing() {
  local tmp out rc
  tmp="$(mktemp -d)"
  write_mock_virsh "${tmp}"
  write_mock_ovs_vsctl "${tmp}"
  export MOCK_SENSOR_STATE=missing MOCK_BR0_EXISTS=1 MOCK_MIRROR_EXISTS=0
  set +e
  out="$(run_validate "${tmp}" 2>&1)"
  rc=$?
  set -e
  assert_eq "missing sensor exit" "30" "${rc}"
  assert_contains "missing sensor fail" "[FAIL] sensor_vm_running" "${out}"
  rm -rf "${tmp}"
}

test_stale_vnet() {
  local tmp out rc
  tmp="$(mktemp -d)"
  write_mock_virsh "${tmp}"
  write_mock_ovs_vsctl "${tmp}"
  export MOCK_SENSOR_STATE=running MOCK_SENSOR_IFACE=vnet5
  export MOCK_MIRROR_EXISTS=1 MOCK_MIRROR_OUTPUT_PORT=vnet3 MOCK_MIRROR_SELECT_ALL=true
  set +e
  out="$(run_validate "${tmp}" 2>&1)"
  rc=$?
  set -e
  assert_eq "stale vnet exit" "41" "${rc}"
  assert_contains "stale vnet output fail" "[FAIL] mirror_output_port" "${out}"
  rm -rf "${tmp}"
}

test_missing_mirror() {
  local tmp out rc
  tmp="$(mktemp -d)"
  write_mock_virsh "${tmp}"
  write_mock_ovs_vsctl "${tmp}"
  export MOCK_SENSOR_STATE=running MOCK_SENSOR_IFACE=vnet3 MOCK_MIRROR_EXISTS=0
  set +e
  out="$(run_validate "${tmp}" 2>&1)"
  rc=$?
  set -e
  assert_eq "missing mirror exit" "40" "${rc}"
  assert_contains "missing mirror fail" "[FAIL] mirror_exists" "${out}"
  rm -rf "${tmp}"
}

test_non_root_permission_skip() {
  local tmp out rc
  tmp="$(mktemp -d)"
  write_mock_virsh "${tmp}"
  write_mock_ovs_vsctl "${tmp}"
  write_mock_sudo_deny "${tmp}"
  MOCK_OVS_PERMISSION=1
  set +e
  out="$(env -i \
    PATH="${tmp}:${PATH}" \
    HOME="${HOME:-/tmp}" \
    MOCK_OVS_PERMISSION=1 \
    XDR_ROOT="${ROOT}" \
    bash "${BOOT}/validate-ovs-mirror.sh" 2>&1)"
  rc=$?
  set -e
  unset MOCK_OVS_PERMISSION
  assert_eq "non-root privilege exit" "77" "${rc}"
  assert_contains "non-root skip br0" "[SKIP] br0_exists" "${out}"
  assert_contains "non-root skip result" "RESULT: SKIP" "${out}"
  assert_not_contains "non-root false fail br0" "[FAIL] br0_exists" "${out}"
  assert_not_contains "non-root false fail mirror" "[FAIL] mirror_exists" "${out}"
  rm -rf "${tmp}"
}

test_ensure_idempotent_dry_run() {
  local tmp out rc
  tmp="$(mktemp -d)"
  write_mock_virsh "${tmp}"
  write_mock_ovs_vsctl "${tmp}"
  export MOCK_SENSOR_STATE=running MOCK_SENSOR_IFACE=vnet3
  export MOCK_MIRROR_EXISTS=1 MOCK_MIRROR_OUTPUT_PORT=vnet3 MOCK_MIRROR_SELECT_ALL=true
  set +e
  out="$(run_ensure "${tmp}" --dry-run 2>&1)"
  rc=$?
  set -e
  assert_eq "ensure dry-run exit" "0" "${rc}"
  assert_contains "ensure dry-run noop" "idempotent noop" "${out}"
  rm -rf "${tmp}"
}

test_sensor_vnet_via_ovs_net_source() {
  local tmp out rc
  tmp="$(mktemp -d)"
  write_mock_virsh "${tmp}"
  write_mock_ovs_vsctl "${tmp}"
  export MOCK_SENSOR_STATE=running MOCK_SENSOR_IFACE=vnet0 MOCK_SENSOR_BRIDGE=ovs-net
  export MOCK_DOMIFLIST_FORMAT=ovs-net MOCK_MIRROR_EXISTS=1
  export MOCK_MIRROR_OUTPUT_PORT=vnet0 MOCK_MIRROR_SELECT_ALL=true MOCK_BR0_EXISTS=1
  set +e
  out="$(run_validate "${tmp}" 2>&1)"
  rc=$?
  set -e
  assert_eq "ovs-net source domiflist exit" "0" "${rc}"
  assert_contains "ovs-net source domiflist pass" "RESULT: PASS" "${out}"
  assert_contains "ovs-net source vnet iface" "sensor iface=vnet0 on br0" "${out}"
  rm -rf "${tmp}"
}

test_vnet_on_domiflist_missing_on_br0() {
  local tmp out rc
  tmp="$(mktemp -d)"
  write_mock_virsh "${tmp}"
  write_mock_ovs_vsctl "${tmp}"
  export MOCK_SENSOR_STATE=running MOCK_SENSOR_IFACE=vnet0 MOCK_SENSOR_BRIDGE=ovs-net
  export MOCK_DOMIFLIST_FORMAT=ovs-net MOCK_MIRROR_EXISTS=0 MOCK_BR0_EXISTS=1
  export MOCK_OVS_PORTS=vnet3
  set +e
  out="$(run_validate "${tmp}" 2>&1)"
  rc=$?
  set -e
  assert_eq "vnet missing on br0 exit" "31" "${rc}"
  assert_contains "vnet missing on br0 detail" \
    "VM interface vnet0 found via ovs-net but not present on OVS bridge br0" "${out}"
  rm -rf "${tmp}"
}

test_appliance_ovs_mirror_summary() {
  local tmp out
  tmp="$(mktemp -d)"
  mkdir -p "${tmp}/bootstrap"
  install -m 0755 "${BOOT}/_runtime-validation-lib.sh" "${tmp}/bootstrap/"
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
  chmod +x "${tmp}/bootstrap/"*.sh
  out="$(XDR_ROOT="${tmp}" XDR_LAB_BOOTSTRAP_DIR="${tmp}/bootstrap" \
    bash "${BOOT}/validate-appliance.sh" 2>&1)"
  assert_contains "appliance ovs mirror pass" "[PASS] ovs_mirror" "${out}"
  assert_contains "appliance ovs mirror ready" "OVS mirror telemetry: READY" "${out}"
  rm -rf "${tmp}"
}

echo "=== test_validate_ovs_mirror ==="
test_valid_mirror_pass
test_sensor_vm_stopped
test_sensor_vm_missing
test_stale_vnet
test_missing_mirror
test_sensor_vnet_via_ovs_net_source
test_vnet_on_domiflist_missing_on_br0
test_non_root_permission_skip
test_ensure_idempotent_dry_run
test_appliance_ovs_mirror_summary

echo "---"
echo "passed=${PASS} failed=${FAIL}"
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
