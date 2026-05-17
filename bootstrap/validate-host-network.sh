#!/usr/bin/env bash
# Validate KVM host lab network plane (OVS br0, ovs-net, forwarding, NAT contract).
# Read-only — does not mutate host state.
#
# Usage:
#   ./bootstrap/validate-host-network.sh [--json]
#
# Exit codes:
#   0   all checks passed
#   10  br0 missing
#   11  br0 administratively DOWN
#   12  br0 missing gateway address (10.10.10.1/24)
#   20  ovs-vsctl unavailable or failed
#   21  ovs-net libvirt network missing
#   22  ovs-net inactive
#   30  net.ipv4.ip_forward disabled
#   40  lab MASQUERADE rule missing
#   41  reverse NAT contract not satisfied (nat verify)
#   13  xdr-lab-host-network.service not enabled
#   14  ensure-host-network did not complete this boot
#   50  multiple failures (lowest specific code still printed; use --json for all)
#   77  root-only probes skipped (privilege constraints; not a runtime failure)
#
set -euo pipefail

REQUIRE_ROOT=1

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

declare -a RESULTS=()
declare -a FAIL_CODES=()
OVERALL_RC=0
NON_ROOT=0

if ! rv_is_root; then
  rv_reexec_as_root_if_needed "$@" || true
  if ! rv_is_root; then
    NON_ROOT=1
  fi
fi

record() {
  local id="$1" ok="$2" detail="$3" code="$4"
  if [[ "${ok}" == "1" ]]; then
    RESULTS+=("$(rv_check_pass "${id}" "${detail}")")
  else
    RESULTS+=("$(rv_check_fail "${id}" "${detail}")")
    FAIL_CODES+=("${code}")
  fi
}

record_skip() {
  local id="$1" detail="$2"
  RESULTS+=("$(rv_check_skip "${id}" "${detail}")")
}

run_probe() {
  local id="$1" code="$2" detail_pass="$3" detail_fail="$4"
  shift 4
  local ok=1 detail="${detail_pass}" rc=0
  rv_probe_begin "${id}"
  if ! "$@"; then
    rc=$?
    ok=0
    if [[ "${rc}" -eq 124 ]]; then
      detail="${id} probe timed out (${XDR_LAB_PROBE_TIMEOUT_SECS}s)"
    else
      detail="${detail_fail}"
    fi
  fi
  rv_probe_end "${id}" "${ok}"
  record "${id}" "${ok}" "${detail}" "${code}"
}

rv_log INFO "validate-host-network start bridge=${LAB_BRIDGE} net=${LAB_OVS_NETWORK}"

# systemd persistence unit enabled
run_probe host_network_unit_enabled 13 \
  "xdr-lab-host-network.service is enabled" \
  "xdr-lab-host-network.service is not enabled (run cli-installer.sh)" \
  rv_systemd_unit_enabled xdr-lab-host-network.service

# oneshot completed this boot (boot_id marker written by ensure-host-network.sh)
rv_probe_begin ensure_host_network_boot
boot_ok=0
boot_detail="no host-network-boot.json for current boot_id"
if rv_host_network_boot_ok; then
  boot_ok=1
  boot_detail="ensure-host-network.sh completed this boot"
else
  if rv_systemd_unit_active xdr-lab-host-network.service; then
    boot_detail="xdr-lab-host-network.service active but boot marker missing/stale"
  elif rv_run_with_timeout "${XDR_LAB_SYSTEMCTL_TIMEOUT_SECS}" \
      "systemctl is-failed xdr-lab-host-network.service" \
      systemctl is-failed --quiet xdr-lab-host-network.service 2>/dev/null; then
    boot_detail="xdr-lab-host-network.service failed — see journalctl -u xdr-lab-host-network.service"
  fi
fi
rv_probe_end ensure_host_network_boot "${boot_ok}"
record ensure_host_network_boot "${boot_ok}" "${boot_detail}" 14

# br0 exists
run_probe br0_exists 10 \
  "interface ${LAB_BRIDGE} present" \
  "interface ${LAB_BRIDGE} missing" \
  rv_iface_exists

# br0 UP (OVS reports UNKNOWN when IFF_UP — both are healthy)
rv_probe_begin br0_up
br0_up_ok=0
br0_up_detail="${LAB_BRIDGE} missing — cannot test operstate"
if rv_iface_exists; then
  if rv_iface_oper_up; then
    br0_up_ok=1
    br0_up_detail="${LAB_BRIDGE} operstate UP/UNKNOWN"
  else
    br0_up_detail="${LAB_BRIDGE} is DOWN (ip -br link)"
  fi
fi
rv_probe_end br0_up "${br0_up_ok}"
record br0_up "${br0_up_ok}" "${br0_up_detail}" 11

# br0 IP
rv_probe_begin br0_gateway_ip
br0_ip_ok=0
br0_ip_detail="${LAB_BRIDGE} missing — cannot test address"
if rv_iface_exists; then
  if rv_iface_has_gateway_ip; then
    br0_ip_ok=1
    br0_ip_detail="${LAB_GATEWAY}/24 on ${LAB_BRIDGE}"
  else
    br0_ip_detail="missing inet ${LAB_GATEWAY}/24 on ${LAB_BRIDGE}"
  fi
fi
rv_probe_end br0_gateway_ip "${br0_ip_ok}"
record br0_gateway_ip "${br0_ip_ok}" "${br0_ip_detail}" 12

# ovs-vsctl
rv_probe_begin ovs_vsctl
ovs_vsctl_ok=0
ovs_bridge_ok=0
ovs_vsctl_detail="ovs-vsctl not in PATH"
ovs_bridge_detail="skipped — ovs-vsctl missing"
if [[ "${NON_ROOT}" -eq 1 ]]; then
  ovs_vsctl_detail="requires root privileges (ovs-vsctl)"
  ovs_bridge_detail="requires root privileges (ovs-vsctl)"
  record_skip ovs_vsctl "${ovs_vsctl_detail}"
  record_skip ovs_bridge "${ovs_bridge_detail}"
  rv_probe_end ovs_vsctl 0
  rv_probe_end ovs_bridge 0
else
  if command -v ovs-vsctl &>/dev/null; then
    ovs_vsctl_out=""
    ovs_rc=0
    ovs_vsctl_out="$(rv_ovs_vsctl_show)" || ovs_rc=$?
    if [[ "${ovs_rc}" -eq 0 ]]; then
      ovs_vsctl_ok=1
      ovs_vsctl_detail="ovs-vsctl show succeeded"
      if grep -q "Bridge ${LAB_BRIDGE}" <<<"${ovs_vsctl_out}"; then
        ovs_bridge_ok=1
        ovs_bridge_detail="OVS bridge ${LAB_BRIDGE} in ovs-vsctl show"
      else
        ovs_bridge_detail="OVS bridge ${LAB_BRIDGE} not listed in ovs-vsctl show"
      fi
    elif [[ "${ovs_rc}" -eq 124 ]]; then
      ovs_vsctl_detail="ovs-vsctl show timed out (${XDR_LAB_OVS_VSCTL_TIMEOUT_SECS}s)"
      ovs_bridge_detail="skipped — ovs-vsctl timed out"
    elif rv_text_is_ovs_permission_denied "${ovs_vsctl_out}"; then
      ovs_vsctl_detail="requires root privileges (ovs-vsctl)"
      ovs_bridge_detail="requires root privileges (ovs-vsctl)"
      record_skip ovs_vsctl "${ovs_vsctl_detail}"
      record_skip ovs_bridge "${ovs_bridge_detail}"
      ovs_vsctl_ok=-1
    else
      ovs_vsctl_detail="ovs-vsctl runtime error: ${ovs_vsctl_out}"
      ovs_bridge_detail="skipped — ovs-vsctl failed"
    fi
  fi
  if [[ "${ovs_vsctl_ok}" -ne -1 ]]; then
    rv_probe_end ovs_vsctl "${ovs_vsctl_ok}"
    record ovs_vsctl "${ovs_vsctl_ok}" "${ovs_vsctl_detail}" 20
    rv_probe_end ovs_bridge "${ovs_bridge_ok}"
    record ovs_bridge "${ovs_bridge_ok}" "${ovs_bridge_detail}" 20
  else
    rv_probe_end ovs_vsctl 0
    rv_probe_end ovs_bridge 0
  fi
fi

# ovs-net present / active
rv_probe_begin ovs_net_defined
ovs_defined_ok=0
ovs_active_ok=0
ovs_defined_detail="libvirt network ${LAB_OVS_NETWORK} not defined"
ovs_active_detail="skipped — ${LAB_OVS_NETWORK} missing"
virsh_rc=0
if rv_virsh_net_defined; then
  ovs_defined_ok=1
  ovs_defined_detail="libvirt network ${LAB_OVS_NETWORK} defined"
  if rv_virsh_net_active; then
    ovs_active_ok=1
    ovs_active_detail="${LAB_OVS_NETWORK} Active=yes"
  else
    virsh_rc=$?
    if [[ "${virsh_rc}" -eq 124 ]]; then
      ovs_active_detail="${LAB_OVS_NETWORK} probe timed out (${XDR_LAB_VIRSH_TIMEOUT_SECS}s)"
    else
      ovs_active_detail="${LAB_OVS_NETWORK} not active (virsh net-info)"
    fi
  fi
else
  virsh_rc=$?
  if [[ "${virsh_rc}" -eq 124 ]]; then
    ovs_defined_detail="virsh net-info ${LAB_OVS_NETWORK} timed out (${XDR_LAB_VIRSH_TIMEOUT_SECS}s)"
    ovs_active_detail="skipped — virsh timed out"
  fi
fi
rv_probe_end ovs_net_defined "${ovs_defined_ok}"
record ovs_net_defined "${ovs_defined_ok}" "${ovs_defined_detail}" 21
rv_probe_end ovs_net_active "${ovs_active_ok}"
record ovs_net_active "${ovs_active_ok}" "${ovs_active_detail}" 22

# ip_forward
run_probe ip_forward 30 \
  "net.ipv4.ip_forward=1" \
  "net.ipv4.ip_forward is not 1" \
  rv_ip_forward_enabled

# MASQUERADE
rv_probe_begin nat_masquerade
masq_ok=0
masq_detail="expected MASQUERADE for ${LAB_SUBNET_CIDR} not found"
masq_rc=0
if [[ "${NON_ROOT}" -eq 1 ]]; then
  masq_detail="requires root privileges (iptables / nat_state.py verify)"
  record_skip nat_masquerade "${masq_detail}"
  rv_probe_end nat_masquerade 0
else
  masq_out=""
  masq_out="$(rv_nat_verify_json 2>&1)" || masq_rc=$?
  if [[ "${masq_rc}" -eq 0 ]]; then
  line="$(printf '%s' "${masq_out}" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print("yes" if d.get("masquerade",{}).get("present") else "no")' 2>/dev/null || echo no)"
    if [[ "${line}" == "yes" ]]; then
      masq_ok=1
      masq_detail="POSTROUTING MASQUERADE for ${LAB_SUBNET_CIDR}"
    fi
  elif [[ "${masq_rc}" -eq 124 ]]; then
    masq_detail="nat_state.py verify timed out (${XDR_LAB_NAT_VERIFY_TIMEOUT_SECS}s)"
  elif rv_text_is_iptables_permission_denied "${masq_out}" \
      || rv_text_is_permission_denied "${masq_out}"; then
    masq_detail="requires root privileges (iptables / nat_state.py verify)"
    record_skip nat_masquerade "${masq_detail}"
    rv_probe_end nat_masquerade 0
    masq_ok=-1
  fi
  if [[ "${masq_ok}" -ne -1 ]]; then
    rv_probe_end nat_masquerade "${masq_ok}"
    record nat_masquerade "${masq_ok}" "${masq_detail}" 40
  fi
fi

# reverse NAT
rv_probe_begin reverse_nat
rev_ok=0
rev_detail="reverse NAT contract failed (nat_state.py verify)"
rev_rc=0
if [[ "${NON_ROOT}" -eq 1 ]]; then
  rev_detail="requires root privileges (iptables / nat_state.py verify)"
  record_skip reverse_nat "${rev_detail}"
  rv_probe_end reverse_nat 0
else
  rev_out=""
  helper="$(rv_nat_helper || true)"
  state_path="$(rv_nat_state_path)"
  if [[ -z "${helper}" ]]; then
    rev_detail="nat_state.py helper missing"
  else
    rev_out="$(rv_run_with_timeout "${XDR_LAB_NAT_VERIFY_TIMEOUT_SECS}" \
      "nat_state.py verify --iptables-only" \
      python3 "${helper}" verify --state-path "${state_path}" --iptables-only 2>&1)" || rev_rc=$?
    if [[ "${rev_rc}" -eq 0 ]]; then
      rev_ok=1
      rev_detail="reverse NAT contract verified (nat_state.py verify)"
    elif [[ "${rev_rc}" -eq 124 ]]; then
      rev_detail="nat_state.py verify timed out (${XDR_LAB_NAT_VERIFY_TIMEOUT_SECS}s)"
    elif rv_text_is_iptables_permission_denied "${rev_out}" \
        || rv_text_is_permission_denied "${rev_out}"; then
      rev_detail="requires root privileges (iptables / nat_state.py verify)"
      record_skip reverse_nat "${rev_detail}"
      rv_probe_end reverse_nat 0
      rev_ok=-1
    else
      rev_detail="reverse NAT runtime error (nat_state.py verify): ${rev_out}"
    fi
  fi
  if [[ "${rev_ok}" -ne -1 ]]; then
    rv_probe_end reverse_nat "${rev_ok}"
    record reverse_nat "${rev_ok}" "${rev_detail}" 41
  fi
fi

if [[ "${#FAIL_CODES[@]}" -gt 1 ]]; then
  OVERALL_RC=50
elif [[ "${#FAIL_CODES[@]}" -eq 1 ]]; then
  OVERALL_RC="${FAIL_CODES[0]}"
else
  OVERALL_RC=0
fi

if [[ "${JSON_MODE}" -eq 1 ]]; then
  python3 - "${OVERALL_RC}" "${LAB_BRIDGE}" "${LAB_OVS_NETWORK}" "${LAB_GATEWAY}" <<'PY' "${RESULTS[@]}"
import json, sys
rc = int(sys.argv[1])
bridge, net, gw = sys.argv[2], sys.argv[3], sys.argv[4]
rows = sys.argv[5:]
checks = []
for row in rows:
    status, cid, detail = row.split("\t", 2)
    checks.append({
        "id": cid,
        "ok": status == "PASS",
        "skipped": status == "SKIP",
        "detail": detail,
    })
out = {
    "script": "validate-host-network",
    "ok": rc == 0,
    "exit_code": rc,
    "bridge": bridge,
    "ovs_network": net,
    "gateway": gw,
    "checks": checks,
}
print(json.dumps(out, indent=2, sort_keys=True))
PY
else
  echo "=== validate-host-network (${LAB_BRIDGE} / ${LAB_OVS_NETWORK}) ==="
  for row in "${RESULTS[@]}"; do
    IFS=$'\t' read -r status id detail <<<"${row}"
    printf '[%s] %-18s %s\n' "${status}" "${id}" "${detail}"
  done
  echo "---"
  if [[ "${OVERALL_RC}" -eq 0 ]]; then
    echo "RESULT: PASS (exit 0)"
  else
    echo "RESULT: FAIL (exit ${OVERALL_RC})"
  fi
fi

rv_log INFO "validate-host-network finished exit=${OVERALL_RC}"
exit "${OVERALL_RC}"
