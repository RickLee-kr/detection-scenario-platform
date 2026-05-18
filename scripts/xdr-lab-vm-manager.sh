#!/usr/bin/env bash
# XDR Lab VM manager — deployment/runtime engine for KVM lab VMs.
# Invoked by aella_cli lab * only; do not embed this logic in Python.
#
# Path policy (xdr-lab-appliance):
#   * Runtime location is XDR_BASE (default /opt/xdr-lab, set by
#     cli-installer.sh). This stays the same in production.
#   * When this file is executed from the repo (xdr-lab-appliance/scripts),
#     `config/paths.sh` is sourced if present so developer overrides
#     (XDR_LAB_PROJECT_ROOT, XDR_BASE, etc.) take effect.

set -euo pipefail

_XDR_VM_MGR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${XDR_BASE:=/opt/xdr-lab}"
: "${XDR_ROOT:=${XDR_BASE}}"
: "${XDR_LAB_DEV_MODE:=0}"
if [[ "${XDR_LAB_DEV_MODE}" == "1" && -f "${_XDR_VM_MGR_DIR}/../config/paths.sh" ]]; then
  # shellcheck source=../config/paths.sh
  . "${_XDR_VM_MGR_DIR}/../config/paths.sh"
elif [[ -f "${XDR_ROOT}/config/paths.sh" ]]; then
  # shellcheck source=/dev/null
  . "${XDR_ROOT}/config/paths.sh"
elif [[ -n "${XDR_BASE:-}" && -f "${XDR_BASE}/config/paths.sh" ]]; then
  # shellcheck source=/dev/null
  . "${XDR_BASE}/config/paths.sh"
fi
# Fallback layout (older installs before paths.sh shipped under ${XDR_ROOT}/config/).
: "${XDR_BASE:=/opt/xdr-lab}"
: "${XDR_ROOT:=${XDR_BASE}}"
: "${XDR_LAB_VMS_JSON:=${XDR_ROOT}/config/lab-vms.json}"
: "${XDR_IMAGES_DIR:=${XDR_ROOT}/images}"
: "${XDR_RUNTIME_DIR:=${XDR_ROOT}/runtime}"
: "${XDR_RUNTIME_STATE_DIR:=${XDR_RUNTIME_DIR}/state}"
: "${XDR_LOGS_DIR:=${XDR_ROOT}/logs}"
: "${XDR_SCRIPTS_DIR:=${XDR_ROOT}/scripts}"

readonly XDR_BASE
readonly XDR_ROOT
readonly CFG="${XDR_LAB_VMS_JSON}"
readonly IMG="${XDR_IMAGES_DIR}"
readonly RUN="${XDR_RUNTIME_DIR}"
readonly STATED="${XDR_RUNTIME_STATE_DIR}"
readonly LOGD="${XDR_LOGS_DIR}"
readonly SCRIPTS="${XDR_SCRIPTS_DIR}"

_xdr_helper_path() {
  local name="$1"
  if [[ "${XDR_LAB_DEV_MODE}" == "1" && -f "${_XDR_VM_MGR_DIR}/${name}" ]]; then
    echo "${_XDR_VM_MGR_DIR}/${name}"
  else
    echo "${SCRIPTS}/${name}"
  fi
}

readonly STATE_HELPER="$(_xdr_helper_path vm_runtime_state.py)"
readonly MIRROR_HELPER="$(_xdr_helper_path ovs_mirror_state.py)"
readonly NAT_HELPER="$(_xdr_helper_path nat_state.py)"
readonly SNAPSHOT_HELPER="$(_xdr_helper_path snapshot_state.py)"
readonly IMAGE_DL_HELPER="$(_xdr_helper_path image_download_manager.py)"
readonly CALDERA_HELPER="$(_xdr_helper_path caldera_orchestration.py)"
readonly TOOL_HELPER="$(_xdr_helper_path tool_runtime_manager.py)"
if [[ "${XDR_LAB_DEV_MODE}" == "1" && -f "${_XDR_VM_MGR_DIR}/windows_lab_helpers.sh" ]]; then
  # shellcheck source=windows_lab_helpers.sh
  . "${_XDR_VM_MGR_DIR}/windows_lab_helpers.sh"
elif [[ -f "${SCRIPTS}/windows_lab_helpers.sh" ]]; then
  # shellcheck source=windows_lab_helpers.sh
  . "${SCRIPTS}/windows_lab_helpers.sh"
fi

# Mirror orchestration knobs (overridable via env / config/paths.sh).
: "${XDR_LAB_MIRROR_NAME:=mirror-to-sensor}"
: "${XDR_LAB_SENSOR_VM:=sensor-vm}"
: "${XDR_LAB_MIRROR_STATE_JSON:=${STATED}/mirror.json}"
: "${LAB_BRIDGE:=br0}"
: "${LAB_OVS_NETWORK:=ovs-net}"
: "${LAB_OVS_CAPTURE_NETWORK:=${LAB_OVS_NETWORK}}"
: "${LAB_GATEWAY:=10.10.10.1}"
: "${XDR_LAB_MIRROR_PROBE_TARGET:=${LAB_GATEWAY}}"

# Reverse-NAT validation knobs (read-only; NEVER mutates iptables).
# The authoritative mapping lives in nat_state.py — these are only the
# state-file path + observability defaults for the validator wrapper.
: "${XDR_LAB_NAT_STATE_JSON:=${STATED}/nat.json}"
: "${XDR_LAB_NAT_WEB_CONSOLE_VM:=windows-victim}"

# Lab snapshot aggregate (sensor-vm, victim-linux, windows-victim by default).
: "${XDR_LAB_SNAPSHOTS_JSON:=${STATED}/snapshots.json}"
: "${XDR_LAB_SNAPSHOT_VM_LIST:=sensor-vm victim-linux windows-victim}"

# Windows golden qcow2 cache + UEFI/NVRAM policy (overridable via config/paths.sh).
: "${XDR_LAB_WINDOWS_IMAGES_DIR:=${XDR_IMAGES_DIR}/windows}"
: "${XDR_LAB_WINDOWS_RECREATE_NVRAM:=0}"
: "${XDR_LAB_WINDOWS_SSH_USER:=lab}"
: "${XDR_LAB_WINDOWS_NET_MODEL:=e1000}"

# Golden image manifest (sensor-vm / victim-linux / windows-victim). Optional: when
# missing, legacy lab-vms.json URLs + public Ubuntu cloud image are used.
: "${XDR_LAB_IMAGES_MANIFEST:=${XDR_ROOT}/config/images-manifest.json}"
: "${XDR_LAB_IMAGES_STATE_JSON:=${STATED}/images.json}"

# MITRE CALDERA orchestration (BAS / adversary emulation; scripts/caldera_orchestration.py).
: "${XDR_LAB_CALDERA_STATE_JSON:=${STATED}/caldera.json}"
: "${XDR_LAB_SCENARIO_STATE_JSON:=${STATED}/scenario.json}"
: "${XDR_LAB_CALDERA_API_KEY_FILE:=/etc/xdr-lab/caldera-api-key}"

# victim-linux (Ubuntu 24.04 cloud) — authoritative base artifact (spec 003 L3 cache layout).
readonly VICTIM_LINUX_CLOUD_IMAGE_URL="${VICTIM_LINUX_CLOUD_IMAGE_URL:-https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img}"
readonly VICTIM_LINUX_CLOUD_IMAGE_BASENAME="ubuntu-24.04-server-cloudimg-amd64.img"
# Operator contract: lab bridge static address for victim-linux (override for air-gapped tests).
readonly VICTIM_LINUX_MATERIALIZED_IP="${VICTIM_LINUX_MATERIALIZED_IP:-10.10.10.20}"
readonly VICTIM_LINUX_SSH_USER="${VICTIM_LINUX_SSH_USER:-ubuntu}"
# SSH validation tries these usernames in order (override via env as space-separated list).
readonly LINUX_SERVER_SSH_USER_CANDIDATES="${LINUX_SERVER_SSH_USER_CANDIDATES:-ubuntu lab}"
# Set by validate_ssh_connectivity on success.
LINUX_SERVER_SSH_VALIDATED_USER=""
# SSH validation identity / known_hosts (override via env).
: "${XDR_LAB_VICTIM_LINUX_SSH_IDENTITY:=}"
: "${XDR_LAB_SSH_USER_KNOWN_HOSTS_FILE:=}"
: "${XDR_LAB_SSH_VALIDATION_TIMEOUT:=120}"

# Windows emergency VNC — host socat forward (QEMU stays 127.0.0.1-only).
: "${XDR_LAB_VNC_PROXY_DIR:=${XDR_RUNTIME_DIR}/vnc-proxy}"
: "${XDR_LAB_VNC_EXTERNAL_PORT:=15900}"
: "${XDR_LAB_VNC_PROXY_BIND:=0.0.0.0}"

# Windows VM browser console — websockify (127.0.0.1:6080) -> 127.0.0.1:QEMU-VNC + noVNC static UI.
: "${XDR_LAB_WEB_CONSOLE_DIR:=${XDR_RUNTIME_DIR}/web-console}"
: "${XDR_LAB_WEB_CONSOLE_PORT:=6080}"
: "${XDR_LAB_WEB_CONSOLE_BIND:=127.0.0.1}"
: "${XDR_LAB_WEB_CONSOLE_RETRY_SECS:=10}"
: "${XDR_LAB_WINDOWS_VICTIM_VNC_PORT:=5902}"
: "${XDR_LAB_WINDOWS_VICTIM_VNC_DISPLAY:=:2}"

_XDR_RUNTIME_ENV_READY=0
_XDR_READONLY_CLI=0
_XDR_LOG_WRITE_WARNED=0

init_runtime_environment() {
  if [[ "${_XDR_RUNTIME_ENV_READY}" == "1" ]]; then
    return 0
  fi
  umask 022
  mkdir -p "${IMG}" "${SCRIPTS}" "${XDR_ROOT}/config" "${RUN}" "${STATED}" "${LOGD}" \
    "${XDR_LAB_WINDOWS_IMAGES_DIR}" "${XDR_LAB_VNC_PROXY_DIR}" "${XDR_LAB_WEB_CONSOLE_DIR}"
  _XDR_RUNTIME_ENV_READY=1
}

log_structured() {
  [[ "${_XDR_READONLY_CLI}" == "1" ]] && return 0
  local level="$1"
  shift
  local logfile="${LOGD}/vm-manager.log"
  local line
  line="$(python3 - "${level}" "$*" <<'PY' 2>/dev/null || true
import json, sys, datetime
level, msg = sys.argv[1], sys.argv[2]
rec = {
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "level": level,
    "msg": msg,
}
print(json.dumps(rec, ensure_ascii=False))
PY
)"
  [[ -z "${line}" ]] && return 0
  if { printf '%s\n' "${line}" >>"${logfile}"; } 2>/dev/null; then
    return 0
  fi
  if [[ "${_XDR_LOG_WRITE_WARNED}" != "1" ]]; then
    echo "WARN: vm-manager log not writable: ${logfile} (fallback=stderr)" >&2
    _XDR_LOG_WRITE_WARNED=1
  fi
  printf '%s\n' "${line}" >&2
}

dry_run_active() {
  [[ "${XDR_LAB_DRY_RUN:-}" == "1" ]]
}

if [[ -f "${_XDR_VM_MGR_DIR}/vnc_proxy_helpers.sh" ]]; then
  # shellcheck source=vnc_proxy_helpers.sh
  . "${_XDR_VM_MGR_DIR}/vnc_proxy_helpers.sh"
elif [[ -f "${SCRIPTS}/vnc_proxy_helpers.sh" ]]; then
  # shellcheck source=/dev/null
  . "${SCRIPTS}/vnc_proxy_helpers.sh"
fi

_invoke_state_refresh() {
  local vm="$1"
  local touch_deploy="${2:-0}"
  if dry_run_active; then
    return 0
  fi
  if [[ ! -f "${STATE_HELPER}" ]]; then
    log_structured "WARN" "state_helper_missing path=${STATE_HELPER}"
    return 0
  fi
  mkdir -p "${STATED}"
  local td=( )
  if [[ "$touch_deploy" == "1" ]]; then
    td=(--touch-deploy)
  fi
  local linux_base="${IMG}/victim-linux/${VICTIM_LINUX_CLOUD_IMAGE_BASENAME}"
  if ! python3 "${STATE_HELPER}" refresh \
    --vm "$vm" \
    --cfg "$CFG" \
    --state-dir "$STATED" \
    "${td[@]}" \
    --linux-materialized-ip "${VICTIM_LINUX_MATERIALIZED_IP}" \
    --linux-ssh-user "${VICTIM_LINUX_SSH_USER}" \
    --linux-cloud-base "${linux_base}" \
    --windows-images-dir "${XDR_LAB_WINDOWS_IMAGES_DIR}" \
    --vnc-proxy-dir "${XDR_LAB_VNC_PROXY_DIR}" \
    --web-console-dir "${XDR_LAB_WEB_CONSOLE_DIR}"; then
    log_structured "WARN" "state_refresh_failed vm=${vm}"
  fi
}

# =============================================================================
# OVS mirror orchestration — state-aware (mirror.json is a refreshed cache).
#
# Mutations (ovs-vsctl) live in apply_ovs_mirror; verify/validate are read-only.
# All three respect XDR_LAB_DRY_RUN=1 and emit JSONL events to vm-manager.log.
# =============================================================================

_mirror_helper_available() {
  if [[ ! -f "${MIRROR_HELPER}" ]]; then
    log_structured "ERROR" "ovs_mirror_helper_missing path=${MIRROR_HELPER}"
    return 1
  fi
  return 0
}

_mirror_get_sensor_ip() {
  local sensor_vm="$1"
  python3 - "$CFG" "$sensor_vm" <<'PY' 2>/dev/null || true
import json, sys
path, vm = sys.argv[1], sys.argv[2]
try:
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    print(cfg.get("vms", {}).get(vm, {}).get("internal_ip", ""))
except Exception:
    print("")
PY
}

_mirror_state_field() {
  # Read a single field from mirror.json (returns empty if missing).
  local field="$1"
  if [[ ! -f "${XDR_LAB_MIRROR_STATE_JSON}" ]]; then
    echo ""
    return 0
  fi
  python3 - "${XDR_LAB_MIRROR_STATE_JSON}" "$field" <<'PY' 2>/dev/null || echo ""
import json, sys
path, key = sys.argv[1], sys.argv[2]
try:
    with open(path, "r", encoding="utf-8") as f:
        rec = json.load(f)
    v = rec.get(key, "")
    if v is None:
        print("")
    elif isinstance(v, bool):
        print("true" if v else "false")
    else:
        print(v)
except Exception:
    print("")
PY
}

_mirror_refresh_state() {
  local sensor_vm="$1" bridge="$2" mirror_name="$3" touch_applied="${4:-0}"
  local management_ip
  management_ip="$(_mirror_get_sensor_ip "$sensor_vm")"
  local args=(refresh
    --bridge "$bridge"
    --mirror-name "$mirror_name"
    --sensor-vm "$sensor_vm"
    --management-ip "$management_ip"
    --state-path "${XDR_LAB_MIRROR_STATE_JSON}"
  )
  if [[ "$touch_applied" == "1" ]]; then
    args+=(--touch-applied)
  fi
  mkdir -p "$(dirname "${XDR_LAB_MIRROR_STATE_JSON}")"
  python3 "${MIRROR_HELPER}" "${args[@]}" >/dev/null || true
  # Cascade: sensor-vm.json mirror_applied is derived from mirror.json.
  _invoke_state_refresh "$sensor_vm" 0
}

_mirror_quote_cmd() {
  printf '%q ' "$@"
  printf '\n'
}

_mirror_inspect_json() {
  local sensor_vm="$1" bridge="$2" mirror_name="$3"
  local management_ip
  management_ip="$(_mirror_get_sensor_ip "$sensor_vm")"
  python3 "${MIRROR_HELPER}" inspect \
    --bridge "${bridge}" \
    --mirror-name "${mirror_name}" \
    --sensor-vm "${sensor_vm}" \
    --management-ip "${management_ip}" 2>/dev/null || true
}

_mirror_print_diagnostics_json() {
  local json="$1"
  python3 - "$json" <<'PY' 2>/dev/null || true
import json, sys
try:
    doc = json.loads(sys.argv[1] or "{}")
except Exception:
    doc = {}
print("sensor-vm interfaces:")
topology = doc.get("sensor_topology") if isinstance(doc.get("sensor_topology"), list) else []
if topology:
    for row in topology:
        iface = row.get("interface") or "unknown"
        role = row.get("detected_role") or "unknown"
        source = row.get("source") or "unknown"
        has_ip = str(bool(row.get("has_ip"))).lower()
        attached = str(bool(row.get("attached_to_bridge"))).lower()
        print(f"  {iface} -> {role} source={source} attached_to_bridge={attached} has_ip={has_ip}")
else:
    print("  (none detected)")
print(f"selected_capture_port={doc.get('detected_capture_port') or doc.get('sensor_capture_interface') or 'unknown'}")
print(f"detected_bridge={doc.get('detected_bridge') or doc.get('bridge') or 'unknown'}")
print(f"detected_mirror_port={doc.get('output_port_name') or 'unknown'}")
print(f"current_mirrors={doc.get('current_mirrors') or '[]'}")
reasons = doc.get("verify_failure_reasons") if isinstance(doc.get("verify_failure_reasons"), list) else []
if reasons:
    print("verify_failure_reasons:")
    for reason in reasons:
        print(f"  - {reason}")
PY
}

_mirror_print_state_diagnostics() {
  if [[ ! -f "${XDR_LAB_MIRROR_STATE_JSON}" ]]; then
    echo "mirror diagnostics: ${XDR_LAB_MIRROR_STATE_JSON} missing"
    return 0
  fi
  python3 - "${XDR_LAB_MIRROR_STATE_JSON}" <<'PY' 2>/dev/null || true
import json, sys
path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
except Exception as exc:
    print(f"mirror diagnostics unavailable: {exc}")
    sys.exit(0)
print("=== OVS mirror live source-of-truth ===")
print("$ virsh domiflist " + str(doc.get("sensor_vm") or "sensor-vm"))
print(doc.get("domiflist") or "(empty)")
print("")
print("$ ovs-vsctl show")
print(doc.get("ovs_show") or "(empty)")
print("")
print(f"detected_bridge={doc.get('detected_bridge') or doc.get('bridge') or 'unknown'}")
print(f"detected_capture_port={doc.get('detected_capture_port') or 'unknown'}")
print(f"detected_mirror_port={doc.get('output_port_name') or 'unknown'}")
print(f"current_mirrors={doc.get('current_mirrors') or '[]'}")
reasons = doc.get("verify_failure_reasons") if isinstance(doc.get("verify_failure_reasons"), list) else []
if reasons:
    print("verify_failure_reasons:")
    for reason in reasons:
        print(f"  - {reason}")
PY
}

_mirror_refresh_and_print_diagnostics() {
  local sensor_vm="$1" bridge="$2" mirror_name="$3" touch_applied="${4:-0}"
  _mirror_refresh_state "$sensor_vm" "$bridge" "$mirror_name" "$touch_applied"
  _mirror_print_state_diagnostics
}

apply_ovs_mirror() {
  local sensor_vm="${1:-${XDR_LAB_SENSOR_VM}}"
  local bridge="${2:-${LAB_BRIDGE}}"
  local mirror_name="${3:-${XDR_LAB_MIRROR_NAME}}"

  log_structured "INFO" "ovs_mirror_apply_started sensor_vm=${sensor_vm} bridge=${bridge} mirror=${mirror_name}"

  if dry_run_active; then
    log_structured "INFO" "dry_run_skip ovs_mirror_apply sensor_vm=${sensor_vm} bridge=${bridge} mirror=${mirror_name}"
    if _mirror_helper_available; then
      _mirror_refresh_state "$sensor_vm" "$bridge" "$mirror_name" 0
    fi
    return 0
  fi

  _mirror_helper_available || return 1
  require_cmd ovs-vsctl
  require_cmd virsh

  echo "=== OVS mirror apply diagnostics ==="
  local inspect_json
  inspect_json="$(_mirror_inspect_json "$sensor_vm" "$bridge" "$mirror_name")"
  _mirror_print_diagnostics_json "$inspect_json"

  # 1. ovs daemon health.
  local ovs_show_err ovs_show_rc
  set +e
  ovs_show_err="$(ovs-vsctl show 2>&1 >/dev/null)"
  ovs_show_rc=$?
  set -e
  if [[ "${ovs_show_rc}" -ne 0 ]]; then
    echo "ovs-vsctl command: ovs-vsctl show"
    echo "ovs-vsctl stderr: ${ovs_show_err:-"(empty)"}"
    log_structured "ERROR" "ovs_mirror_apply_failed reason=ovs_not_running stderr=${ovs_show_err:-empty}"
    _mirror_refresh_and_print_diagnostics "$sensor_vm" "$bridge" "$mirror_name" 0
    return 1
  fi
  echo "ovs-vsctl command: ovs-vsctl show"
  echo "ovs-vsctl success: OVS is reachable"

  # 2. bridge presence.
  local br_err br_rc
  set +e
  br_err="$(ovs-vsctl br-exists "${bridge}" 2>&1 >/dev/null)"
  br_rc=$?
  set -e
  if [[ "${br_rc}" -ne 0 ]]; then
    echo "ovs-vsctl command: ovs-vsctl br-exists ${bridge}"
    echo "ovs-vsctl stderr: ${br_err:-"(empty)"}"
    log_structured "ERROR" "ovs_mirror_apply_failed reason=bridge_missing bridge=${bridge} stderr=${br_err:-empty}"
    _mirror_refresh_and_print_diagnostics "$sensor_vm" "$bridge" "$mirror_name" 0
    return 1
  fi
  echo "ovs-vsctl command: ovs-vsctl br-exists ${bridge}"
  echo "ovs-vsctl success: bridge ${bridge} exists"

  # 3. sensor-vm libvirt domain.
  if ! vm_exists "${sensor_vm}"; then
    echo "verify_failure_reasons:"
    echo "  - sensor VM ${sensor_vm} is not defined"
    log_structured "ERROR" "ovs_mirror_apply_failed reason=sensor_vm_not_defined vm=${sensor_vm}"
    _mirror_refresh_and_print_diagnostics "$sensor_vm" "$bridge" "$mirror_name" 0
    return 1
  fi

  # 4. sensor-vm must be running (vnet interface only exists while running).
  local dom_state
  dom_state="$(virsh domstate "${sensor_vm}" 2>/dev/null | tr -d '\r' || true)"
  if [[ "${dom_state}" != "running" ]]; then
    echo "verify_failure_reasons:"
    echo "  - sensor VM ${sensor_vm} is not running (state=${dom_state:-unknown})"
    log_structured "ERROR" "ovs_mirror_apply_failed reason=sensor_vm_not_running vm=${sensor_vm} state=${dom_state:-unknown}"
    _mirror_refresh_and_print_diagnostics "$sensor_vm" "$bridge" "$mirror_name" 0
    return 1
  fi

  # 5. Auto-discover the dedicated capture vnet interface from live NIC facts.
  local sensor_iface
  sensor_iface="$(python3 "${MIRROR_HELPER}" discover-iface --vm "${sensor_vm}" --bridge "${bridge}" --management-ip "$(_mirror_get_sensor_ip "$sensor_vm")" 2>/dev/null || true)"
  if [[ -z "${sensor_iface}" ]]; then
    log_structured "ERROR" "ovs_mirror_apply_failed reason=sensor_capture_iface_not_found vm=${sensor_vm} bridge=${bridge} policy=management_nic_forbidden"
    _mirror_refresh_and_print_diagnostics "$sensor_vm" "$bridge" "$mirror_name" 0
    return 1
  fi
  echo "selected_capture_port=${sensor_iface}"
  log_structured "INFO" "ovs_mirror_apply_capture_iface_discovered vm=${sensor_vm} bridge=${bridge} capture_iface=${sensor_iface}"

  # 6. Clear stale bridge mirror references before recreating the lab mirror.
  local clear_cmd=(ovs-vsctl clear bridge "${bridge}" mirrors)
  echo "ovs-vsctl command: $(_mirror_quote_cmd "${clear_cmd[@]}")"
  local clear_err clear_rc
  set +e
  clear_err="$("${clear_cmd[@]}" 2>&1 >/dev/null)"
  clear_rc=$?
  set -e
  if [[ "${clear_rc}" -ne 0 ]]; then
    echo "ovs-vsctl stderr: ${clear_err:-"(empty)"}"
    log_structured "ERROR" "ovs_mirror_apply_failed reason=ovs_vsctl_clear_failed bridge=${bridge} mirror=${mirror_name} stderr=${clear_err:-empty}"
    _mirror_refresh_and_print_diagnostics "$sensor_vm" "$bridge" "$mirror_name" 0
    return 1
  fi
  echo "ovs-vsctl success: cleared stale mirrors on ${bridge}"

  # 7. Remove any pre-existing mirror entry with our name (only ours).
  local existing_uuid
  existing_uuid="$(ovs-vsctl --columns=_uuid --bare find mirror "name=${mirror_name}" 2>/dev/null | awk 'NF {print; exit}' || true)"
  if [[ -n "${existing_uuid}" ]]; then
    log_structured "INFO" "ovs_mirror_apply_removing_existing mirror=${mirror_name} uuid=${existing_uuid}"
    ovs-vsctl --if-exists remove bridge "${bridge}" mirrors "${existing_uuid}" >/dev/null 2>&1 || true
    ovs-vsctl --if-exists destroy mirror "${existing_uuid}" >/dev/null 2>&1 || true
  fi

  # 8. Create the new mirror: select_all=true means every packet on the
  #    bridge gets copied to output-port (OVS auto-excludes the output port
  #    itself to prevent feedback loops).
  local create_cmd=(ovs-vsctl
    -- --id=@out get port "${sensor_iface}"
    -- --id=@m create mirror "name=${mirror_name}" select_all=true output-port=@out
    -- set bridge "${bridge}" mirrors=@m
  )
  echo "ovs-vsctl command: $(_mirror_quote_cmd "${create_cmd[@]}")"
  local create_err create_rc
  set +e
  create_err="$("${create_cmd[@]}" 2>&1 >/dev/null)"
  create_rc=$?
  set -e
  if [[ "${create_rc}" -ne 0 ]]; then
    echo "ovs-vsctl stderr: ${create_err:-"(empty)"}"
    log_structured "ERROR" "ovs_mirror_apply_failed reason=ovs_vsctl_create_failed bridge=${bridge} mirror=${mirror_name} iface=${sensor_iface} stderr=${create_err:-empty}"
    _mirror_refresh_and_print_diagnostics "$sensor_vm" "$bridge" "$mirror_name" 0
    return 1
  fi
  echo "ovs-vsctl success: mirror ${mirror_name} created output-port=${sensor_iface}"

  # 9. Verify the live config matches our intent before claiming success.
  if ! python3 "${MIRROR_HELPER}" inspect \
      --bridge "${bridge}" \
      --mirror-name "${mirror_name}" \
      --sensor-vm "${sensor_vm}" \
      --management-ip "$(_mirror_get_sensor_ip "$sensor_vm")" >/dev/null 2>&1; then
    log_structured "ERROR" "ovs_mirror_apply_failed reason=post_apply_inconsistent bridge=${bridge} mirror=${mirror_name} iface=${sensor_iface}"
    _mirror_refresh_and_print_diagnostics "$sensor_vm" "$bridge" "$mirror_name" 0
    return 1
  fi

  _mirror_refresh_and_print_diagnostics "$sensor_vm" "$bridge" "$mirror_name" 1
  log_structured "INFO" "ovs_mirror_apply_success sensor_vm=${sensor_vm} bridge=${bridge} mirror=${mirror_name} iface=${sensor_iface} idempotent=false"
  return 0
}

verify_ovs_mirror() {
  local sensor_vm="${1:-${XDR_LAB_SENSOR_VM}}"
  local bridge="${2:-${LAB_BRIDGE}}"
  local mirror_name="${3:-${XDR_LAB_MIRROR_NAME}}"

  log_structured "INFO" "ovs_mirror_verify_started sensor_vm=${sensor_vm} bridge=${bridge} mirror=${mirror_name}"
  _mirror_helper_available || return 1
  echo "=== OVS mirror verify diagnostics ==="

  mkdir -p "$(dirname "${XDR_LAB_MIRROR_STATE_JSON}")"
  if python3 "${MIRROR_HELPER}" verify \
      --bridge "${bridge}" \
      --mirror-name "${mirror_name}" \
      --sensor-vm "${sensor_vm}" \
      --management-ip "$(_mirror_get_sensor_ip "$sensor_vm")" \
      --state-path "${XDR_LAB_MIRROR_STATE_JSON}" >/dev/null 2>&1; then
    _invoke_state_refresh "$sensor_vm" 0
    _mirror_print_state_diagnostics
    log_structured "INFO" "ovs_mirror_verify_success sensor_vm=${sensor_vm} bridge=${bridge} mirror=${mirror_name}"
    return 0
  fi

  _invoke_state_refresh "$sensor_vm" 0
  local mirror_exists output_port_exists output_port_matches sensor_iface sensor_mgmt_iface
  mirror_exists="$(_mirror_state_field mirror_exists)"
  output_port_exists="$(_mirror_state_field output_port_exists)"
  output_port_matches="$(_mirror_state_field output_port_matches_capture)"
  sensor_iface="$(_mirror_state_field sensor_interface)"
  sensor_mgmt_iface="$(_mirror_state_field sensor_mgmt_interface)"
  _mirror_print_state_diagnostics
  log_structured "WARN" "ovs_mirror_verify_failed sensor_vm=${sensor_vm} bridge=${bridge} mirror=${mirror_name} mirror_exists=${mirror_exists} output_port_exists=${output_port_exists} output_port_matches_capture=${output_port_matches} sensor_mgmt_iface=${sensor_mgmt_iface:-unknown} sensor_capture_iface=${sensor_iface:-unknown}"
  return 1
}

validate_mirror_traffic() {
  local sensor_vm="${1:-${XDR_LAB_SENSOR_VM}}"
  local bridge="${2:-${LAB_BRIDGE}}"
  local mirror_name="${3:-${XDR_LAB_MIRROR_NAME}}"
  local probe_target="${4:-${XDR_LAB_MIRROR_PROBE_TARGET}}"

  log_structured "INFO" "ovs_mirror_traffic_validation_started sensor_vm=${sensor_vm} bridge=${bridge} mirror=${mirror_name} probe_target=${probe_target}"

  if dry_run_active; then
    log_structured "INFO" "dry_run_skip ovs_mirror_traffic_validation sensor_vm=${sensor_vm}"
    return 0
  fi

  _mirror_helper_available || return 1

  # Refresh first so we read the freshest sensor_interface from mirror.json.
  _mirror_refresh_state "$sensor_vm" "$bridge" "$mirror_name" 0

  local consistent sensor_iface sensor_ip
  consistent="$(_mirror_state_field consistent)"
  sensor_iface="$(_mirror_state_field sensor_interface)"
  sensor_ip="$(_mirror_get_sensor_ip "$sensor_vm")"

  if [[ "${consistent}" != "true" ]]; then
    log_structured "WARN" "ovs_mirror_traffic_validation_skipped reason=mirror_inconsistent sensor_vm=${sensor_vm} bridge=${bridge} mirror=${mirror_name}"
    return 1
  fi
  if [[ -z "${sensor_iface}" ]]; then
    log_structured "WARN" "ovs_mirror_traffic_validation_skipped reason=sensor_iface_unknown sensor_vm=${sensor_vm}"
    return 1
  fi
  if [[ -z "${sensor_ip}" ]]; then
    log_structured "WARN" "ovs_mirror_traffic_validation_skipped reason=sensor_ip_unknown sensor_vm=${sensor_vm}"
    return 1
  fi

  local sensor_user="${XDR_LAB_SENSOR_SSH_USER:-ubuntu}"
  local pkt_count="${XDR_LAB_MIRROR_PACKET_COUNT:-5}"
  local td_timeout="${XDR_LAB_MIRROR_TCPDUMP_TIMEOUT:-20}"

  local out_json
  if ! out_json="$(python3 "${MIRROR_HELPER}" validate-traffic \
        --sensor-ip "${sensor_ip}" \
        --sensor-user "${sensor_user}" \
        --sensor-iface "${sensor_iface}" \
        --probe-target "${probe_target}" \
        --probe-source host \
        --packet-count "${pkt_count}" \
        --tcpdump-timeout "${td_timeout}" 2>/dev/null)"; then
    local reason
    reason="$(printf '%s' "${out_json}" | python3 -c 'import sys,json; d=json.loads(sys.stdin.read() or "{}"); print(d.get("reason",""))' 2>/dev/null || true)"
    log_structured "WARN" "ovs_mirror_traffic_validation_failed sensor_vm=${sensor_vm} sensor_ip=${sensor_ip} iface=${sensor_iface} probe_target=${probe_target} reason=${reason:-unknown}"
    return 1
  fi

  local lines
  lines="$(printf '%s' "${out_json}" | python3 -c 'import sys,json; d=json.loads(sys.stdin.read() or "{}"); print(d.get("tcpdump_lines",0))' 2>/dev/null || echo 0)"
  log_structured "INFO" "ovs_mirror_traffic_validation_success sensor_vm=${sensor_vm} sensor_ip=${sensor_ip} iface=${sensor_iface} probe_target=${probe_target} tcpdump_lines=${lines}"
  return 0
}

show_mirror_status() {
  local sensor_vm="${1:-${XDR_LAB_SENSOR_VM}}"
  local bridge="${2:-${LAB_BRIDGE}}"
  local mirror_name="${3:-${XDR_LAB_MIRROR_NAME}}"
  _mirror_helper_available || return 1
  _mirror_refresh_state "$sensor_vm" "$bridge" "$mirror_name" 0
  if [[ -f "${XDR_LAB_MIRROR_STATE_JSON}" ]]; then
    cat "${XDR_LAB_MIRROR_STATE_JSON}"
  fi
}

mirror_dispatch() {
  local sub="${1:-}"
  shift || true
  local sensor_vm="${1:-${XDR_LAB_SENSOR_VM}}"

  case "${sub}" in
    apply)
      apply_ovs_mirror "${sensor_vm}" "${LAB_BRIDGE}" "${XDR_LAB_MIRROR_NAME}"
      ;;
    verify)
      verify_ovs_mirror "${sensor_vm}" "${LAB_BRIDGE}" "${XDR_LAB_MIRROR_NAME}"
      ;;
    validate-traffic)
      validate_mirror_traffic "${sensor_vm}" "${LAB_BRIDGE}" "${XDR_LAB_MIRROR_NAME}" \
        "${XDR_LAB_MIRROR_PROBE_TARGET}"
      ;;
    status)
      show_mirror_status "${sensor_vm}" "${LAB_BRIDGE}" "${XDR_LAB_MIRROR_NAME}"
      ;;
    *)
      echo "Usage: $(basename "$0") mirror <apply|verify|validate-traffic|status> [sensor-vm]" >&2
      return 2
      ;;
  esac
}

# =============================================================================
# Reverse-NAT validation — READ-ONLY against the host's iptables.
#
# The KVM Host Golden Image is the single source of truth for the lab's
# reverse-NAT policy (MASQUERADE on POSTROUTING for 10.10.10.0/24, the
# DNAT triplet on PREROUTING, and the FORWARD ACCEPT for 10.10.10.0/24).
# This dispatcher NEVER calls iptables with -F/-X/-A/-I/-D/-P (constitution
# P-13). It only reads via `iptables -S` and projects the result into
# ${XDR_LAB_NAT_STATE_JSON} via nat_state.py.
#
# Dry-run policy: `nat verify` and `nat status` are read-only by design,
# so they run unchanged when XDR_LAB_DRY_RUN=1.
# =============================================================================

_nat_helper_available() {
  if [[ ! -f "${NAT_HELPER}" ]]; then
    log_structured "ERROR" "nat_helper_missing path=${NAT_HELPER}"
    return 1
  fi
  return 0
}

verify_nat_state() {
  local iptables_only="${1:-0}"
  log_structured "INFO" "nat_verify_begin state_path=${XDR_LAB_NAT_STATE_JSON} iptables_only=${iptables_only}"
  _nat_helper_available || return 1
  mkdir -p "$(dirname "${XDR_LAB_NAT_STATE_JSON}")"

  # NOTE: `if cmd; then ... fi` masks cmd's exit code in the implicit else
  # path (the `if` evaluates to 0 when no else runs). Capture rc explicitly.
  local rc=0
  local -a nat_verify_args=(
    verify
    --state-path "${XDR_LAB_NAT_STATE_JSON}"
    --web-console-port "${XDR_LAB_WEB_CONSOLE_PORT}"
    --web-console-dir "${XDR_LAB_WEB_CONSOLE_DIR}"
    --web-console-vm "${XDR_LAB_NAT_WEB_CONSOLE_VM}"
  )
  if [[ "${iptables_only}" == "1" ]]; then
    nat_verify_args+=(--iptables-only)
  fi
  python3 "${NAT_HELPER}" "${nat_verify_args[@]}" >/dev/null 2>&1 || rc=$?

  if [[ "${rc}" -eq 0 ]]; then
    log_structured "INFO" "nat_verify_ok state_path=${XDR_LAB_NAT_STATE_JSON}"
    return 0
  fi

  # Surface a structured per-defect summary so operators don't have to grep
  # the JSON. The helper has already (re)written nat.json, so we read fields
  # off disk rather than re-running the probe.
  local iptables_ok masq_present fwd_present web_present missing
  iptables_ok="$(_nat_state_field iptables_readable)"
  masq_present="$(_nat_state_field_dotted masquerade.present)"
  fwd_present="$(_nat_state_field_dotted forward.present)"
  web_present="$(_nat_state_field_dotted web_console.present)"
  missing="$(_nat_state_field_list missing)"

  log_structured "WARN" "nat_verify_failed iptables_readable=${iptables_ok} masquerade_present=${masq_present} forward_present=${fwd_present} web_console_listen=${web_present} missing=[${missing}]"
  _nat_verify_emit_remediation "${missing}"
  return "${rc}"
}

# Human-oriented hints on stderr (structured log above remains SIEM-safe).
_nat_verify_emit_remediation() {
  local missing="${1:-}"
  local wc="${XDR_LAB_WEB_CONSOLE_PORT:-6080}"
  echo "" >&2
  echo "=== NAT verify failed — operator actions ===" >&2
  echo "Golden-Image contract (host iptables, read-only check):" >&2
  echo "  • POSTROUTING: MASQUERADE for 10.10.10.0/24" >&2
  echo "  • PREROUTING DNAT (tcp): 1022→10.10.10.10:22, 2022→10.10.10.20:22, 3389→10.10.10.30:3389" >&2
  echo "  • FORWARD: ACCEPT rules covering 10.10.10.0/24 (lab traffic)" >&2
  echo "  • Web console (optional): per-VM websockify — see docs/web-console.md (PORT_MAP 6081/6082)" >&2
  echo "" >&2
  echo "Inventory must match the same external ports (see: xdr-lab-vm-manager.sh access):" >&2
  echo "  sensor-vm 10.10.10.10 ssh→1022 | victim-linux 10.10.10.20 ssh→2022 | windows-victim 10.10.10.30 rdp→3389" >&2
  echo "" >&2
  echo "missing[] from ${XDR_LAB_NAT_STATE_JSON}: [${missing}]" >&2
  case ",${missing}," in
    *",iptables_unreadable,"*)
      echo "• iptables_unreadable: run the verify as root (sudo) or fix capabilities; confirm iptables is installed." >&2
      ;;
  esac
  case ",${missing}," in
    *",masquerade,"*)
      echo "• masquerade: restore POSTROUTING MASQUERADE for 10.10.10.0/24 (lab egress SNAT)." >&2
      ;;
  esac
  case ",${missing}," in
    *",forward_accept,"*)
      echo "• forward_accept: allow FORWARD for the lab subnet toward br0 / lab guests (see Golden Image filter rules)." >&2
      ;;
  esac
  case ",${missing}," in
    *",sensor-vm-ssh,"*|*",victim-linux-ssh,"*|*",windows-victim-rdp,"*)
      echo "• DNAT (*-ssh / windows-victim-rdp): rule missing OR --to-destination does not match the contract IP:port." >&2
      echo "  Re-apply the KVM host NAT bundle from the Golden Image / host bootstrap procedure (iptables PREROUTING DNAT)." >&2
      echo "  If the rule points at an old internal IP, update the host DNAT to the canonical lab IPs above." >&2
      ;;
  esac
  case ",${missing}," in
    *",web_console_listen_"*)
      echo "• web_console (optional): aella_cli lab web-console start <vm> — see docs/web-console.md (recommended PORT_MAP 6081/6082)." >&2
      echo "  Core NAT only: nat verify --iptables-only   |   Web console: bootstrap/validate-web-console.sh" >&2
      ;;
  esac
  echo "" >&2
  echo "Re-check: bash scripts/xdr-lab-vm-manager.sh nat status   # prints ${XDR_LAB_NAT_STATE_JSON}" >&2
  echo "Compare:   bash scripts/xdr-lab-vm-manager.sh access     # inventory vs external IP" >&2
}

show_nat_status() {
  log_structured "INFO" "nat_status_begin state_path=${XDR_LAB_NAT_STATE_JSON}"
  _nat_helper_available || return 1
  mkdir -p "$(dirname "${XDR_LAB_NAT_STATE_JSON}")"

  # Refresh first so `status` always reflects the current host reality.
  # The refresh subcommand never mutates iptables; XDR_LAB_DRY_RUN is
  # irrelevant here.
  python3 "${NAT_HELPER}" refresh \
    --state-path "${XDR_LAB_NAT_STATE_JSON}" \
    --web-console-port "${XDR_LAB_WEB_CONSOLE_PORT}" \
    --web-console-dir "${XDR_LAB_WEB_CONSOLE_DIR}" \
    --web-console-vm "${XDR_LAB_NAT_WEB_CONSOLE_VM}" >/dev/null 2>&1 || \
    log_structured "WARN" "nat_status_refresh_failed state_path=${XDR_LAB_NAT_STATE_JSON}"

  if [[ -f "${XDR_LAB_NAT_STATE_JSON}" ]]; then
    cat "${XDR_LAB_NAT_STATE_JSON}"
  else
    echo "{\"error\":\"nat.json missing and refresh failed\"}"
  fi
  log_structured "INFO" "nat_status_end state_path=${XDR_LAB_NAT_STATE_JSON}"
}

_nat_state_field() {
  local field="$1"
  if [[ ! -f "${XDR_LAB_NAT_STATE_JSON}" ]]; then
    echo ""
    return 0
  fi
  python3 - "${XDR_LAB_NAT_STATE_JSON}" "$field" <<'PY' 2>/dev/null || echo ""
import json, sys
path, key = sys.argv[1], sys.argv[2]
try:
    with open(path, "r", encoding="utf-8") as f:
        rec = json.load(f)
    v = rec.get(key, "")
    if v is None:
        print("")
    elif isinstance(v, bool):
        print("true" if v else "false")
    else:
        print(v)
except Exception:
    print("")
PY
}

_nat_state_field_dotted() {
  # Read a single dotted field path (e.g. "masquerade.present").
  local path="$1"
  if [[ ! -f "${XDR_LAB_NAT_STATE_JSON}" ]]; then
    echo ""
    return 0
  fi
  python3 - "${XDR_LAB_NAT_STATE_JSON}" "$path" <<'PY' 2>/dev/null || echo ""
import json, sys
file_path, dotted = sys.argv[1], sys.argv[2]
try:
    with open(file_path, "r", encoding="utf-8") as f:
        rec = json.load(f)
    cur = rec
    for part in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = None
            break
    if cur is None:
        print("")
    elif isinstance(cur, bool):
        print("true" if cur else "false")
    else:
        print(cur)
except Exception:
    print("")
PY
}

_nat_state_field_list() {
  # Read a list field and join with commas (for structured log embedding).
  local field="$1"
  if [[ ! -f "${XDR_LAB_NAT_STATE_JSON}" ]]; then
    echo ""
    return 0
  fi
  python3 - "${XDR_LAB_NAT_STATE_JSON}" "$field" <<'PY' 2>/dev/null || echo ""
import json, sys
path, key = sys.argv[1], sys.argv[2]
try:
    with open(path, "r", encoding="utf-8") as f:
        rec = json.load(f)
    v = rec.get(key, [])
    if isinstance(v, list):
        print(",".join(str(x) for x in v))
    elif v is None:
        print("")
    else:
        print(str(v))
except Exception:
    print("")
PY
}

nat_dispatch() {
  local sub="${1:-}"
  shift || true
  case "${sub}" in
    verify)
      local iptables_only=0
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --iptables-only) iptables_only=1 ;;
          *)
            echo "Usage: $(basename "$0") nat verify [--iptables-only]" >&2
            return 2
            ;;
        esac
        shift
      done
      verify_nat_state "${iptables_only}"
      ;;
    status)
      show_nat_status
      ;;
    *)
      echo "Usage: $(basename "$0") nat <verify|status>" >&2
      echo "  verify [--iptables-only]  Probe iptables (read-only); optional flag" >&2
      echo "          skips web-console listener (core DNAT contract only)." >&2
      echo "  status  Refresh and print runtime/state/nat.json." >&2
      return 2
      ;;
  esac
}

validate_all_vms() {
  local target="${1:-all}"
  require_cmd virsh
  local v exp dom_st
  for v in $(list_vms); do
    if [[ "$target" != "all" && "$target" != "$v" ]]; then
      continue
    fi
    log_structured "INFO" "validate_all_vms_begin vm=${v}"
    local vtype
    vtype="$(python3 - "$CFG" "$v" <<'PY'
import json, sys
path, vm = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as f:
    cfg = json.load(f)
print(cfg["vms"][vm].get("type", ""))
PY
)"
    if [[ "$vtype" == "windows" ]]; then
      validate_windows_vm "$v"
      log_structured "INFO" "validate_all_vms_end vm=${v}"
      continue
    fi
    dom_st="$(virsh domstate "$v" 2>/dev/null | tr -d '\r' || true)"
    log_structured "INFO" "validate_virsh_domstate vm=${v} state=${dom_st:-unknown}"
    virsh domifaddr "$v" --source lease 2>/dev/null || true
    virsh domifaddr "$v" --source agent 2>/dev/null || true
    exp="$(get_vm_field "$v" internal_ip)"
    if [[ "$v" == "victim-linux" ]]; then
      exp="${VICTIM_LINUX_MATERIALIZED_IP}"
    fi
    if [[ -n "${exp}" ]] && command -v ping >/dev/null 2>&1; then
      if ping -c 1 -W 2 "$exp" >/dev/null 2>&1; then
        log_structured "INFO" "validate_ping_ok vm=${v} ip=${exp}"
      else
        log_structured "WARN" "validate_ping_fail vm=${v} ip=${exp}"
      fi
    fi
    _invoke_state_refresh "$v" 0
    log_structured "INFO" "validate_ssh_batch_observed vm=${v} (see ${STATED}/${v}.json ssh_reachable)"
    if [[ "$v" == "victim-linux" ]]; then
      if [[ -f "${STATE_HELPER}" ]] && python3 "${STATE_HELPER}" cloud-init-done \
        --ip "${VICTIM_LINUX_MATERIALIZED_IP}" \
        --user "${VICTIM_LINUX_SSH_USER}"; then
        log_structured "INFO" "validate_cloud_init_boot_finished vm=${v}"
      else
        log_structured "WARN" "validate_cloud_init_not_finished vm=${v} ip=${VICTIM_LINUX_MATERIALIZED_IP}"
      fi
    fi
    log_structured "INFO" "validate_all_vms_end vm=${v}"
  done
}

die() {
  echo "ERROR: $*" >&2
  log_structured "ERROR" "$*"
  exit 1
}

_known_cli_actions=(
  download deploy start stop destroy status validate access cleanup
  snapshot scenario runtime mirror nat vnc-proxy web-console windows-console images vm sensor atomic tools
)

is_known_cli_action() {
  local want="$1" x
  for x in "${_known_cli_actions[@]}"; do
    [[ "$x" == "$want" ]] && return 0
  done
  return 1
}

# Read-only CLI paths must not mkdir, log, or touch runtime state.
needs_runtime_environment() {
  local action="$1"
  shift || true
  if dry_run_active; then
    return 1
  fi
  case "$action" in
    status|access)
      return 1
      ;;
    images)
      # Bare `images` defaults to status in images_cli_dispatch.
      [[ $# -eq 0 || "${1:-}" == "status" ]] && return 1
      ;;
    sensor)
      [[ "${1:-}" == "verify" ]] && return 1
      ;;
    scenario)
      [[ $# -eq 0 ]] && return 1
      ;;
  esac
  return 0
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

print_libvirt_network_topology() {
  echo "=== libvirt network topology ==="
  echo "libvirt network: ${LAB_OVS_NETWORK}"
  echo "ovs bridge: ${LAB_BRIDGE}"
  echo "attach mode: libvirt-network"
}

validate_libvirt_ovs_network_pre_deploy() {
  require_cmd virsh
  local net_info active
  if ! net_info="$(virsh net-info "${LAB_OVS_NETWORK}" 2>&1)"; then
    echo "ERROR:" >&2
    echo "libvirt network '${LAB_OVS_NETWORK}' is not defined." >&2
    echo "" >&2
    echo "Fix:" >&2
    echo "  sudo virsh net-define ${XDR_ROOT}/config/ovs-net.xml" >&2
    echo "  sudo virsh net-start ${LAB_OVS_NETWORK}" >&2
    echo "  sudo virsh net-autostart ${LAB_OVS_NETWORK}" >&2
    die "libvirt network '${LAB_OVS_NETWORK}' not defined"
  fi
  active="$(printf '%s\n' "${net_info}" | awk -F: '/^Active:/ {gsub(/ /,"",$2); print $2}')"
  if [[ "${active}" != "yes" ]]; then
    echo "ERROR:" >&2
    echo "libvirt network '${LAB_OVS_NETWORK}' not active." >&2
    echo "" >&2
    echo "Fix:" >&2
    echo "  sudo virsh net-start ${LAB_OVS_NETWORK}" >&2
    echo "  sudo virsh net-autostart ${LAB_OVS_NETWORK}" >&2
    die "libvirt network '${LAB_OVS_NETWORK}' not active"
  fi
  log_structured "INFO" "validate_libvirt_ovs_network_ok net=${LAB_OVS_NETWORK} active=yes"
}

# Single authoritative virt-install --network argument builder.
# Emits two lines: --network and network=<libvirt-net>,model=<model>
build_libvirt_network_args() {
  local model="${1:-virtio}"
  echo "--network"
  echo "network=${LAB_OVS_NETWORK},model=${model}"
}

virt_install_libvirt_network() {
  local net_model="$1"
  shift
  local -a net_args=()
  mapfile -t net_args < <(build_libvirt_network_args "${net_model}")
  virt-install "${@}" "${net_args[@]}"
}

validate_vm_libvirt_network_attach() {
  local vm="$1"
  local domiflist source iface ports
  require_cmd virsh

  echo "=== deploy network validation (${vm}) ==="
  domiflist="$(virsh domiflist "${vm}" 2>/dev/null || true)"
  echo "${domiflist}"

  source="$(printf '%s\n' "${domiflist}" | awk 'NR>2 && $1 ~ /^vnet/ {print $3; exit}')"
  if [[ "${source}" != "${LAB_OVS_NETWORK}" ]]; then
    log_structured "ERROR" "validate_vm_libvirt_network_attach_failed vm=${vm} source=${source:-unknown} expected=${LAB_OVS_NETWORK}"
    return 1
  fi
  log_structured "INFO" "validate_vm_libvirt_network_attach_ok vm=${vm} source=${LAB_OVS_NETWORK}"

  iface="$(printf '%s\n' "${domiflist}" | awk 'NR>2 && $1 ~ /^vnet/ {print $1; exit}')"
  if [[ -z "${iface}" ]]; then
    log_structured "WARN" "validate_vm_ovs_port_missing vm=${vm} reason=no_vnet_in_domiflist"
    return 1
  fi

  if command -v ovs-vsctl &>/dev/null; then
    ports="$(ovs-vsctl list-ports "${LAB_BRIDGE}" 2>/dev/null || true)"
    echo "=== ovs bridge ports (${LAB_BRIDGE}) ==="
    echo "${ports}"
    if ! grep -qxF "${iface}" <<<"${ports}"; then
      log_structured "WARN" "validate_vm_ovs_port_missing vm=${vm} iface=${iface} bridge=${LAB_BRIDGE}"
      return 1
    fi
    log_structured "INFO" "validate_vm_ovs_port_ok vm=${vm} iface=${iface} bridge=${LAB_BRIDGE}"
  fi
  return 0
}

list_vms() {
  python3 - "$CFG" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    cfg = json.load(f)
print(" ".join(sorted(cfg.get("vms", {}).keys())))
PY
}

get_vm_field() {
  local vm="$1" key="$2"
  python3 - "$CFG" "$vm" "$key" <<'PY'
import json, sys
path, vm, key = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, "r", encoding="utf-8") as f:
    cfg = json.load(f)
val = cfg["vms"][vm][key]
if isinstance(val, (dict, list)):
    print(json.dumps(val, separators=(",", ":")))
else:
    print(val)
PY
}

# Relative paths in lab-vms.json (e.g. sensor_cache_dir) are rooted at ${XDR_ROOT}.
lab_resolve_path() {
  local p="$1"
  if [[ "$p" == /* ]]; then
    printf '%s' "$p"
  else
    printf '%s/%s' "${XDR_ROOT}" "${p#./}"
  fi
}

# Optional VM JSON field (returns default if missing / unreadable).
vm_json_field_optional() {
  local vm="$1" key="$2" default="${3:-}"
  python3 - "$CFG" "$vm" "$key" "$default" <<'PY'
import json, sys
path, vm, key, default = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
try:
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    v = cfg.get("vms", {}).get(vm, {})
    if key not in v or v[key] is None:
        print(default)
    elif isinstance(v[key], (dict, list)):
        print(json.dumps(v[key], separators=(",", ":")))
    else:
        print(v[key])
except Exception:
    print(default)
PY
}

net_global_field() {
  local key="$1"
  python3 - "$CFG" "$key" <<'PY'
import json, sys
path, key = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as f:
    cfg = json.load(f)
print(cfg.get("network", {}).get(key, ""))
PY
}

require_positive_int_at_least() {
  local label="$1" value="$2" minimum="$3"
  if ! [[ "${value}" =~ ^[0-9]+$ ]] || [[ "${value}" -lt "${minimum}" ]]; then
    die "${label} must be an integer >= ${minimum}; got ${value:-<empty>}"
  fi
}

sensor_capture_network_for() {
  local vm="$1"
  python3 - "$CFG" "$vm" "${LAB_OVS_CAPTURE_NETWORK}" <<'PY'
import json, sys
path, vm, default = sys.argv[1:4]
try:
    cfg = json.load(open(path, encoding="utf-8"))
    nics = ((cfg.get("vms") or {}).get(vm) or {}).get("nics") or {}
    capture = nics.get("capture_nic") or {}
    print(capture.get("network") or default)
except Exception:
    print(default)
PY
}

sensor_vnet_count() {
  local vm="$1"
  virsh domiflist "${vm}" 2>/dev/null | awk 'NR>2 && $1 ~ /^vnet/ {n++} END {print n+0}'
}

ensure_sensor_capture_nic() {
  local vm="$1"
  local capture_network="${2:-$(sensor_capture_network_for "$vm")}"
  local count state attach_args=()

  count="$(sensor_vnet_count "$vm")"
  if [[ "${count}" -ge 2 ]]; then
    log_structured "INFO" "sensor_capture_nic_present vm=${vm} vnet_count=${count} capture_network=${capture_network}"
    return 0
  fi

  if ! virsh net-info "${capture_network}" >/dev/null 2>&1; then
    die "Sensor capture libvirt network '${capture_network}' is not defined; capture NIC is required and management NIC mirror reuse is unsupported"
  fi

  state="$(virsh domstate "${vm}" 2>/dev/null | tr -d '\r' || true)"
  attach_args=(--domain "$vm" --type network --source "$capture_network" --model virtio --config)
  if [[ "${state}" == "running" ]]; then
    attach_args+=(--live)
  fi
  log_structured "INFO" "sensor_capture_nic_attach vm=${vm} network=${capture_network} state=${state:-unknown}"
  virsh attach-interface "${attach_args[@]}" >/dev/null

  count="$(sensor_vnet_count "$vm")"
  if [[ "${count}" -lt 2 ]]; then
    die "Sensor capture NIC attach did not produce a second vnet interface for ${vm}"
  fi
  log_structured "INFO" "sensor_capture_nic_attached vm=${vm} network=${capture_network} vnet_count=${count}"
}

get_lab_subnet_cidr() {
  python3 - "$CFG" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    cfg = json.load(f)
print(cfg.get("network", {}).get("lab_subnet_cidr", "10.10.10.0/24"))
PY
}

download_to() {
  local url="$1" dest="$2"
  if config_url_is_placeholder "${url}"; then
    die "CONFIG_PLACEHOLDER_ERROR: refusing to download placeholder URL: ${url}. Replace config/lab-vms.json or config/images-manifest.json with real artifact URLs, or install artifacts manually."
  fi
  mkdir -p "$(dirname "$dest")"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --retry-delay 2 -o "$dest" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$dest" "$url"
  else
    die "Neither curl nor wget is available for downloads"
  fi
}

config_url_is_placeholder() {
  local url="${1:-}" lowered
  lowered="$(printf '%s' "${url}" | tr '[:upper:]' '[:lower:]')"
  [[ -z "${url}" || "${lowered}" == *"replace_me.example.invalid"* || "${lowered}" == *"replace_me"* || "${lowered}" == *"placeholder"* ]]
}

validate_stellar_download_env() {
  local env_file="${XDR_LAB_STELLAR_DOWNLOAD_ENV:-/etc/xdr-lab/stellar-download.env}"
  if [[ -n "${STELLAR_DOWNLOAD_USER:-}" && -n "${STELLAR_DOWNLOAD_PASSWORD:-}" ]]; then
    return 0
  fi
  [[ -f "${env_file}" ]] || die "Stellar download credentials missing: set STELLAR_DOWNLOAD_USER/STELLAR_DOWNLOAD_PASSWORD or create ${env_file} (owner root:xdr-lab, mode 0640 recommended)"
  local mode owner group current_user
  mode="$(stat -c '%a' "${env_file}" 2>/dev/null || echo "")"
  owner="$(stat -c '%U' "${env_file}" 2>/dev/null || echo "")"
  group="$(stat -c '%G' "${env_file}" 2>/dev/null || echo "")"
  current_user="$(id -un 2>/dev/null || echo "${USER:-unknown}")"
  if [[ -n "${owner}" && "${owner}" != "root" ]]; then
    log_structured "WARN" "stellar_download_env_owner owner=${owner} path=${env_file} recommendation=root"
  fi
  if [[ -n "${group}" && "${group}" != "xdr-lab" ]]; then
    log_structured "WARN" "stellar_download_env_group group=${group} path=${env_file} recommendation=xdr-lab"
  fi
  if [[ "${mode}" =~ ^[0-7]+$ ]] && [[ "${mode}" != "640" ]]; then
    log_structured "WARN" "stellar_download_env_permissions mode=${mode} path=${env_file} recommendation=0640"
  fi
  if [[ ! -r "${env_file}" ]]; then
    die "Stellar download credentials file exists but is not readable; current_user=${current_user}; credential_file=${env_file}; required_owner_group=root:xdr-lab; required_mode=0640; remediation=Run installer or: sudo chown root:xdr-lab ${env_file} && sudo chmod 640 ${env_file} && newgrp xdr-lab; env_override=export STELLAR_DOWNLOAD_USER/STELLAR_DOWNLOAD_PASSWORD for this command"
  fi
}

# -----------------------------------------------------------------------------
# images-manifest.json — download / verify / zstd / state (images.json)
# Opt-in: set "enabled": true in the manifest or XDR_LAB_USE_IMAGE_MANIFEST=1
# so existing installs keep legacy lab-vms.json URLs until operators opt in.
# -----------------------------------------------------------------------------

manifest_enabled() {
  [[ -f "${XDR_LAB_IMAGES_MANIFEST}" && -f "${IMAGE_DL_HELPER}" ]] || return 1
  if [[ "${XDR_LAB_USE_IMAGE_MANIFEST:-}" == "1" ]]; then
    return 0
  fi
  python3 - "${XDR_LAB_IMAGES_MANIFEST}" <<'PY'
import json, sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    d = json.load(f)
sys.exit(0 if d.get("enabled") is True else 1)
PY
}

manifest_has_role() {
  local vm="$1"
  manifest_enabled || return 1
  python3 "${IMAGE_DL_HELPER}" \
    --manifest "${XDR_LAB_IMAGES_MANIFEST}" \
    --state "${XDR_LAB_IMAGES_STATE_JSON}" \
    --xdr-root "${XDR_ROOT}" \
    has-role --role "${vm}"
}

image_manifest_sync() {
  local select="${1:-MANIFEST_ALL}"
  manifest_enabled || return 0
  require_cmd python3
  if [[ "${select}" == "sensor-vm" ]]; then
    validate_stellar_download_env
  fi
  if manifest_selection_has_placeholder_url "${select}"; then
    die "CONFIG_PLACEHOLDER_ERROR: refusing manifest download because ${XDR_LAB_IMAGES_MANIFEST} contains REPLACE_ME.example.invalid placeholder URLs for select=${select}. Replace URLs or install artifacts manually."
  fi
  local pre=( )
  local post=( )
  if dry_run_active; then
    pre+=(--dry-run)
  fi
  if [[ "${XDR_LAB_IMAGE_DOWNLOAD_FORCE:-}" == "1" ]]; then
    post+=(--force)
  fi
  python3 "${IMAGE_DL_HELPER}" \
    --manifest "${XDR_LAB_IMAGES_MANIFEST}" \
    --state "${XDR_LAB_IMAGES_STATE_JSON}" \
    --xdr-root "${XDR_ROOT}" \
    --log-file "${LOGD}/vm-manager.log" \
    "${pre[@]}" \
    download --select "${select}" "${post[@]}"
}

sensor_cache_dir_for_version() {
  local version="$1"
  printf '%s/sensor/%s' "${IMG}" "${version}"
}

sensor_manifest_sync() {
  local version="$1" force="${2:-0}"
  require_cmd python3
  [[ -f "${XDR_LAB_IMAGES_MANIFEST}" ]] || die "Sensor image manifest missing: ${XDR_LAB_IMAGES_MANIFEST}"
  [[ -f "${IMAGE_DL_HELPER}" ]] || die "image_download_manager.py missing: ${IMAGE_DL_HELPER}"
  if manifest_selection_has_placeholder_url "sensor-vm"; then
    die "CONFIG_PLACEHOLDER_ERROR: refusing sensor download because ${XDR_LAB_IMAGES_MANIFEST} contains REPLACE_ME.example.invalid placeholder URLs for sensor-vm."
  fi
  if ! dry_run_active; then
    validate_stellar_download_env
  fi
  local pre=( )
  local post=( )
  if dry_run_active; then
    pre+=(--dry-run)
  fi
  if [[ "${force}" == "1" ]]; then
    post+=(--force)
  fi
  python3 "${IMAGE_DL_HELPER}" \
    --manifest "${XDR_LAB_IMAGES_MANIFEST}" \
    --state "${XDR_LAB_IMAGES_STATE_JSON}" \
    --xdr-root "${XDR_ROOT}" \
    --log-file "${LOGD}/vm-manager.log" \
    --stellar-env "${XDR_LAB_STELLAR_DOWNLOAD_ENV:-/etc/xdr-lab/stellar-download.env}" \
    "${pre[@]}" \
    download --select sensor-vm --version "${version}" "${post[@]}"
}

manifest_selection_has_placeholder_url() {
  local select="${1:-MANIFEST_ALL}"
  python3 - "${XDR_LAB_IMAGES_MANIFEST}" "${select}" <<'PY'
import json, sys
path, select = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)
for image in data.get("images", []):
    if not isinstance(image, dict):
        continue
    if select != "MANIFEST_ALL" and select not in {str(image.get("name", "")), str(image.get("vm_role", ""))}:
        continue
    url = str(image.get("url", ""))
    lowered = url.lower()
    if (not url) or "replace_me.example.invalid" in lowered or "replace_me" in lowered or "placeholder" in lowered:
        sys.exit(0)
sys.exit(1)
PY
}

# shellcheck disable=SC2090,SC3040
download_main_cli() (
  set -euo pipefail
  local force=0
  local tokens=( )
  local a
  for a in "$@"; do
    case "$a" in
      --force) force=1 ;;
      *) tokens+=("$a") ;;
    esac
  done
  if [[ "${force}" == "1" ]]; then
    export XDR_LAB_IMAGE_DOWNLOAD_FORCE=1
  else
    unset XDR_LAB_IMAGE_DOWNLOAD_FORCE 2>/dev/null || true
  fi
  local target="${tokens[0]:-}"
  if [[ -z "${target}" ]]; then
    manifest_enabled || die "Manifest bulk download disabled: set enabled=true in ${XDR_LAB_IMAGES_MANIFEST} or export XDR_LAB_USE_IMAGE_MANIFEST=1"
    require_cmd python3
    image_manifest_sync "MANIFEST_ALL"
    exit $?
  fi
  if [[ "${target}" == "all" ]]; then
    [[ -f "${CFG}" ]] || die "Config missing: ${CFG}"
    iterate_vms download_vm_image
    exit 0
  fi
  [[ -f "${CFG}" ]] || die "Config missing: ${CFG}"
  if python3 - "$CFG" "$target" <<'PY' 2>/dev/null
import json, sys
path, name = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    cfg = json.load(f)
sys.exit(0 if name in cfg.get("vms", {}) else 1)
PY
  then
    download_vm_image "${target}"
  else
    manifest_enabled || die "Unknown VM '${target}' (not in ${CFG}) and manifest download is disabled"
    require_cmd python3
    image_manifest_sync "${target}" || exit $?
  fi
  exit 0
)

images_cli_dispatch() {
  local sub="${1:-status}"
  require_cmd python3
  [[ -f "${IMAGE_DL_HELPER}" ]] || die "image_download_manager.py missing: ${IMAGE_DL_HELPER}"
  case "${sub}" in
    status)
      python3 "${IMAGE_DL_HELPER}" \
        --manifest "${XDR_LAB_IMAGES_MANIFEST}" \
        --state "${XDR_LAB_IMAGES_STATE_JSON}" \
        --xdr-root "${XDR_ROOT}" \
        status
      ;;
    *)
      echo "Usage: $(basename "$0") images status" >&2
      return 2
      ;;
  esac
}

sensor_cli_dispatch() {
  local sub="${1:-}"
  shift || true
  local version="" force=0 cpus="" memory_mb="" disk_gb=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --version)
        [[ $# -ge 2 ]] || die "--version requires a value"
        version="$2"
        shift 2
        ;;
      --force)
        force=1
        shift
        ;;
      --cpus)
        [[ $# -ge 2 ]] || die "--cpus requires a value"
        cpus="$2"
        shift 2
        ;;
      --memory-mb)
        [[ $# -ge 2 ]] || die "--memory-mb requires a value"
        memory_mb="$2"
        shift 2
        ;;
      --disk-gb)
        [[ $# -ge 2 ]] || die "--disk-gb requires a value"
        disk_gb="$2"
        shift 2
        ;;
      *)
        die "Unknown sensor option: $1"
        ;;
    esac
  done

  case "${sub}" in
    download)
      [[ -n "${version}" ]] || die "sensor download requires --version VERSION"
      [[ -z "${cpus}${memory_mb}${disk_gb}" ]] || die "--cpus/--memory-mb/--disk-gb are only supported for sensor deploy"
      sensor_manifest_sync "${version}" "${force}"
      ;;
    deploy)
      [[ -n "${version}" ]] || die "sensor deploy requires --version VERSION"
      [[ -f "${CFG}" ]] || die "Config missing: ${CFG}"
      [[ "${force}" == "0" ]] || die "--force is only supported for sensor download"
      if [[ -n "${cpus}" ]]; then require_positive_int_at_least "--cpus" "${cpus}" 4; export XDR_LAB_SENSOR_CPUS_OVERRIDE="${cpus}"; fi
      if [[ -n "${memory_mb}" ]]; then require_positive_int_at_least "--memory-mb" "${memory_mb}" 6144; export XDR_LAB_SENSOR_MEMORY_MB_OVERRIDE="${memory_mb}"; fi
      if [[ -n "${disk_gb}" ]]; then require_positive_int_at_least "--disk-gb" "${disk_gb}" 80; export XDR_LAB_SENSOR_DISK_GB_OVERRIDE="${disk_gb}"; fi
      deploy_sensor_vm "${XDR_LAB_SENSOR_VM}" 1 "${version}"
      if ! dry_run_active; then
        apply_autostart "${XDR_LAB_SENSOR_VM}"
      fi
      ;;
    verify)
      [[ -z "${version}${cpus}${memory_mb}${disk_gb}" ]] || die "sensor verify does not accept version or size overrides"
      [[ "${force}" == "0" ]] || die "--force is only supported for sensor download"
      local validator="${XDR_ROOT}/bootstrap/validate-sensor-identity.sh"
      if [[ "${XDR_LAB_DEV_MODE}" == "1" && -f "${_XDR_VM_MGR_DIR}/../bootstrap/validate-sensor-identity.sh" ]]; then
        validator="${_XDR_VM_MGR_DIR}/../bootstrap/validate-sensor-identity.sh"
      fi
      [[ -x "${validator}" ]] || die "Sensor validator missing or not executable: ${validator}"
      XDR_LAB_SENSOR_VM="${XDR_LAB_SENSOR_VM}" bash "${validator}"
      ;;
    *)
      echo "Usage: $(basename "$0") sensor download --version VERSION [--force]" >&2
      echo "       $(basename "$0") sensor deploy --version VERSION [--cpus N] [--memory-mb N] [--disk-gb N]" >&2
      echo "       $(basename "$0") sensor verify" >&2
      return 2
      ;;
  esac
}

vm_exists() {
  local name="$1"
  virsh dominfo "$name" >/dev/null 2>&1
}

# =============================================================================
# Windows golden QCOW2 + UEFI orchestration (state: runtime/state/<vm>.json).
#
# NVRAM policy:
#   - XDR_LAB_WINDOWS_RECREATE_NVRAM=0 (default): reuse ${RUN}/${vm}/nvram/OVMF_VARS.fd
#     across redeploys so Windows activation / Secure Boot state persist.
#   - XDR_LAB_WINDOWS_RECREATE_NVRAM=1: delete and recopy from distro template before virt-install.
# destroy_vm: rm -rf ${RUN}/${vm}/ removes nvram + root.qcow2 (next deploy starts clean).
#
# Optional lab-vms.json fields (all optional):
#   - image_checksum_sha256
#   - windows_qcow2_mode: "full-clone" (default) | "backing"
#   - backing_image: filename under ${XDR_LAB_WINDOWS_IMAGES_DIR} when mode=backing
# Reserved: XDR_LAB_WINDOWS_NET_MODEL=virtio switches NIC model (default e1000).
# =============================================================================

windows_checksum_verify() {
  local dest="$1" expected="$2"
  [[ -n "$expected" ]] || return 0
  require_cmd sha256sum
  local got
  got="$(sha256sum "$dest" | awk '{print $1}')"
  if [[ "$got" != "$expected" ]]; then
    die "Windows image checksum mismatch for ${dest} expected=${expected} actual=${got}"
  fi
  log_structured "INFO" "windows_image_checksum_ok path=${dest}"
}

# Grow qcow2 to at least ${size_gb}G; never shrink (golden images may exceed lab-vms.json disk_size_gb).
qemu_img_resize_grow_only() {
  local disk="$1" size_gb="$2" vm="${3:-}"
  local cur_gb target_gb
  cur_gb="$(qemu-img info --output=json "$disk" | python3 -c 'import json,sys; print((json.load(sys.stdin)["virtual-size"]+1073741823)//1073741824)')"
  target_gb="$size_gb"
  if (( target_gb > cur_gb )); then
    qemu-img resize "$disk" "${target_gb}G" >/dev/null
    log_structured "INFO" "windows_qcow2_resize_grow vm=${vm} path=${disk} from_gb=${cur_gb} to_gb=${target_gb}"
  else
    log_structured "INFO" "windows_qcow2_resize_skip vm=${vm} path=${disk} current_gb=${cur_gb} configured_gb=${target_gb}"
  fi
}

windows_emit_deploy_failure_diagnostics() {
  local vm="$1" ip="$2" run_vm="$3" disk="$4" nvram="$5" reason="$6"
  local dom_st domiflist_out ping_rc=1
  echo ""
  echo "=== windows-victim deploy failure diagnostics (${reason}) ==="
  echo "vm=${vm} ip=${ip:-unknown} run_vm=${run_vm}"
  echo ""
  echo "virsh domstate ${vm}:"
  dom_st="$(virsh domstate "$vm" 2>/dev/null | tr -d '\r' || echo "(virsh failed)")"
  echo "  ${dom_st}"
  echo ""
  echo "virsh domiflist ${vm}:"
  domiflist_out="$(virsh domiflist "$vm" 2>&1 || true)"
  printf '%s\n' "${domiflist_out}" | sed 's/^/  /'
  echo ""
  if [[ -n "${ip:-}" ]] && command -v ping >/dev/null 2>&1; then
    echo "ping ${ip}:"
    if ping -c 3 -W 2 "$ip" >/tmp/xdr-windows-ping.$$ 2>&1; then
      ping_rc=0
    else
      ping_rc=$?
    fi
    sed 's/^/  /' /tmp/xdr-windows-ping.$$ 2>/dev/null || true
    rm -f /tmp/xdr-windows-ping.$$ 2>/dev/null || true
    echo "  ping_exit=${ping_rc}"
    echo ""
  fi
  echo "runtime disk:"
  echo "  ${disk}"
  echo ""
  echo "nvram:"
  echo "  ${nvram}"
  echo ""
  if command -v ovs-vsctl &>/dev/null; then
    echo "ovs-vsctl list-ports ${LAB_BRIDGE}:"
    ovs-vsctl list-ports "${LAB_BRIDGE}" 2>/dev/null | sed 's/^/  /' || true
    echo ""
  fi
  echo "try:"
  echo "  virsh console ${vm}"
  echo "  ssh lab@${ip:-10.10.10.30}"
  echo ""
  log_structured "WARN" "windows_deploy_failure_preserved vm=${vm} reason=${reason} run_vm=${run_vm}"
}

windows_handle_deploy_failure() {
  local vm="$1" run_vm="$2" disk="$3" nvram="$4" reason="$5" ip="${6:-}"
  windows_emit_deploy_failure_diagnostics "$vm" "$ip" "$run_vm" "$disk" "$nvram" "$reason"
}

windows_rollback_deploy() {
  local vm="$1" run_vm="$2" reason="$3"
  log_structured "WARN" "windows_rollback_deploy_begin vm=${vm} reason=${reason}"
  virsh destroy "$vm" >/dev/null 2>&1 || true
  virsh undefine "$vm" --managed-save --snapshots-metadata >/dev/null 2>&1 || \
    virsh undefine "$vm" >/dev/null 2>&1 || true
  rm -rf "${run_vm}" 2>/dev/null || true
  log_structured "WARN" "windows_rollback_deploy_end vm=${vm}"
}

windows_probe_core_ok() {
  local vm="$1" exp_ip="$2"
  local st
  st="$(virsh domstate "$vm" 2>/dev/null | tr -d '\r' || true)"
  if [[ "$st" != "running" ]]; then
    return 1
  fi
  if ! command -v ping >/dev/null 2>&1; then
    return 0
  fi
  local lease_ip
  lease_ip="$(virsh domifaddr "$vm" --source lease 2>/dev/null | grep -Eo '([0-9]{1,3}\.){3}[0-9]{1,3}' | head -n1 || true)"
  local agent_ip
  agent_ip="$(virsh domifaddr "$vm" --source agent 2>/dev/null | grep -Eo '([0-9]{1,3}\.){3}[0-9]{1,3}' | head -n1 || true)"
  local try
  for try in "$lease_ip" "$agent_ip" "$exp_ip"; do
    if [[ -n "$try" ]] && ping -c 1 -W 2 "$try" >/dev/null 2>&1; then
      return 0
    fi
  done
  if [[ -n "$lease_ip$agent_ip$exp_ip" ]]; then
    return 1
  fi
  return 0
}

windows_nvram_preflight() {
  local vm="$1" nvram="$2" holder=""
  [[ -n "${nvram}" ]] || return 0
  if command -v virsh >/dev/null 2>&1; then
    while IFS= read -r dom; do
      [[ -n "${dom}" && "${dom}" != "${vm}" ]] || continue
      if virsh dumpxml "${dom}" 2>/dev/null | grep -Fq "${nvram}"; then
        holder="${dom}"
        break
      fi
    done < <(virsh list --all --name 2>/dev/null || true)
  fi
  if [[ -n "${holder}" ]]; then
    die "nvram_locked vm=${vm} path=${nvram} holder_domain=${holder}"
  fi
  if [[ -f "${nvram}" ]] && command -v fuser >/dev/null 2>&1; then
    if fuser "${nvram}" >/dev/null 2>&1; then
      die "nvram_locked vm=${vm} path=${nvram} holder_process=fuser"
    fi
  fi
}

windows_nvram_path() {
  local vm="$1"
  printf '%s/%s/nvram/OVMF_VARS.fd' "${RUN}" "${vm}"
}

windows_runtime_disk_path() {
  local vm="$1"
  printf '%s/%s/root.qcow2' "${RUN}" "${vm}"
}

windows_qemu_dac_owner() {
  local disk="$1" nvram="$2" user="" group=""
  if [[ -e "${disk}" ]]; then
    stat -c '%U:%G' "${disk}" 2>/dev/null && return 0
  fi
  if [[ -e "${nvram}" ]]; then
    stat -c '%U:%G' "${nvram}" 2>/dev/null && return 0
  fi
  if id -u libvirt-qemu >/dev/null 2>&1; then
    user="libvirt-qemu"
    group="kvm"
  elif id -u qemu >/dev/null 2>&1; then
    user="qemu"
    group="qemu"
  fi
  if [[ -n "${user}" ]]; then
    getent group "${group}" >/dev/null 2>&1 || group="${user}"
    printf '%s:%s\n' "${user}" "${group}"
  fi
}

windows_repair_nvram_permissions() {
  local vm="$1" nvram="$2" disk="$3" owner run_vm
  run_vm="${RUN}/${vm}"
  mkdir -p "$(dirname "${nvram}")"
  chmod 0755 "${run_vm}" "$(dirname "${nvram}")" 2>/dev/null || true
  if [[ -f "${nvram}" ]]; then
    chmod u+rw,g+rw,o+r "${nvram}" 2>/dev/null || chmod 0664 "${nvram}" 2>/dev/null || true
  fi
  if [[ -f "${disk}" ]]; then
    chmod u+rw,g+rw,o-rwx "${disk}" 2>/dev/null || true
  fi
  owner="$(windows_qemu_dac_owner "${disk}" "${nvram}" || true)"
  if [[ -n "${owner}" ]]; then
    if [[ "$(id -u)" -eq 0 ]]; then
      [[ -f "${nvram}" ]] && chown "${owner}" "${nvram}" 2>/dev/null || true
      [[ -f "${disk}" ]] && chown "${owner}" "${disk}" 2>/dev/null || true
      log_structured "INFO" "windows_nvram_dac_repaired vm=${vm} owner=${owner} nvram=${nvram}"
    elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
      [[ -f "${nvram}" ]] && sudo -n chown "${owner}" "${nvram}" 2>/dev/null || true
      [[ -f "${disk}" ]] && sudo -n chown "${owner}" "${disk}" 2>/dev/null || true
      log_structured "INFO" "windows_nvram_dac_repaired_sudo vm=${vm} owner=${owner} nvram=${nvram}"
    else
      log_structured "WARN" "windows_nvram_dac_repair_needs_root vm=${vm} owner=${owner} nvram=${nvram}"
    fi
  fi
}

windows_qemu_lock_pids() {
  local vm="$1" nvram="$2" proc pid cmd fd target
  for proc in /proc/[0-9]*; do
    [[ -d "${proc}" ]] || continue
    pid="${proc##*/}"
    cmd="$(tr '\0' ' ' <"${proc}/cmdline" 2>/dev/null || true)"
    [[ "${cmd}" == *qemu* ]] || continue
    if [[ "${cmd}" == *"${nvram}"* || "${cmd}" == *"${vm}"* ]]; then
      printf '%s\n' "${pid}"
      continue
    fi
    for fd in "${proc}"/fd/*; do
      target="$(readlink "${fd}" 2>/dev/null || true)"
      if [[ "${target}" == "${nvram}" ]]; then
        printf '%s\n' "${pid}"
        break
      fi
    done
  done | awk '!seen[$0]++'
}

windows_cleanup_stale_qemu_locks() {
  local vm="$1" nvram="$2" state pids=() pid waited=0
  state="$(virsh domstate "${vm}" 2>/dev/null | tr -d '\r' || true)"
  if [[ "${state}" == "running" ]]; then
    log_structured "INFO" "windows_stale_qemu_cleanup_skipped vm=${vm} reason=domain_running"
    return 0
  fi
  mapfile -t pids < <(windows_qemu_lock_pids "${vm}" "${nvram}")
  if [[ "${#pids[@]}" -eq 0 ]]; then
    return 0
  fi
  log_structured "WARN" "windows_stale_qemu_cleanup_begin vm=${vm} pids=${pids[*]} nvram=${nvram}"
  for pid in "${pids[@]}"; do
    kill "${pid}" 2>/dev/null || true
  done
  while (( waited < 5 )); do
    local alive=0
    for pid in "${pids[@]}"; do
      kill -0 "${pid}" 2>/dev/null && alive=1
    done
    [[ "${alive}" -eq 0 ]] && break
    sleep 1
    waited=$(( waited + 1 ))
  done
  for pid in "${pids[@]}"; do
    kill -0 "${pid}" 2>/dev/null && kill -9 "${pid}" 2>/dev/null || true
  done
  rm -f "${nvram}.lock" "${nvram}.lck" 2>/dev/null || true
  log_structured "WARN" "windows_stale_qemu_cleanup_end vm=${vm} pids=${pids[*]}"
}

repair_windows_vm_runtime() {
  local vm="$1" nvram disk ovmf_vars_tpl
  require_cmd virsh
  if [[ "$(vm_json_field_optional "${vm}" type "")" != "windows" ]]; then
    die "VM is not a Windows guest: ${vm}"
  fi
  nvram="$(windows_nvram_path "${vm}")"
  disk="$(windows_runtime_disk_path "${vm}")"
  if [[ ! -f "${nvram}" ]]; then
    if declare -F xdr_find_ovmf_vars_template >/dev/null 2>&1; then
      ovmf_vars_tpl="$(xdr_find_ovmf_vars_template || true)"
      if [[ -n "${ovmf_vars_tpl}" && -f "${ovmf_vars_tpl}" ]]; then
        mkdir -p "$(dirname "${nvram}")"
        cp -f -- "${ovmf_vars_tpl}" "${nvram}"
        log_structured "INFO" "windows_nvram_recreated vm=${vm} path=${nvram}"
      fi
    fi
  fi
  windows_cleanup_stale_qemu_locks "${vm}" "${nvram}"
  windows_repair_nvram_permissions "${vm}" "${nvram}" "${disk}"
  windows_nvram_preflight "${vm}" "${nvram}"
  _invoke_state_refresh "${vm}" 0
  log_structured "INFO" "windows_vm_repair_complete vm=${vm} nvram=${nvram}"
}

deploy_windows_vm() {
  local vm="$1"
  local nodownload="${2:-0}"

  if ! declare -F xdr_find_ovmf_code >/dev/null 2>&1; then
    die "windows_lab_helpers.sh not loaded (missing xdr_find_ovmf_code)"
  fi

  log_structured "INFO" "windows_deploy_started vm=${vm}"

  if dry_run_active; then
    log_structured "INFO" "dry_run windows_deploy_inspect_only vm=${vm}"
    local _fname _golden
    _fname="$(get_vm_field "$vm" disk_filename)"
    _golden="${XDR_LAB_WINDOWS_IMAGES_DIR}/${_fname}"
    log_structured "INFO" "dry_run windows_planned_golden path=${_golden}"
    log_structured "INFO" "dry_run windows_planned_runtime_disk path=${RUN}/${vm}/root.qcow2"
    log_structured "INFO" "dry_run windows_planned_nvram path=${RUN}/${vm}/nvram/OVMF_VARS.fd"
    _invoke_state_refresh "$vm" 0
    log_structured "INFO" "windows_deploy_success vm=${vm} dry_run=true"
    return 0
  fi

  require_cmd qemu-img
  require_cmd virt-install
  require_cmd virsh

  local cpu mem autostart disk_gb osv fname netm
  cpu="$(get_vm_field "$vm" cpu)"
  mem="$(get_vm_field "$vm" memory)"
  autostart="$(get_vm_field "$vm" autostart)"
  disk_gb="$(get_vm_field "$vm" disk_size_gb)"
  osv="$(get_vm_field "$vm" os_variant)"
  fname="$(get_vm_field "$vm" disk_filename)"
  netm="${XDR_LAB_WINDOWS_NET_MODEL:-e1000}"

  local golden="${XDR_LAB_WINDOWS_IMAGES_DIR}/${fname}"
  local run_vm="${RUN}/${vm}"
  local disk="${run_vm}/root.qcow2"
  local nvram_dir="${run_vm}/nvram"
  local nvram="${nvram_dir}/OVMF_VARS.fd"
  local ovmf_code ovmf_vars_tpl
  ovmf_code="$(xdr_find_ovmf_code)" || die "OVMF_CODE_4M.fd not found (install ovmf/edk2-ovmf)"
  ovmf_vars_tpl="$(xdr_find_ovmf_vars_template)" || die "OVMF_VARS template not found (install ovmf)"

  if [[ "$nodownload" != "1" ]]; then
    download_vm_image "$vm"
  fi
  [[ -f "$golden" ]] || die "Missing Windows golden qcow2: ${golden} (run: $0 download ${vm})"

  if vm_exists "$vm"; then
    virsh start "$vm" >/dev/null 2>&1 || true
    apply_autostart "$vm"
    local exp_ip
    exp_ip="$(get_vm_field "$vm" internal_ip)"
    if validate_vm_boot "$vm" && windows_probe_core_ok "$vm" "$exp_ip"; then
      log_structured "INFO" "windows_deploy_idempotent_ok vm=${vm} state=running ping_ok=1"
      _invoke_state_refresh "$vm" 0
      log_structured "INFO" "windows_deploy_success vm=${vm} idempotent=true"
      return 0
    fi
    die "Existing Windows domain ${vm} is unhealthy (destroy and redeploy, or repair guest networking)"
  fi

  mkdir -p "$nvram_dir"
  if [[ "${XDR_LAB_WINDOWS_RECREATE_NVRAM:-0}" == "1" ]]; then
    rm -f "$nvram" 2>/dev/null || true
  fi
  if [[ ! -f "$nvram" ]]; then
    cp -f -- "$ovmf_vars_tpl" "$nvram"
    chmod u+rw,g+rw,o+r "$nvram" 2>/dev/null || chmod 664 "$nvram" 2>/dev/null || true
    log_structured "INFO" "windows_nvram_created vm=${vm} path=${nvram}"
  else
    log_structured "INFO" "windows_nvram_reuse vm=${vm} path=${nvram}"
  fi
  windows_nvram_preflight "$vm" "$nvram"

  local qcow_mode backing_fn golden_backing
  qcow_mode="$(vm_json_field_optional "$vm" windows_qcow2_mode "full-clone")"
  backing_fn="$(vm_json_field_optional "$vm" backing_image "")"
  golden_backing="${XDR_LAB_WINDOWS_IMAGES_DIR}/${backing_fn}"

  if [[ -f "$disk" ]]; then
    log_structured "INFO" "windows_runtime_qcow2_reuse vm=${vm} path=${disk}"
  else
    if [[ "$qcow_mode" == "backing" && -n "$backing_fn" && -f "$golden_backing" ]]; then
      log_structured "INFO" "windows_qcow2_create_backing vm=${vm} backing=${golden_backing} overlay=${disk}"
      qemu-img create -f qcow2 -F qcow2 -b "$golden_backing" "$disk" "${disk_gb}G"
    else
      log_structured "INFO" "windows_qcow2_full_clone vm=${vm} src=${golden} dst=${disk}"
      qemu-img convert -p -O qcow2 "$golden" "$disk"
    fi
    qemu_img_resize_grow_only "$disk" "$disk_gb" "$vm"
  fi

  local autostart_flag=( )
  if [[ "$autostart" == "True" || "$autostart" == "true" || "$autostart" == "1" ]]; then
    autostart_flag=(--autostart)
  fi

  local graphics_arg="vnc,listen=127.0.0.1"
  if [[ "$vm" == "windows-victim" ]]; then
    graphics_arg="vnc,listen=127.0.0.1,port=${XDR_LAB_WINDOWS_VICTIM_VNC_PORT},autoport=no"
  fi

  log_structured "INFO" "windows_virt_install_begin vm=${vm} libvirt_network=${LAB_OVS_NETWORK} uefi=1 net=${netm} graphics=${graphics_arg}"
  if ! virt_install_libvirt_network "${netm}" \
    --name "$vm" \
    --memory "$mem" \
    --vcpus "$cpu" \
    --disk "path=${disk},format=qcow2,bus=sata" \
    --import \
    --os-variant "$osv" \
    --virt-type kvm \
    --graphics "${graphics_arg}" \
    --boot "loader=${ovmf_code},nvram=${nvram},loader.readonly=yes,loader.type=pflash" \
    --noautoconsole \
    "${autostart_flag[@]}"; then
    windows_handle_deploy_failure "$vm" "$run_vm" "$disk" "$nvram" "virt_install_failed" "$(get_vm_field "$vm" internal_ip)"
    die "virt-install failed for ${vm} (VM and artifacts preserved)"
  fi

  apply_autostart "$vm"

  validate_vm_libvirt_network_attach "$vm" || true

  if ! validate_vm_boot "$vm"; then
    windows_handle_deploy_failure "$vm" "$run_vm" "$disk" "$nvram" "boot_validation_failed" "$(get_vm_field "$vm" internal_ip)"
    die "Boot validation failed for ${vm} (VM and artifacts preserved)"
  fi

  validate_windows_vm "$vm" || true

  local exp_ip nat_json
  exp_ip="$(get_vm_field "$vm" internal_ip)"
  nat_json="$(get_vm_field "$vm" external_nat_port_mapping)"
  log_structured "INFO" "windows_deploy_network_hints vm=${vm} internal_ip=${exp_ip} nat=${nat_json}"
  _invoke_state_refresh "$vm" 1
  log_structured "INFO" "windows_deploy_success vm=${vm} idempotent=false"
}

validate_windows_vm() {
  local vm="$1"
  require_cmd virsh

  log_structured "INFO" "windows_validation_begin vm=${vm}"

  local dom_st exp_ip probe
  dom_st="$(virsh domstate "$vm" 2>/dev/null | tr -d '\r' || true)"
  log_structured "INFO" "windows_validate_virsh_domstate vm=${vm} state=${dom_st:-unknown}"
  virsh domifaddr "$vm" --source lease 2>/dev/null || true
  virsh domifaddr "$vm" --source agent 2>/dev/null || true

  exp_ip="$(get_vm_field "$vm" internal_ip)"
  probe="$(virsh domifaddr "$vm" --source lease 2>/dev/null | grep -Eo '([0-9]{1,3}\.){3}[0-9]{1,3}' | head -n1 || true)"
  if [[ -z "$probe" ]]; then
    probe="$(virsh domifaddr "$vm" --source agent 2>/dev/null | grep -Eo '([0-9]{1,3}\.){3}[0-9]{1,3}' | head -n1 || true)"
  fi
  if [[ -z "$probe" ]]; then
    probe="$exp_ip"
  fi

  if [[ -n "$probe" ]] && command -v ping >/dev/null 2>&1; then
    if ping -c 1 -W 2 "$probe" >/dev/null 2>&1; then
      log_structured "INFO" "windows_validate_ping_ok vm=${vm} ip=${probe}"
    else
      log_structured "WARN" "windows_validate_ping_fail vm=${vm} ip=${probe}"
    fi
  else
    log_structured "WARN" "windows_validate_ping_skip vm=${vm} reason=no_ip_or_no_ping"
  fi

  if [[ -n "$probe" ]]; then
    if declare -F xdr_tcp_open >/dev/null 2>&1; then
      if xdr_tcp_open "$probe" 3389 2; then
        log_structured "INFO" "windows_rdp_reachable vm=${vm} ip=${probe} port=3389"
      else
        log_structured "WARN" "windows_validate_rdp_unreachable vm=${vm} ip=${probe}"
      fi
      if xdr_tcp_open "$probe" 22 2; then
        log_structured "INFO" "windows_validate_ssh_port_open vm=${vm} ip=${probe} port=22"
      else
        log_structured "INFO" "windows_validate_ssh_port_closed vm=${vm} ip=${probe}"
      fi
      if xdr_tcp_open "$probe" 5985 1 || xdr_tcp_open "$probe" 5986 1; then
        log_structured "INFO" "windows_validate_winrm_port_open vm=${vm} ip=${probe}"
      else
        log_structured "INFO" "windows_validate_winrm_port_closed vm=${vm} ip=${probe}"
      fi
    fi
  fi

  _invoke_state_refresh "$vm" 0
  log_structured "INFO" "windows_validation_success vm=${vm}"
  return 0
}

show_windows_console_info() {
  local vm="${1:-windows-victim}"
  require_cmd virsh
  if ! vm_exists "$vm"; then
    log_structured "WARN" "windows_vnc_info_domain_missing vm=${vm}"
    echo "Domain not defined: ${vm}" >&2
    return 1
  fi
  local disp listen num port ext_ip wc_port ws_pid mf vnc_url
  disp=""
  port="unknown"
  listen="127.0.0.1"
  if declare -F xdr_virsh_vncdisplay_raw >/dev/null 2>&1; then
    disp="$(xdr_virsh_vncdisplay_raw "$vm" 2>/dev/null || true)"
    num="$(xdr_parse_qemu_vnc_display_num "$disp" 2>/dev/null || true)"
    if [[ -n "$num" ]]; then
      port=$((5900 + num))
    fi
    if [[ "$disp" == *:* && "$disp" != :* ]]; then
      listen="${disp%%:*}"
    fi
  else
    disp="$(virsh vncdisplay "$vm" 2>&1 | tr -d '\r' | awk 'NF { line = $0 } END { if (line != "") print line }' || true)"
    num="$(echo "$disp" | awk -F: '{print $NF}' | tr -d '[:space:]' | sed 's/^://')"
    if [[ "$num" =~ ^[0-9]+$ ]]; then
      port=$((5900 + num))
    fi
    if [[ "$disp" == *:* && "$disp" != :* ]]; then
      listen="${disp%%:*}"
    fi
  fi

  ext_ip="$(xdr_primary_ipv4 2>/dev/null || true)"
  if declare -F xdr_web_console_listen_port >/dev/null 2>&1; then
    wc_port="$(xdr_web_console_listen_port "$vm")"
  else
    wc_port="${XDR_LAB_WEB_CONSOLE_PORT}"
  fi
  local mf="${XDR_LAB_WEB_CONSOLE_DIR}/${vm}.json"
  if declare -F xdr_web_console_manifest_path >/dev/null 2>&1; then
    mf="$(xdr_web_console_manifest_path "$vm")"
  fi
  ws_pid=""
  if declare -F xdr_vnc_manifest_read_field >/dev/null 2>&1; then
    ws_pid="$(xdr_vnc_manifest_read_field "$mf" websockify_pid)"
  fi
  local ws_state="stopped"
  if [[ -n "$ws_pid" ]] && declare -F xdr_pid_alive >/dev/null 2>&1 && xdr_pid_alive "$ws_pid"; then
    ws_state="running"
  elif [[ -n "$ws_pid" ]]; then
    ws_state="stopped (stale pid in manifest)"
  fi

  vnc_url=""
  if [[ -n "$ext_ip" ]]; then
    vnc_url="http://${ext_ip}:${wc_port}/"
  fi

  log_structured "INFO" "windows_console_info vm=${vm} vnc_display=${disp:-unknown} vnc_port=${port} web_console=${ws_state}"

  echo "Windows Web Console:"
  if [[ -n "$vnc_url" ]]; then
    echo "  URL: ${vnc_url}"
  else
    echo "  URL: http://<external-ip>:${wc_port}/  (host primary IPv4 not detected)"
  fi
  echo "  Target: ${vm}"
  if [[ "$port" != "unknown" ]]; then
    echo "  Internal VNC: ${listen}:${port}"
  else
    echo "  Internal VNC: ${listen}:<unknown>"
  fi
  echo "  websockify: ${ws_state}"
  echo ""
  echo "Legacy raw VNC (socat emergency proxy, VNC viewer client):"
  echo "  External port: ${XDR_LAB_VNC_EXTERNAL_PORT}"
  if declare -F xdr_vnc_proxy_manifest_path >/dev/null 2>&1; then
    local proxy_pid proxy_running
    proxy_pid="$(xdr_vnc_manifest_read_field "$(xdr_vnc_proxy_manifest_path "$vm")" socat_pid)"
    proxy_running="stopped"
    if [[ -n "$proxy_pid" ]] && declare -F xdr_pid_alive >/dev/null 2>&1 && xdr_pid_alive "$proxy_pid"; then
      proxy_running="running"
    elif [[ -n "$proxy_pid" ]]; then
      proxy_running="stopped (stale pid in manifest)"
    fi
    echo "  socat proxy: ${proxy_running}"
  fi
  if [[ -n "$ext_ip" ]]; then
    echo "  vnc://${ext_ip}:${XDR_LAB_VNC_EXTERNAL_PORT}"
  fi
  echo ""
  echo "SSH tunnel to QEMU VNC (no host proxy):"
  if [[ "$port" != "unknown" ]]; then
    echo "  ssh -N -L ${port}:127.0.0.1:${port} <user>@<lab-host>"
    echo "  then VNC client: localhost:${port}"
  fi
  _invoke_state_refresh "$vm" 0
  return 0
}

download_vm_image() {
  local vm="$1"
  if dry_run_active; then
    if manifest_enabled && manifest_has_role "$vm" 2>/dev/null; then
      log_structured "INFO" "dry_run image_manifest_plan vm=${vm}"
      image_manifest_sync "$vm" || true
    fi
    log_structured "INFO" "dry_run_skip download_vm_image vm=${vm}"
    return 0
  fi
  [[ -f "$CFG" ]] || die "Missing config $CFG"
  python3 - "$CFG" "$vm" <<'PY' >/dev/null || die "Unknown VM in config: $vm"
import json, sys
path, vm = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as f:
    cfg = json.load(f)
if vm not in cfg.get("vms", {}):
    sys.exit(1)
sys.exit(0)
PY

  local vtype
  vtype="$(python3 - "$CFG" "$vm" <<'PY'
import json, sys
path, vm = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as f:
    cfg = json.load(f)
print(cfg["vms"][vm].get("type", ""))
PY
)"

  log_structured "INFO" "download_vm_image_begin vm=${vm} type=${vtype}"

  if manifest_enabled && manifest_has_role "$vm"; then
    image_manifest_sync "$vm" || die "Manifest image download failed for ${vm}"
    log_structured "INFO" "download_vm_image_manifest_complete vm=${vm}"
    return 0
  fi

  if [[ "$vm" == "sensor-vm" || "$vtype" == "sensor" ]]; then
    local sdir script_url img_url script_name
    validate_stellar_download_env
    sdir="$(lab_resolve_path "$(get_vm_field "$vm" sensor_cache_dir)")"
    script_url="$(get_vm_field "$vm" virt_deploy_script_url)"
    img_url="$(get_vm_field "$vm" image_url)"
    script_name="$(get_vm_field "$vm" virt_deploy_script_name)"
    mkdir -p "$sdir"
    download_to "$script_url" "${sdir}/${script_name}"
    chmod a+x "${sdir}/${script_name}"
    local img_dest="${sdir}/$(basename "$img_url")"
    download_to "$img_url" "$img_dest"
    log_structured "INFO" "download_vm_image_end vm=${vm} sensor_cache=${sdir}"
    return 0
  fi

  if [[ "$vm" == "victim-linux" ]]; then
    download_linux_server_cloud_base
    return 0
  fi

  if [[ "$vtype" == "windows" ]]; then
    local wdir url fname dest sum
    wdir="${XDR_LAB_WINDOWS_IMAGES_DIR}"
    mkdir -p "$wdir"
    url="$(get_vm_field "$vm" image_url)"
    fname="$(get_vm_field "$vm" disk_filename)"
    dest="${wdir}/${fname}"
    sum="$(vm_json_field_optional "$vm" image_checksum_sha256 "")"
    if [[ -f "$dest" ]]; then
      windows_checksum_verify "$dest" "$sum"
      log_structured "INFO" "windows_golden_cache_hit vm=${vm} path=${dest}"
      return 0
    fi
    log_structured "INFO" "windows_golden_download_begin vm=${vm} url=${url} dest=${dest}"
    download_to "$url" "$dest"
    windows_checksum_verify "$dest" "$sum"
    log_structured "INFO" "windows_golden_download_end vm=${vm} path=${dest}"
    return 0
  fi

  local url dir fname
  url="$(get_vm_field "$vm" image_url)"
  fname="$(get_vm_field "$vm" disk_filename)"
  dir="${IMG}/${vm}"
  mkdir -p "$dir"
  download_to "$url" "${dir}/${fname}"
  log_structured "INFO" "download_vm_image_end vm=${vm} path=${dir}/${fname}"
}

deploy_sensor_vm() {
  local vm="$1"
  local nodownload="${2:-0}"
  local version="${3:-$(vm_json_field_optional "$vm" sensor_version "6.2.0")}"

  local sdir script_name qcow2_name ip gw dns mask hostn cpu mem disk_gb installdir bridge capture_network deploy_image_dir deploy_image_path deploy_script
  sdir="$(sensor_cache_dir_for_version "$version")"
  script_name="$(get_vm_field "$vm" virt_deploy_script_name)"
  qcow2_name="$(vm_json_field_optional "$vm" qcow2_name "aella-modular-ds-${version}.qcow2")"
  ip="$(get_vm_field "$vm" internal_ip)"
  gw="$(net_global_field gateway)"
  dns="$(net_global_field dns)"
  mask="$(net_global_field netmask)"
  hostn="$(get_vm_field "$vm" hostname)"
  bridge="$(vm_json_field_optional "$vm" bridge "${LAB_BRIDGE}")"
  capture_network="$(sensor_capture_network_for "$vm")"
  cpu="${XDR_LAB_SENSOR_CPUS_OVERRIDE:-$(vm_json_field_optional "$vm" cpu "4")}"
  mem="${XDR_LAB_SENSOR_MEMORY_MB_OVERRIDE:-$(vm_json_field_optional "$vm" memory_mb "$(vm_json_field_optional "$vm" memory "6144")")}"
  disk_gb="${XDR_LAB_SENSOR_DISK_GB_OVERRIDE:-$(vm_json_field_optional "$vm" disk_size_gb "80")}"
  installdir="$(vm_json_field_optional "$vm" installdir "/var/lib/libvirt/images/${vm}")"
  deploy_image_dir="${installdir}/images"
  deploy_image_path="${deploy_image_dir}/${qcow2_name}"

  require_positive_int_at_least "--cpus" "$cpu" 4
  require_positive_int_at_least "--memory-mb" "$mem" 6144
  require_positive_int_at_least "--disk-gb" "$disk_gb" 80

  [[ -x "${sdir}/${script_name}" ]] || die "Sensor deploy script missing: ${sdir}/${script_name} (run download first)"
  [[ -f "${sdir}/${qcow2_name}" ]] || die "Sensor qcow2 missing: ${sdir}/${qcow2_name} (run download first)"

  local args=(
    --
    "--hostname=${hostn}"
    "--release=${version}"
    "--CPUS=${cpu}"
    "--MEM=${mem}"
    "--DISKSIZE=${disk_gb}"
    "--installdir=${installdir}"
    "--nodownload=true"
    "--nointeract=true"
    "--bridge=${bridge}"
    "--ip=${ip}"
    "--netmask=${mask}"
    "--gw=${gw}"
    "--dns=${dns}"
  )

  if dry_run_active; then
    printf 'DRY-RUN: cd %q && bash %q' "$sdir" "${script_name}"
    printf ' %q' "${args[@]}"
    printf '\n'
    printf 'DRY-RUN: virsh attach-interface --domain %q --type network --source %q --model virtio --config --live\n' "$vm" "${capture_network}"
    log_structured "INFO" "dry_run sensor_deploy_command vm=${vm} version=${version} cpus=${cpu} memory_mb=${mem} disk_gb=${disk_gb} capture_network=${capture_network}"
    return 0
  fi

  require_cmd virsh
  require_cmd bash
  require_cmd python3
  mkdir -p "${deploy_image_dir}"
  ln -sfn "${sdir}/${qcow2_name}" "${deploy_image_path}"
  log_structured "INFO" "sensor_deploy_image_prepared vm=${vm} source=${sdir}/${qcow2_name} target=${deploy_image_path}"
  deploy_script="${sdir}/${script_name}.xdr-lab"
  python3 - "${sdir}/${script_name}" "${deploy_script}" "${LAB_OVS_NETWORK}" <<'PY'
import sys
src, dst, net = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(src, encoding="utf-8").read()
needle = "bridge=${BRIDGE},model=virtio"
replacement = f"network={net},model=virtio"
if needle not in text:
    raise SystemExit(f"Stellar deploy script network anchor not found: {needle}")
text = text.replace(needle, replacement)
open(dst, "w", encoding="utf-8").write(text)
PY
  chmod +x "${deploy_script}"
  log_structured "INFO" "sensor_deploy_script_patched vm=${vm} script=${deploy_script} libvirt_network=${LAB_OVS_NETWORK}"
  if vm_exists "${vm}"; then
    log_structured "WARN" "sensor_deploy_existing_domain_cleanup vm=${vm}"
    virsh autostart "${vm}" --disable >/dev/null 2>&1 || true
    virsh destroy "${vm}" >/dev/null 2>&1 || true
    virsh undefine "${vm}" --managed-save --snapshots-metadata --remove-all-storage >/dev/null 2>&1 || \
      virsh undefine "${vm}" --managed-save --snapshots-metadata >/dev/null 2>&1 || \
      virsh undefine "${vm}" >/dev/null 2>&1 || true
  fi

  # Official sensor model: vendor deploy creates NIC #1 for management;
  # xdr-lab attaches NIC #2 as the IP-less capture sink for OVS mirror output.
  log_structured "INFO" "deploy_sensor_vm_exec vm=${vm} bridge=${bridge} capture_network=${capture_network} nodownload=${nodownload} cpus=${cpu} memory_mb=${mem} disk_gb=${disk_gb} version=${version}"
  ( cd "$sdir" && bash "./$(basename "${deploy_script}")" "${args[@]}" )
  ensure_sensor_capture_nic "$vm" "${capture_network}"

  validate_sensor_deployment "$vm" "$ip" "$hostn"
  _invoke_state_refresh "$vm" 1
}

validate_sensor_deployment() {
  local vm="$1" ip="$2" hostn="$3"
  if vm_exists "$vm"; then
    log_structured "INFO" "validate_sensor_deployment virsh_ok vm=${vm}"
    validate_vm_libvirt_network_attach "$vm" || true
    local vnet_count
    vnet_count="$(sensor_vnet_count "$vm")"
    if [[ "${vnet_count}" -lt 2 ]]; then
      log_structured "ERROR" "validate_sensor_deployment_capture_nic_missing vm=${vm} vnet_count=${vnet_count}"
      return 1
    fi
    log_structured "INFO" "validate_sensor_deployment_dual_nic_ok vm=${vm} vnet_count=${vnet_count}"
  else
    log_structured "WARN" "validate_sensor_deployment virsh_missing vm=${vm}"
  fi
  if command -v ping >/dev/null 2>&1; then
    if ping -c 1 -W 2 "$ip" >/dev/null 2>&1; then
      log_structured "INFO" "validate_sensor_deployment ping_ok ip=${ip} host=${hostn}"
    else
      log_structured "WARN" "validate_sensor_deployment_ping_failed ip=${ip} host=${hostn}"
    fi
  fi
}

download_linux_server_cloud_base() {
  local dir dest
  dir="${IMG}/victim-linux"
  dest="${dir}/${VICTIM_LINUX_CLOUD_IMAGE_BASENAME}"
  mkdir -p "$dir"
  if manifest_enabled && manifest_has_role "victim-linux"; then
    if [[ -f "$dest" ]]; then
      log_structured "INFO" "download_linux_server_cloud_manifest_ok path=${dest}"
      return 0
    fi
    die "Missing Ubuntu cloud base image at ${dest} (enable manifest sync / lab download victim-linux first)"
  fi
  if [[ -f "$dest" ]]; then
    log_structured "INFO" "download_linux_server_cloud_cache_hit path=${dest}"
    return 0
  fi
  log_structured "INFO" "download_linux_server_cloud_begin url=${VICTIM_LINUX_CLOUD_IMAGE_URL} dest=${dest}"
  download_to "${VICTIM_LINUX_CLOUD_IMAGE_URL}" "$dest"
  log_structured "INFO" "download_linux_server_cloud_end path=${dest}"
}

# Lab operator home — when invoked via sudo, prefer the invoking user's ~/.ssh.
linux_server_operator_home() {
  local u h
  if [[ -n "${SUDO_USER:-}" ]]; then
    u="${SUDO_USER}"
  else
    u="${USER:-}"
  fi
  if [[ -n "$u" && "$u" != "root" ]]; then
    h="$(getent passwd "$u" 2>/dev/null | cut -d: -f6 || true)"
    if [[ -n "$h" && -d "$h" ]]; then
      printf '%s' "$h"
      return 0
    fi
  fi
  printf '%s' "${HOME}"
}

# True when a file contains at least one non-comment SSH public-key line.
_linux_server_pubkey_file_usable() {
  local f="$1"
  [[ -n "$f" && -f "$f" && -r "$f" ]] || return 1
  grep -E '^[[:space:]]*(#|$)' -v "$f" \
    | grep -qE '^(ssh-(rsa|ed25519|dss)|ecdsa-sha2-|sk-ssh-ed25519@openssh.com|sk-ecdsa-sha2-nistp256@openssh.com)'
}

# Priority: env override → XDR_ROOT config → id_ed25519.pub → id_rsa.pub → first ~/.ssh/*.pub
linux_server_discover_ssh_pubkey_source() {
  local op_home="$1"
  local -a candidates=()
  local f pub

  if [[ -n "${XDR_LAB_VICTIM_LINUX_AUTHORIZED_KEYS:-}" ]]; then
    candidates+=("${XDR_LAB_VICTIM_LINUX_AUTHORIZED_KEYS}")
  fi
  candidates+=("${XDR_ROOT}/config/victim-linux-authorized_keys")
  candidates+=("${op_home}/.ssh/id_ed25519.pub")
  candidates+=("${op_home}/.ssh/id_rsa.pub")

  for f in "${candidates[@]}"; do
    if _linux_server_pubkey_file_usable "$f"; then
      printf '%s' "$f"
      return 0
    fi
  done

  shopt -s nullglob
  local -a pubs=("${op_home}"/.ssh/*.pub)
  shopt -u nullglob
  for pub in "${pubs[@]}"; do
    if _linux_server_pubkey_file_usable "$pub"; then
      printf '%s' "$pub"
      return 0
    fi
  done
  return 1
}

# Private key for SSH validation — env override, then pubkey sibling, then ~/.ssh defaults.
linux_server_discover_ssh_identity() {
  local op_home identity pub_src

  if [[ -n "${XDR_LAB_VICTIM_LINUX_SSH_IDENTITY:-}" ]]; then
    identity="${XDR_LAB_VICTIM_LINUX_SSH_IDENTITY}"
    [[ -f "$identity" && -r "$identity" ]] || return 1
    printf '%s' "$identity"
    return 0
  fi

  op_home="$(linux_server_operator_home)"
  if pub_src="$(linux_server_discover_ssh_pubkey_source "$op_home" 2>/dev/null)"; then
    if [[ "$pub_src" == *.pub ]]; then
      identity="${pub_src%.pub}"
      if [[ -f "$identity" && -r "$identity" ]]; then
        printf '%s' "$identity"
        return 0
      fi
    fi
  fi

  for identity in "${op_home}/.ssh/id_ed25519" "${op_home}/.ssh/id_rsa"; do
    [[ -f "$identity" && -r "$identity" ]] || continue
    printf '%s' "$identity"
    return 0
  done
  return 1
}

linux_server_emit_no_ssh_keys_remediation() {
  echo "" >&2
  echo "ERROR:" >&2
  echo "No usable SSH public keys detected." >&2
  echo "" >&2
  echo "Generate one with:" >&2
  echo "  ssh-keygen -t ed25519" >&2
  echo "" >&2
  echo "Then retry:" >&2
  echo "  xdr-lab-vm-manager.sh deploy victim-linux" >&2
  log_structured "ERROR" "deploy_victim_linux_no_ssh_pubkey reason=no_usable_keys"
}

# Populates $out from the first matching source; sets LINUX_SERVER_SSH_PUBKEY_SOURCE.
linux_server_collect_ssh_pubkeys_file() {
  local out="$1"
  local op_home src
  op_home="$(linux_server_operator_home)"
  src="$(linux_server_discover_ssh_pubkey_source "$op_home")" || return 1
  : >"$out"
  grep -E '^[[:space:]]*(#|$)' -v "$src" | sed '/^$/d' >>"$out" || true
  if [[ ! -s "$out" ]]; then
    return 1
  fi
  LINUX_SERVER_SSH_PUBKEY_SOURCE="$src"
  log_structured "INFO" "deploy_victim_linux_authorized_keys path=${src}"
  echo "INFO deploy_victim_linux_authorized_keys path=${src}"
  log_structured "INFO" "linux_server_collect_ssh_pubkeys_file_ok source=${src} path=${out} lines=$(wc -l <"$out")"
  return 0
}

validate_victim_linux_cloud_init_user_data_keys() {
  local user_data="$1" keys_file="$2"
  python3 - "$user_data" "$keys_file" <<'PY'
import pathlib, sys

ud_path, keys_path = sys.argv[1], sys.argv[2]
ud = pathlib.Path(ud_path).read_text(encoding="utf-8")
keys = [
    ln.strip()
    for ln in pathlib.Path(keys_path).read_text(encoding="utf-8").splitlines()
    if ln.strip() and not ln.strip().startswith("#")
]
if not keys:
    sys.exit("keys_file empty after filtering")
missing = [k for k in keys if k not in ud]
if missing:
    sys.exit(f"authorized_keys missing from user-data count={len(missing)}")
if "ssh_pwauth: false" not in ud and "ssh_pwauth:false" not in ud.replace(" ", ""):
    sys.exit("ssh_pwauth must be false")
if "lock_passwd: true" not in ud and "lock_passwd:true" not in ud.replace(" ", ""):
    sys.exit("lock_passwd must be true")
if "name: lab" not in ud:
    sys.exit("users block must define name: lab")
if "ssh_authorized_keys:" not in ud:
    sys.exit("ssh_authorized_keys block missing under users")
PY
}

validate_victim_linux_pre_install_artifacts() {
  local vm="$1" seed="$2" user_data="$3" meta_data="$4" disk="$5" base="$6" keys_file="$7"
  log_structured "INFO" "validate_victim_linux_pre_install_begin vm=${vm}"

  [[ -f "$seed" ]] || {
    log_structured "ERROR" "validate_victim_linux_pre_install_failed vm=${vm} reason=seed_iso_missing path=${seed}"
    return 1
  }
  log_structured "INFO" "validate_victim_linux_seed_iso_ok vm=${vm} path=${seed}"

  [[ -f "$user_data" && -f "$meta_data" ]] || {
    log_structured "ERROR" "validate_victim_linux_pre_install_failed vm=${vm} reason=cloud_init_staging_missing"
    return 1
  }
  log_structured "INFO" "validate_victim_linux_cloud_init_staging_ok vm=${vm} user_data=${user_data} meta_data=${meta_data}"

  if ! validate_victim_linux_cloud_init_user_data_keys "$user_data" "$keys_file"; then
    log_structured "ERROR" "validate_victim_linux_pre_install_failed vm=${vm} reason=authorized_keys_not_in_user_data"
    return 1
  fi
  log_structured "INFO" "validate_victim_linux_authorized_keys_embedded_ok vm=${vm}"

  local backing
  backing="$(qemu-img info --output=json "$disk" 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("backing-filename") or "")' 2>/dev/null || true)"
  if [[ -z "$backing" ]]; then
    log_structured "ERROR" "validate_victim_linux_pre_install_failed vm=${vm} reason=qcow2_backing_missing disk=${disk}"
    return 1
  fi
  if [[ "$(readlink -f "$backing" 2>/dev/null || echo "$backing")" != "$(readlink -f "$base" 2>/dev/null || echo "$base")" ]]; then
    log_structured "ERROR" "validate_victim_linux_pre_install_failed vm=${vm} reason=qcow2_backing_mismatch backing=${backing} expected=${base}"
    return 1
  fi
  log_structured "INFO" "validate_victim_linux_qcow2_backing_ok vm=${vm} disk=${disk} backing=${base}"

  log_structured "INFO" "validate_victim_linux_pre_install_success vm=${vm}"
  return 0
}

validate_victim_linux_libvirt_domain() {
  local vm="$1"
  log_structured "INFO" "validate_victim_linux_libvirt_domain_begin vm=${vm}"
  if ! vm_exists "$vm"; then
    log_structured "ERROR" "validate_victim_linux_libvirt_domain_failed vm=${vm} reason=domain_not_defined"
    return 1
  fi
  local dom_st
  dom_st="$(virsh domstate "$vm" 2>/dev/null | tr -d '\r' || true)"
  log_structured "INFO" "validate_victim_linux_libvirt_domain_ok vm=${vm} state=${dom_st:-unknown}"
  return 0
}

generate_network_config() {
  local out="$1" ip_cidr="$2" gateway="$3" dns="$4"
  cat >"$out" <<EOF
network:
  version: 2
  ethernets:
    labnic:
      match:
        name: "en*"
      dhcp4: false
      dhcp6: false
      addresses:
        - ${ip_cidr}
      routes:
        - to: default
          via: ${gateway}
      nameservers:
        addresses:
          - ${dns}
EOF
}

generate_user_data() {
  local out="$1" keys_file="$2" hostname="$3"
  python3 - "$out" "$keys_file" "$hostname" <<'PY'
import pathlib, sys
outp, kpath, hostn = sys.argv[1], sys.argv[2], sys.argv[3]
keys = [
    ln.strip()
    for ln in pathlib.Path(kpath).read_text(encoding="utf-8").splitlines()
    if ln.strip() and not ln.strip().startswith("#")
]
if not keys:
    sys.exit("no ssh public keys after filtering")
# cloud-init #cloud-config — static network is on the seed ISO (network-config).


def _yaml_dq(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


lines = [
    "#cloud-config",
    f"hostname: {hostn}",
    "fqdn: %s.lab.local" % hostn,
    "manage_etc_hosts: true",
    "package_update: false",
    "package_upgrade: false",
    "ssh_pwauth: false",
    "lock_passwd: true",
    "users:",
    "  - name: lab",
    "    sudo: ALL=(ALL) NOPASSWD:ALL",
    "    groups: sudo",
    "    shell: /bin/bash",
    "    ssh_authorized_keys:",
]
for k in keys:
    lines.append("      - " + _yaml_dq(k))
lines.extend(
    [
        "packages:",
        "  - openssh-server",
        "  - qemu-guest-agent",
        "runcmd:",
        "  - [ systemctl, enable, qemu-guest-agent ]",
        "  - [ systemctl, start, qemu-guest-agent ]",
        "  - [ systemctl, enable, ssh ]",
        "  - [ systemctl, start, ssh ]",
    ]
)
pathlib.Path(outp).write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

create_cloud_init_seed_iso() {
  local seed_out="$1" user_data="$2" meta_data="$3" network_config="$4"
  if command -v cloud-localds >/dev/null 2>&1; then
    cloud-localds --network-config="${network_config}" \
      "${seed_out}" "${user_data}" "${meta_data}"
    return 0
  fi
  require_cmd genisoimage
  local staging
  staging="$(mktemp -d)"
  cp -f -- "${user_data}" "${staging}/user-data"
  cp -f -- "${meta_data}" "${staging}/meta-data"
  cp -f -- "${network_config}" "${staging}/network-config"
  ( cd "${staging}" && genisoimage -quiet -output "${seed_out}" -volid cidata -joliet -rock \
      user-data meta-data network-config )
  rm -rf "${staging}"
}

linux_server_ssh_user_candidates() {
  local -a candidates=()
  local u
  if [[ -n "${VICTIM_LINUX_SSH_USER:-}" ]]; then
    candidates+=("${VICTIM_LINUX_SSH_USER}")
  fi
  for u in ${LINUX_SERVER_SSH_USER_CANDIDATES}; do
    local seen=0
    for c in "${candidates[@]}"; do
      [[ "$c" == "$u" ]] && seen=1 && break
    done
    [[ "$seen" -eq 0 ]] && candidates+=("$u")
  done
  printf '%s\n' "${candidates[@]}"
}

linux_server_print_rendered_cloud_init() {
  local user_data="$1" network_config="$2"
  echo ""
  echo "=== rendered cloud-init ==="
  echo ""
  echo "users:"
  sed -n '/^users:/,/^[^ ]/p' "$user_data" 2>/dev/null | sed '$d' || true
  echo ""
  echo "ssh_authorized_keys (lab user):"
  awk '
    /^[[:space:]]+- name: lab$/ { in_lab=1; next }
    in_lab && /^[[:space:]]+ssh_authorized_keys:/ { in_keys=1; next }
    in_lab && in_keys && /^[[:space:]]+- / { sub(/^[[:space:]]+- /, ""); print; next }
    in_lab && in_keys && /^[^[:space:]]/ { exit }
    in_lab && /^[[:space:]]+- name:/ && !/name: lab/ { exit }
  ' "$user_data" 2>/dev/null || true
  echo ""
  echo "network config (addresses):"
  awk '/addresses:/{p=1} p{print} p && /^[^ ]/ && !/addresses:/{exit}' "$network_config" 2>/dev/null || true
  echo ""
}

linux_server_emit_post_deploy_artifacts() {
  local vm="$1" run_vm="$2" disk="$3" seed="$4" ci_dir="$5"
  echo ""
  echo "cloud-init artifacts:"
  if [[ -d "$ci_dir" ]]; then
    find "$ci_dir" -maxdepth 1 -type f -printf '  %p\n' 2>/dev/null | sort || ls -la "$ci_dir" 2>/dev/null || true
  else
    echo "  (cloud-init dir missing: ${ci_dir})"
  fi
  echo ""
  echo "libvirt disk:"
  echo "  ${disk}"
  if [[ -f "$disk" ]]; then
    qemu-img info "$disk" 2>/dev/null | sed 's/^/  /' || true
  fi
  echo ""
  echo "seed path:"
  echo "  ${seed}"
  echo ""
  echo "virsh console hint:"
  echo "  virsh console ${vm}"
  echo ""
}

linux_server_emit_deploy_failure_diagnostics() {
  local vm="$1" ip="$2" run_vm="$3" disk="$4" seed="$5" ci_dir="$6" reason="${7:-unknown}"
  local dom_st domifaddr_out domiflist_out ping_rc ping_out

  echo ""
  echo "=== ${vm} diagnostics (reason=${reason}) ==="
  echo ""
  echo "virsh domstate ${vm}:"
  dom_st="$(virsh domstate "$vm" 2>/dev/null | tr -d '\r' || echo "(virsh failed)")"
  echo "  ${dom_st}"
  echo ""
  echo "virsh domifaddr ${vm}:"
  domifaddr_out="$(virsh domifaddr "$vm" 2>&1 || true)"
  printf '%s\n' "${domifaddr_out}" | sed 's/^/  /'
  echo ""
  echo "virsh domiflist ${vm}:"
  domiflist_out="$(virsh domiflist "$vm" 2>&1 || true)"
  printf '%s\n' "${domiflist_out}" | sed 's/^/  /'
  echo ""
  echo "ping ${ip}:"
  if ping -c 3 -W 2 "$ip" >/tmp/xdr-victim-linux-ping.$$ 2>&1; then
    ping_rc=0
  else
    ping_rc=$?
  fi
  sed 's/^/  /' /tmp/xdr-victim-linux-ping.$$ 2>/dev/null || true
  rm -f /tmp/xdr-victim-linux-ping.$$ 2>/dev/null || true
  echo "  ping_exit=${ping_rc}"
  echo ""
  echo "cloud-init status hint (from guest console or after SSH):"
  echo "  cloud-init status --long"
  echo "  journalctl -u cloud-init -n 80"
  echo ""
  echo "disk path:"
  echo "  ${disk}"
  echo ""
  echo "seed path:"
  echo "  ${seed}"
  echo ""
  echo "cloud-init artifacts:"
  if [[ -d "$ci_dir" ]]; then
    find "$ci_dir" -maxdepth 1 -type f -printf '  %p\n' 2>/dev/null | sort || ls -la "$ci_dir" 2>/dev/null || true
  else
    echo "  (preserved dir missing: ${ci_dir})"
  fi
  echo ""
  echo "try:"
  echo "  virsh console ${vm}"
  echo ""
  log_structured "WARN" "linux_server_deploy_failure_preserved vm=${vm} reason=${reason} run_vm=${run_vm}"
}

# Deploy failure preserve mode — never destroy domain or delete forensic artifacts.
linux_server_handle_deploy_failure() {
  local vm="$1" run_vm="$2" disk="$3" seed="$4" ci_dir="$5" reason="$6" ip="${7:-}"
  linux_server_emit_deploy_failure_diagnostics "$vm" "$ip" "$run_vm" "$disk" "$seed" "$ci_dir" "$reason"
}

linux_server_rollback_deploy() {
  local vm="$1" run_vm="$2" reason="$3"
  log_structured "WARN" "linux_server_rollback_deploy_begin vm=${vm} reason=${reason}"
  virsh destroy "$vm" >/dev/null 2>&1 || true
  virsh undefine "$vm" --managed-save --snapshots-metadata >/dev/null 2>&1 || \
    virsh undefine "$vm" >/dev/null 2>&1 || true
  rm -rf "${run_vm}" 2>/dev/null || true
  log_structured "WARN" "linux_server_rollback_deploy_end vm=${vm}"
}

validate_vm_boot() {
  local vm="$1"
  local deadline=$((SECONDS + 420))
  log_structured "INFO" "validate_vm_boot_begin vm=${vm}"
  while (( SECONDS < deadline )); do
    local st
    st="$(virsh domstate "$vm" 2>/dev/null | tr -d '\r' || true)"
    if [[ "$st" == "running" ]]; then
      log_structured "INFO" "validate_vm_boot_ok vm=${vm} state=running"
      return 0
    fi
    sleep 3
  done
  log_structured "ERROR" "validate_vm_boot_failed vm=${vm} reason=timeout_not_running"
  return 1
}

validate_ssh_connectivity() {
  local ip="$1"
  shift
  local -a users=() ssh_cmd=()
  local user deadline identity last_cmd_summary=""
  local per_attempt_timeout=7

  if [[ $# -gt 0 ]]; then
    users=("$@")
  else
    while IFS= read -r user; do
      [[ -n "$user" ]] && users+=("$user")
    done < <(linux_server_ssh_user_candidates)
  fi
  [[ ${#users[@]} -gt 0 ]] || users=(ubuntu lab)

  identity="$(linux_server_discover_ssh_identity)" || {
    log_structured "ERROR" "validate_ssh_connectivity_no_identity"
    echo "ERROR ssh_validation_failed reason=no_ssh_identity" >&2
    return 1
  }

  deadline=$((SECONDS + XDR_LAB_SSH_VALIDATION_TIMEOUT))
  log_structured "INFO" "validate_ssh_connectivity_begin ip=${ip} users=${users[*]} identity=${identity} timeout=${XDR_LAB_SSH_VALIDATION_TIMEOUT}"
  LINUX_SERVER_SSH_VALIDATED_USER=""

  while (( SECONDS < deadline )); do
    for user in "${users[@]}"; do
      ssh_cmd=(
        ssh
        -i "$identity"
        -o IdentitiesOnly=yes
        -o BatchMode=yes
        -o ConnectTimeout=5
        -o StrictHostKeyChecking=no
      )
      if [[ -n "${XDR_LAB_SSH_USER_KNOWN_HOSTS_FILE:-}" ]]; then
        ssh_cmd+=(-o "UserKnownHostsFile=${XDR_LAB_SSH_USER_KNOWN_HOSTS_FILE}")
      fi
      ssh_cmd+=("${user}@${ip}" "hostname")

      last_cmd_summary="ssh -i ${identity} -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no"
      if [[ -n "${XDR_LAB_SSH_USER_KNOWN_HOSTS_FILE:-}" ]]; then
        last_cmd_summary+=" -o UserKnownHostsFile=${XDR_LAB_SSH_USER_KNOWN_HOSTS_FILE}"
      fi
      last_cmd_summary+=" ${user}@${ip} hostname"

      if timeout "$per_attempt_timeout" "${ssh_cmd[@]}" >/dev/null 2>&1; then
        LINUX_SERVER_SSH_VALIDATED_USER="$user"
        log_structured "INFO" "validate_ssh_connectivity_ok ip=${ip} user=${user} identity=${identity}"
        echo "INFO ssh_validation_success user=${user}"
        return 0
      fi
    done
    sleep 3
  done

  log_structured "ERROR" "validate_ssh_connectivity_failed ip=${ip} users=${users[*]} identity=${identity} cmd=${last_cmd_summary}"
  echo "ERROR ssh_validation_failed cmd_summary=\"${last_cmd_summary}\"" >&2
  return 1
}

validate_reboot_persistence() {
  local vm="$1" ip="$2" user="$3"
  if [[ "${XDR_LAB_SKIP_REBOOT_TEST:-}" == "1" ]]; then
    log_structured "INFO" "validate_reboot_persistence_skip vm=${vm} reason=env_XDR_LAB_SKIP_REBOOT_TEST"
    return 0
  fi
  log_structured "INFO" "validate_reboot_persistence_begin vm=${vm}"
  virsh reboot "$vm" >/dev/null 2>&1 || die "virsh reboot failed for ${vm}"
  sleep 15
  if ! validate_vm_boot "$vm"; then
    log_structured "ERROR" "validate_reboot_persistence_failed vm=${vm} step=boot_after_reboot"
    return 1
  fi
  if ! validate_ssh_connectivity "$ip"; then
    log_structured "ERROR" "validate_reboot_persistence_failed vm=${vm} step=ssh_after_reboot"
    return 1
  fi
  log_structured "INFO" "validate_reboot_persistence_ok vm=${vm}"
  return 0
}

deploy_linux_server_cloud() {
  local vm="$1"
  local nodownload="${2:-0}"

  require_cmd qemu-img
  require_cmd virt-install
  require_cmd virsh
  require_cmd ssh
  if ! command -v cloud-localds >/dev/null 2>&1; then
    require_cmd genisoimage
  fi

  local cpu mem autostart disk_gb gw dns cidr hostn json_ip
  cpu="$(get_vm_field "$vm" cpu)"
  mem="$(get_vm_field "$vm" memory)"
  autostart="$(get_vm_field "$vm" autostart)"
  disk_gb="$(get_vm_field "$vm" disk_size_gb)"
  gw="$(net_global_field gateway)"
  dns="$(net_global_field dns)"
  cidr="$(get_lab_subnet_cidr)"
  hostn="$(get_vm_field "$vm" name)"
  json_ip="$(get_vm_field "$vm" internal_ip)"

  if [[ "$json_ip" != "${VICTIM_LINUX_MATERIALIZED_IP}" ]]; then
    log_structured "WARN" "deploy_linux_server_ip_mismatch vm=${vm} lab_vms_json_internal_ip=${json_ip} materialized_ip=${VICTIM_LINUX_MATERIALIZED_IP} hint=align_lab_vms_or_set_VICTIM_LINUX_MATERIALIZED_IP"
  fi

  local static_ip="${VICTIM_LINUX_MATERIALIZED_IP}"
  local cidr_suffix="${cidr##*/}"
  local ip_cidr="${static_ip}/${cidr_suffix}"

  local base="${IMG}/victim-linux/${VICTIM_LINUX_CLOUD_IMAGE_BASENAME}"
  local run_vm="${RUN}/victim-linux"
  local ci_dir="${run_vm}/cloud-init"
  local disk="${run_vm}/root.qcow2"
  local seed="${run_vm}/seed.iso"
  local keys ud md nc ssh_key_src probe_keys

  if [[ "$nodownload" != "1" ]]; then
    download_linux_server_cloud_base
  fi
  [[ -f "$base" ]] || die "Missing Ubuntu cloud base image: $base (run download victim-linux)"

  probe_keys="${ci_dir}/.probe-authorized_keys.lines"
  mkdir -p "$ci_dir"
  if ! linux_server_collect_ssh_pubkeys_file "$probe_keys"; then
    rm -f "$probe_keys" 2>/dev/null || true
    linux_server_emit_no_ssh_keys_remediation
    die "No usable SSH public keys detected for victim-linux"
  fi
  ssh_key_src="${LINUX_SERVER_SSH_PUBKEY_SOURCE:-unknown}"
  rm -f "$probe_keys" 2>/dev/null || true

  echo "=== victim-linux deployment ==="
  echo "Base image: ${base}"
  echo "SSH key: ${ssh_key_src}"
  echo "Libvirt network: ${LAB_OVS_NETWORK}"
  echo "Static IP: ${static_ip}"
  echo "Cloud-init: enabled"
  log_structured "INFO" "deploy_victim_linux_banner base_image=${base} ssh_key=${ssh_key_src} libvirt_network=${LAB_OVS_NETWORK} static_ip=${static_ip} cloud_init=enabled"

  if vm_exists "$vm"; then
    log_structured "INFO" "deploy_linux_server_idempotent_domain_exists vm=${vm}"
    virsh start "$vm" >/dev/null 2>&1 || true
    apply_autostart "$vm"
    if ! validate_vm_boot "$vm"; then
      die "Existing domain ${vm} is not running; destroy and redeploy"
    fi
    if ! validate_ssh_connectivity "$static_ip"; then
      linux_server_handle_deploy_failure "$vm" "$run_vm" "$disk" "$seed" "$ci_dir" "idempotent_ssh_validation_failed" "$static_ip"
      die "Existing domain ${vm} failed SSH validation (VM and artifacts preserved for debugging)"
    fi
    log_structured "INFO" "deploy_linux_server_idempotent_ok vm=${vm}"
    validate_vm_libvirt_network_attach "$vm" || true
    linux_server_emit_post_deploy_artifacts "$vm" "$run_vm" "$disk" "$seed" "$ci_dir"
    _invoke_state_refresh "$vm" 0
    return 0
  fi

  mkdir -p "$ci_dir" "$run_vm"
  keys="${ci_dir}/authorized_keys.lines"
  ud="${ci_dir}/user-data"
  md="${ci_dir}/meta-data"
  nc="${ci_dir}/network-config"

  linux_server_collect_ssh_pubkeys_file "$keys" || {
    linux_server_emit_no_ssh_keys_remediation
    die "No usable SSH public keys detected for victim-linux"
  }

  generate_user_data "$ud" "$keys" "$hostn"
  generate_network_config "$nc" "$ip_cidr" "$gw" "$dns"
  cat >"$md" <<EOF
instance-id: ${vm}
local-hostname: ${hostn}
dsmode: local
EOF

  linux_server_print_rendered_cloud_init "$ud" "$nc"

  if [[ -f "$disk" || -f "$seed" ]]; then
    log_structured "WARN" "deploy_linux_server_cleanup_stale_artifacts vm=${vm}"
    rm -f "$disk" "$seed" 2>/dev/null || true
  fi

  log_structured "INFO" "deploy_linux_server_qemu_img_create vm=${vm} backing=${base}"
  qemu-img create -f qcow2 -F qcow2 -b "$base" "$disk" "${disk_gb}G"
  qemu-img resize "$disk" "${disk_gb}G" >/dev/null

  create_cloud_init_seed_iso "$seed" "$ud" "$md" "$nc"

  if ! validate_victim_linux_pre_install_artifacts "$vm" "$seed" "$ud" "$md" "$disk" "$base" "$keys"; then
    linux_server_handle_deploy_failure "$vm" "$run_vm" "$disk" "$seed" "$ci_dir" "cloud_init_pre_install_validation_failed" "$static_ip"
    die "victim-linux cloud-init pre-install validation failed (artifacts preserved at ${ci_dir})"
  fi

  local autostart_flag=( )
  if [[ "$autostart" == "True" || "$autostart" == "true" || "$autostart" == "1" ]]; then
    autostart_flag=(--autostart)
  fi

  log_structured "INFO" "deploy_linux_server_virt_install_begin vm=${vm} libvirt_network=${LAB_OVS_NETWORK} ip=${static_ip}"
  if ! virt_install_libvirt_network virtio \
    --name "$vm" \
    --memory "$mem" \
    --vcpus "$cpu" \
    --disk "path=${disk},format=qcow2,bus=virtio" \
    --disk "path=${seed},device=cdrom,bus=sata" \
    --import \
    --os-variant ubuntu24.04 \
    --virt-type kvm \
    --noautoconsole \
    "${autostart_flag[@]}"; then
    linux_server_handle_deploy_failure "$vm" "$run_vm" "$disk" "$seed" "$ci_dir" "virt_install_failed" "$static_ip"
    die "virt-install failed for ${vm} (artifacts preserved)"
  fi

  apply_autostart "$vm"

  validate_vm_libvirt_network_attach "$vm" || true

  if ! validate_victim_linux_libvirt_domain "$vm"; then
    linux_server_handle_deploy_failure "$vm" "$run_vm" "$disk" "$seed" "$ci_dir" "libvirt_domain_validation_failed" "$static_ip"
    die "victim-linux libvirt domain validation failed (VM and artifacts preserved)"
  fi

  if ! validate_vm_boot "$vm"; then
    linux_server_handle_deploy_failure "$vm" "$run_vm" "$disk" "$seed" "$ci_dir" "boot_validation_failed" "$static_ip"
    die "Boot validation failed for ${vm} (VM and artifacts preserved)"
  fi
  if ! validate_ssh_connectivity "$static_ip"; then
    linux_server_handle_deploy_failure "$vm" "$run_vm" "$disk" "$seed" "$ci_dir" "ssh_validation_failed" "$static_ip"
    die "SSH validation failed for ${vm} (ip=${static_ip}) — VM, disk, seed, and cloud-init artifacts preserved"
  fi
  validate_reboot_persistence "$vm" "$static_ip" "${LINUX_SERVER_SSH_VALIDATED_USER:-lab}" || {
    linux_server_handle_deploy_failure "$vm" "$run_vm" "$disk" "$seed" "$ci_dir" "reboot_persistence_failed" "$static_ip"
    die "Reboot persistence validation failed for ${vm} (VM and artifacts preserved)"
  }

  local nat_json
  nat_json="$(get_vm_field "$vm" external_nat_port_mapping)"
  log_structured "INFO" "deploy_linux_server_network_hints vm=${vm} internal_ip=${static_ip} nat=${nat_json}"
  linux_server_emit_post_deploy_artifacts "$vm" "$run_vm" "$disk" "$seed" "$ci_dir"
  log_structured "INFO" "deploy_linux_server_end vm=${vm}"
  _invoke_state_refresh "$vm" 1
}

deploy_vm() {
  local vm="$1"
  local nodownload="${2:-0}"

  [[ -f "$CFG" ]] || die "Missing config $CFG"

  local vtype
  vtype="$(python3 - "$CFG" "$vm" <<'PY'
import json, sys
path, vm = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as f:
    cfg = json.load(f)
print(cfg["vms"][vm].get("type", ""))
PY
)"

  log_structured "INFO" "deploy_vm_begin vm=${vm} type=${vtype}"

  if dry_run_active; then
    if [[ "$vtype" == "windows" ]]; then
      deploy_windows_vm "$vm" "$nodownload"
      return 0
    fi
    log_structured "INFO" "dry_run_skip deploy_vm vm=${vm}"
    return 0
  fi

  print_libvirt_network_topology
  validate_libvirt_ovs_network_pre_deploy

  if [[ "$vm" == "sensor-vm" || "$vtype" == "sensor" ]]; then
    if [[ "$nodownload" != "1" ]]; then
      download_vm_image "$vm"
    fi
    deploy_sensor_vm "$vm" "$nodownload" "$(vm_json_field_optional "$vm" sensor_version "6.2.0")"
    apply_autostart "$vm"
    log_structured "INFO" "deploy_vm_end vm=${vm} (sensor)"
    return 0
  fi

  if [[ "$vm" == "victim-linux" ]]; then
    if [[ "$nodownload" != "1" ]]; then
      download_vm_image "$vm"
    else
      log_structured "INFO" "deploy_linux_server_skip_download vm=${vm} nodownload=1"
    fi
    deploy_linux_server_cloud "$vm" "$nodownload"
    log_structured "INFO" "deploy_vm_end vm=${vm} (victim-linux-cloud)"
    return 0
  fi

  if [[ "$vtype" == "windows" ]]; then
    deploy_windows_vm "$vm" "$nodownload"
    log_structured "INFO" "deploy_vm_end vm=${vm} (windows-golden-uefi)"
    return 0
  fi

  require_cmd virt-install
  require_cmd virsh
  require_cmd qemu-img

  local fname cpu mem osv autostart disk_gb
  fname="$(get_vm_field "$vm" disk_filename)"
  cpu="$(get_vm_field "$vm" cpu)"
  mem="$(get_vm_field "$vm" memory)"
  osv="$(get_vm_field "$vm" os_variant)"
  autostart="$(get_vm_field "$vm" autostart)"
  disk_gb="$(get_vm_field "$vm" disk_size_gb)"

  local src="${IMG}/${vm}/${fname}"
  [[ -f "$src" ]] || die "Missing qcow2 (run download ${vm}): $src"

  local dst="${RUN}/${vm}-runtime.qcow2"
  if [[ ! -f "$dst" ]]; then
    cp -f -- "$src" "$dst"
  fi
  qemu-img resize "$dst" "${disk_gb}G" >/dev/null

  if vm_exists "$vm"; then
    log_structured "INFO" "deploy_vm_idempotent_exists vm=${vm}"
    apply_autostart "$vm"
    _invoke_state_refresh "$vm" 0
    return 0
  fi

  local autostart_flag=( )
  if [[ "$autostart" == "True" || "$autostart" == "true" || "$autostart" == "1" ]]; then
    autostart_flag=(--autostart)
  fi

  log_structured "INFO" "deploy_vm_virt_install vm=${vm}"
  virt_install_libvirt_network virtio \
    --name "$vm" \
    --memory "$mem" \
    --vcpus "$cpu" \
    --disk "path=${dst},format=qcow2,bus=virtio" \
    --import \
    --os-variant "$osv" \
    --virt-type kvm \
    --noautoconsole \
    "${autostart_flag[@]}"

  validate_vm_libvirt_network_attach "$vm" || true

  local internal_ip nat_json
  internal_ip="$(get_vm_field "$vm" internal_ip)"
  nat_json="$(get_vm_field "$vm" external_nat_port_mapping)"
  log_structured "INFO" "deploy_vm_network_hints vm=${vm} internal_ip=${internal_ip} nat=${nat_json}"

  log_structured "INFO" "deploy_vm_end vm=${vm}"
  _invoke_state_refresh "$vm" 1
}

apply_autostart() {
  local vm="$1"
  local autostart
  autostart="$(get_vm_field "$vm" autostart)"
  if [[ "$autostart" == "True" || "$autostart" == "true" || "$autostart" == "1" ]]; then
    virsh autostart "$vm" >/dev/null 2>&1 || true
  else
    virsh autostart --disable "$vm" >/dev/null 2>&1 || true
  fi
}

start_vm() {
  local vm="$1"
  if dry_run_active; then
    log_structured "INFO" "dry_run_skip start_vm vm=${vm}"
    return 0
  fi
  if ! vm_exists "$vm"; then
    die "VM not defined: $vm"
  fi
  log_structured "INFO" "start_vm vm=${vm}"
  local errf rc vtype
  errf="$(mktemp)"
  set +e
  virsh start "$vm" 2>"${errf}"
  rc=$?
  set -e
  if [[ "${rc}" -ne 0 ]]; then
    vtype="$(vm_json_field_optional "${vm}" type "")"
    if [[ "${vtype}" == "windows" ]] && grep -qiE 'ovmf|nvram|pflash|already in use|lock' "${errf}" 2>/dev/null; then
      log_structured "WARN" "windows_start_nvram_lock_detected vm=${vm} rc=${rc}"
      repair_windows_vm_runtime "${vm}" || true
      set +e
      virsh start "$vm" 2>>"${errf}"
      rc=$?
      set -e
    fi
  fi
  if [[ "${rc}" -ne 0 ]]; then
    sed 's/^/virsh: /' "${errf}" >&2 || true
    rm -f "${errf}"
    die "virsh start failed for $vm"
  fi
  rm -f "${errf}"
  _invoke_state_refresh "$vm" 0
}

stop_vm() {
  local vm="$1"
  if dry_run_active; then
    log_structured "INFO" "dry_run_skip stop_vm vm=${vm}"
    return 0
  fi
  if ! vm_exists "$vm"; then
    log_structured "WARN" "stop_vm_missing vm=${vm}"
    return 0
  fi
  log_structured "INFO" "stop_vm vm=${vm}"
  virsh destroy "$vm" >/dev/null 2>&1 || virsh shutdown "$vm" >/dev/null 2>&1 || true
  _invoke_state_refresh "$vm" 0
}

destroy_vm() {
  local vm="$1"
  if dry_run_active; then
    log_structured "INFO" "dry_run_skip destroy_vm vm=${vm}"
    return 0
  fi
  if ! vm_exists "$vm"; then
    log_structured "WARN" "destroy_vm_missing vm=${vm}"
    rm -f "${RUN}/${vm}-runtime.qcow2" || true
    rm -rf "${RUN}/${vm}" 2>/dev/null || true
    _invoke_state_refresh "$vm" 0
    return 0
  fi
  log_structured "INFO" "destroy_vm vm=${vm}"
  virsh destroy "$vm" >/dev/null 2>&1 || true
  virsh undefine "$vm" --managed-save --snapshots-metadata >/dev/null 2>&1 || \
    virsh undefine "$vm" >/dev/null 2>&1 || true
  rm -f "${RUN}/${vm}-runtime.qcow2" || true
  rm -rf "${RUN}/${vm}" 2>/dev/null || true
  _invoke_state_refresh "$vm" 0
}

show_vm_status() {
  local target="$1"
  require_cmd virsh
  if [[ "$target" == "all" ]]; then
    virsh list --all
    if [[ "${_XDR_READONLY_CLI}" != "1" ]]; then
      local v
      for v in $(list_vms); do
        _invoke_state_refresh "$v" 0
      done
    fi
    return 0
  fi
  if virsh dominfo "$target" >/dev/null 2>&1; then
    virsh dominfo "$target"
    virsh domifaddr "$target" --source agent 2>/dev/null || true
    virsh domifaddr "$target" --source lease 2>/dev/null || true
  else
    log_structured "WARN" "status_domain_missing vm=${target}"
  fi
  if [[ "${_XDR_READONLY_CLI}" != "1" ]]; then
    _invoke_state_refresh "$target" 0
  fi
}

iterate_vms() {
  local action="$1"
  shift
  local v
  for v in $(list_vms); do
    "$action" "$v" "$@"
  done
}

# Operator-facing summary: lab-vms.json NAT map + detected host IPv4 (read-only).
show_lab_access() {
  log_structured "INFO" "lab_access_begin cfg=${CFG}"
  require_cmd python3
  local ext_ip
  ext_ip="$(xdr_primary_ipv4 2>/dev/null || true)"
  XDR_LAB_ACCESS_EXT_IP="${ext_ip}" \
    XDR_LAB_ACCESS_WEB_CONSOLE_PORT="${XDR_LAB_WEB_CONSOLE_PORT:-6080}" \
    XDR_LAB_ACCESS_WEB_CONSOLE_PORT_MAP="${XDR_LAB_WEB_CONSOLE_PORT_MAP:-}" \
    python3 - "$CFG" <<'PY'
import json, os, sys

path = sys.argv[1]
ext = (os.environ.get("XDR_LAB_ACCESS_EXT_IP") or "").strip()
wc_port = int(os.environ.get("XDR_LAB_ACCESS_WEB_CONSOLE_PORT") or "6080")
wc_map = (os.environ.get("XDR_LAB_ACCESS_WEB_CONSOLE_PORT_MAP") or "").strip()
with open(path, "r", encoding="utf-8") as f:
    cfg = json.load(f)
net = cfg.get("network", {})
vms = cfg.get("vms", {})

print("XDR Lab — operator access (reverse NAT)")
print("")
print(f"Lab subnet: {net.get('lab_subnet_cidr', '')}")
print(f"Lab gateway: {net.get('gateway', '')}")
if ext:
    print(f"Appliance external IPv4 (detected): {ext}")
else:
    print("Appliance external IPv4: <not detected — use the host's routable address>")
print("")
print("Canonical lab contract (Golden Image DNAT + inventory; core three VMs):")
print("  VM               internal_ip    service   external→internal (TCP)")
print("  sensor-vm        10.10.10.10    ssh       1022 → 22")
print("  victim-linux     10.10.10.20    ssh       2022 → 22")
print("  windows-victim   10.10.10.30    rdp       3389 → 3389")
print("")
print("Optional management (websockify → 127.0.0.1 QEMU VNC; not iptables DNAT):")
if wc_map:
    for entry in wc_map.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" in entry:
            vm, port = entry.split("=", 1)
        elif ":" in entry:
            vm, port = entry.split(":", 1)
        else:
            continue
        vm, port = vm.strip(), port.strip()
        if vm and port.isdigit():
            print(f"  {vm:<16} 127.0.0.1      web UI    {port} → http://127.0.0.1:{port}/")
else:
    print(
        f"  (host)           127.0.0.1      web UI    {wc_port} → websockify/noVNC (lab web-console start)"
    )
print("  See: docs/web-console.md")
print("")
print("Validate (read-only):")
print("  bash scripts/xdr-lab-vm-manager.sh nat verify --iptables-only")
print("  bash scripts/xdr-lab-vm-manager.sh web-console verify <vm>")
print("  ${XDR_ROOT}/bootstrap/validate-web-console.sh")
print("")

# lab-vms.json must mirror the same external ports / internal IPs for core VMs.
CONTRACT = (
    ("sensor-vm", "10.10.10.10", ("ssh", 1022)),
    ("victim-linux", "10.10.10.20", ("ssh", 2022)),
    ("windows-victim", "10.10.10.30", ("rdp", 3389)),
)
warn = []
for vm_name, canon_ip, (svc, canon_port) in CONTRACT:
    rec = vms.get(vm_name) or {}
    ip = (rec.get("internal_ip") or "").strip()
    m = rec.get("external_nat_port_mapping") or {}
    got = m.get(svc)
    if ip != canon_ip:
        warn.append(f"  {vm_name}: internal_ip is {ip!r}, expected {canon_ip}")
    if got != canon_port:
        warn.append(
            f"  {vm_name}: external_nat_port_mapping[{svc}] is {got!r}, expected {canon_port}"
        )
if warn:
    print("WARNING: lab-vms.json disagrees with canonical contract for a core VM:")
    print("\n".join(warn))
    print("")

print("Per-VM inventory (from lab-vms.json; ext:host ports use detected external IP when shown):")
core_first = ["sensor-vm", "victim-linux", "windows-victim"]
seen = set()
order = [n for n in core_first if n in vms] + sorted(n for n in vms if n not in core_first)
for name in order:
    vm = vms[name]
    ip = vm.get("internal_ip", "")
    print(f"  {name}")
    print(f"    internal_ip: {ip}")
    m = vm.get("external_nat_port_mapping") or {}
    if not m:
        print("    external_nat_port_mapping: (none)")
        print("")
        continue
    for svc, port in sorted(m.items()):
        if ext:
            print(f"    {svc}: {ext}:{port}")
        else:
            print(f"    {svc}: <external-ip>:{port}")
    print("")
PY
  log_structured "INFO" "lab_access_end"
}

# Destructive: stop then destroy every VM key in lab-vms.json (same contract as stop/destroy all).
lab_cleanup_all() {
  log_structured "WARN" "lab_cleanup_all_begin destructive=true"
  echo "NOTICE: Stopping and destroying ALL lab VMs listed in ${CFG} ..." >&2
  local v
  for v in $(list_vms); do
    stop_vm "$v" || true
  done
  for v in $(list_vms); do
    destroy_vm "$v" || true
  done
  log_structured "WARN" "lab_cleanup_all_end"
  echo "Lab cleanup finished." >&2
}

# =============================================================================
# Lab snapshot orchestration — batch across XDR_LAB_SNAPSHOT_VM_LIST (default
# sensor-vm victim-linux windows-victim). State: ${STATED}/snapshots.json
# (snapshot_state.py). Libvirt mutations only via virsh; appliance_cli.py
# must not reimplement snapshot logic.
#
# UEFI/pflash domains (windows-victim): external disk-only snapshots
# (--disk-only); internal qcow2 snapshots are unsupported by libvirt.
# Linux/BIOS domains: internal domain snapshots (existing behavior).
# =============================================================================

_snapshot_helper_ok() {
  if [[ ! -f "${SNAPSHOT_HELPER}" ]]; then
    log_structured "ERROR" "snapshot_helper_missing path=${SNAPSHOT_HELPER}"
    return 1
  fi
  return 0
}

_snapshot_vms_csv() {
  echo "${XDR_LAB_SNAPSHOT_VM_LIST}" | tr ' ' ','
}

_snapshot_is_target_vm() {
  local n="$1" v
  for v in ${XDR_LAB_SNAPSHOT_VM_LIST}; do
    [[ "${n}" == "${v}" ]] && return 0
  done
  return 1
}

_snapshot_usage() {
  cat >&2 <<EOF
Usage: $(basename "$0") snapshot <create|revert|list|delete> ...

  snapshot create [<vm>] [<snapshot-name>]
      Batch (all targets: ${XDR_LAB_SNAPSHOT_VM_LIST}) when <vm> is omitted.
      With <vm>: create only on that domain. Name defaults to xdr-lab-<UTC> if omitted.

  snapshot revert [<vm>] <snapshot-name>
      Batch all targets when <vm> is omitted.

  snapshot delete [<vm>] <snapshot-name>
      Batch all targets when <vm> is omitted.

  snapshot list [<vm>]
      List all orchestration targets when <vm> is omitted.

  UEFI/pflash VMs (e.g. windows-victim) use external disk-only snapshots.

Examples:
  $(basename "$0") snapshot create pre-attack
  $(basename "$0") snapshot create windows-victim test-delete
  $(basename "$0") snapshot list windows-victim
  $(basename "$0") snapshot delete windows-victim test-delete
EOF
}

snapshot_vm_policy() {
  local vm="$1"
  _snapshot_helper_ok || { echo internal; return 0; }
  python3 "${SNAPSHOT_HELPER}" vm-policy --vm "${vm}" 2>/dev/null || echo internal
}

snapshot_backup_uefi_nvram() {
  local vm="$1" nm="$2"
  local src="${RUN}/${vm}/nvram/OVMF_VARS.fd"
  local dst_dir="${RUN}/${vm}/snapshots/${nm}"
  if [[ ! -f "${src}" ]]; then
    return 0
  fi
  if ! mkdir -p "${dst_dir}" 2>/dev/null; then
    log_structured "WARN" "snapshot_nvram_backup_skipped vm=${vm} name=${nm} reason=mkdir_failed path=${dst_dir}"
    return 0
  fi
  if ! cp -a "${src}" "${dst_dir}/OVMF_VARS.fd" 2>/dev/null; then
    log_structured "WARN" "snapshot_nvram_backup_skipped vm=${vm} name=${nm} reason=copy_failed"
  fi
}

snapshot_create_vm() {
  local vm="$1" nm="$2" errf="$3"
  local policy
  policy="$(snapshot_vm_policy "$vm")"
  if [[ "${policy}" == "external_disk" ]]; then
    if python3 "${SNAPSHOT_HELPER}" external-create \
      --vm "${vm}" --snapshot-name "${nm}" --runtime-dir "${RUN}" \
      2>"${errf}"; then
      snapshot_backup_uefi_nvram "${vm}" "${nm}"
      SNAPSHOT_MODE=external_disk _snapshot_result_line "${vm}" "1" "" "${linesf_global:-}"
      return 0
    fi
    return 1
  fi
  if virsh snapshot-create-as "${vm}" "${nm}" \
    --description "xdr-lab orchestrated batch" >/dev/null 2>"${errf}"; then
    SNAPSHOT_MODE=internal _snapshot_result_line "${vm}" "1" "" "${linesf_global:-}"
    return 0
  fi
  return 1
}

snapshot_revert_vm() {
  local vm="$1" nm="$2" errf="$3"
  local policy
  policy="$(snapshot_vm_policy "$vm")"
  if [[ "${policy}" == "external_disk" ]]; then
    if python3 "${SNAPSHOT_HELPER}" external-revert \
      --vm "${vm}" --snapshot-name "${nm}" --runtime-dir "${RUN}" \
      >/dev/null 2>"${errf}"; then
      SNAPSHOT_MODE=external_disk _snapshot_result_line "${vm}" "1" "" "${linesf_global:-}"
      return 0
    fi
    return 1
  fi
  if virsh snapshot-revert "${vm}" "${nm}" --running --force >/dev/null 2>"${errf}"; then
    SNAPSHOT_MODE=internal _snapshot_result_line "${vm}" "1" "" "${linesf_global:-}"
    return 0
  fi
  if virsh snapshot-revert "${vm}" "${nm}" --force >/dev/null 2>"${errf}"; then
    SNAPSHOT_MODE=internal _snapshot_result_line "${vm}" "1" "" "${linesf_global:-}"
    return 0
  fi
  return 1
}

snapshot_delete_vm() {
  local vm="$1" nm="$2" errf="$3"
  local policy
  policy="$(snapshot_vm_policy "$vm")"
  if [[ "${policy}" == "external_disk" ]]; then
    if python3 "${SNAPSHOT_HELPER}" external-delete \
      --vm "${vm}" --snapshot-name "${nm}" --runtime-dir "${RUN}" \
      >/dev/null 2>"${errf}"; then
      SNAPSHOT_MODE=external_disk _snapshot_result_line "${vm}" "1" "" "${linesf_global:-}"
      return 0
    fi
    return 1
  fi
  if virsh snapshot-delete "${vm}" "${nm}" >/dev/null 2>"${errf}"; then
    SNAPSHOT_MODE=internal _snapshot_result_line "${vm}" "1" "" "${linesf_global:-}"
    return 0
  fi
  return 1
}

snapshot_state_write() {
  local op="${1:-refresh}"
  local sname="${2:-}"
  local started="${3:-}"
  local finished="${4:-}"
  local dryf="${5:-0}"
  local overall="${6:-0}"
  local vmres="${7:-}"
  local scope_vms="${8:-}"
  local vcsv
  local dryarg=()
  if [[ -n "${scope_vms}" ]]; then
    vcsv="$(echo "${scope_vms}" | tr ' ' ',')"
  else
    vcsv="$(_snapshot_vms_csv)"
  fi
  if [[ "$dryf" == "1" || "$(dry_run_active && echo 1 || echo 0)" == "1" ]]; then
    return 0
  fi
  mkdir -p "$(dirname "${XDR_LAB_SNAPSHOTS_JSON}")"
  _snapshot_helper_ok || return 1
  if [[ "$dryf" == "1" ]]; then
    dryarg=(--dry-run)
  fi
  if [[ -n "${vmres}" && -f "${vmres}" ]]; then
    python3 "${SNAPSHOT_HELPER}" write \
      --snapshots-path "${XDR_LAB_SNAPSHOTS_JSON}" \
      --runtime-dir "${RUN}" \
      --vms "${vcsv}" \
      --operation "${op}" \
      --snapshot-name "${sname}" \
      --started-utc "${started}" \
      --finished-utc "${finished}" \
      --overall-rc "${overall}" \
      --vm-results "${vmres}" \
      "${dryarg[@]}" || return 1
  else
    python3 "${SNAPSHOT_HELPER}" write \
      --snapshots-path "${XDR_LAB_SNAPSHOTS_JSON}" \
      --runtime-dir "${RUN}" \
      --vms "${vcsv}" \
      --operation "${op}" \
      --snapshot-name "${sname}" \
      --started-utc "${started}" \
      --finished-utc "${finished}" \
      --overall-rc "${overall}" \
      "${dryarg[@]}" || return 1
  fi
  return 0
}

snapshot_refresh_runtime_vms() {
  local scope="${1:-${XDR_LAB_SNAPSHOT_VM_LIST}}"
  local v
  for v in ${scope}; do
    _invoke_state_refresh "$v" 0 || true
  done
}

_snapshot_report_batch() {
  local op="$1" nm="$2" overall="$3" outjf="$4"
  [[ -f "${outjf}" ]] || return 0
  python3 "${SNAPSHOT_HELPER}" print-batch-summary \
    --operation "${op}" \
    --snapshot-name "${nm}" \
    --overall-rc "${overall}" \
    --vm-results "${outjf}" || true
}

_snapshot_result_line() {
  local vm="$1" ok="$2" msg="$3" linesf="$4"
  MSG="$msg" SNAPSHOT_MODE="${SNAPSHOT_MODE:-}" python3 - "$vm" "$ok" "$linesf" <<'PY'
import json, os, sys
vm, ok, path = sys.argv[1], sys.argv[2], sys.argv[3]
msg = os.environ.get("MSG", "")
mode = os.environ.get("SNAPSHOT_MODE", "").strip()
rec = {"vm": vm, "ok": ok == "1", "message": msg}
if mode:
    rec["snapshot_mode"] = mode
with open(path, "a", encoding="utf-8") as f:
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
PY
}

snapshot_create_vms() {
  local target_vms="${1:?}"
  local want_name="${2:-}"
  local started finished
  started="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  local nm="${want_name}"
  if [[ -z "${nm}" ]]; then
    nm="xdr-lab-$(date -u +"%Y%m%dT%H%M%SZ")"
  fi
  log_structured "INFO" "snapshot_create_begin name=${nm} vms=${target_vms}"
  require_cmd virsh || true
  _snapshot_helper_ok || return 2

  local linesf outjf overall=0 dryf=0
  linesf="$(mktemp)"
  outjf="$(mktemp)"
  linesf_global="${linesf}"
  dry_run_active && dryf=1

  local vm errf reason policy
  for vm in ${target_vms}; do
    if dry_run_active; then
      log_structured "INFO" "snapshot_batch_create_dry_run vm=${vm} name=${nm}"
      SNAPSHOT_MODE="$(snapshot_vm_policy "$vm")" _snapshot_result_line "$vm" "1" "dry_run_skip" "$linesf"
      continue
    fi
    if ! vm_exists "$vm"; then
      log_structured "ERROR" "snapshot_create_failed vm=${vm} name=${nm} reason=domain_missing"
      _snapshot_result_line "$vm" "0" "domain_not_defined" "$linesf"
      overall=1
      continue
    fi
    policy="$(snapshot_vm_policy "$vm")"
    errf="$(mktemp)"
    if snapshot_create_vm "$vm" "$nm" "$errf"; then
      log_structured "INFO" "snapshot_create_ok vm=${vm} name=${nm} mode=${policy}"
      rm -f "${errf}"
      continue
    fi
    reason="$(head -c 2000 "${errf}" 2>/dev/null | tr '\n' ' ' || true)"
    log_structured "ERROR" "snapshot_create_failed vm=${vm} name=${nm} mode=${policy} stderr=${reason:-unknown}"
    _snapshot_result_line "$vm" "0" "${reason}" "$linesf"
    overall=1
    rm -f "${errf}"
  done
  unset linesf_global

  python3 "${SNAPSHOT_HELPER}" merge-lines --input "${linesf}" --output "${outjf}" || {
    rm -f "${linesf}" "${outjf}"
    return 2
  }
  _snapshot_report_batch "create" "${nm}" "${overall}" "${outjf}"
  finished="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  snapshot_state_write "create" "${nm}" "${started}" "${finished}" "${dryf}" "${overall}" "${outjf}" "${target_vms}" || {
    echo "snapshot create: failed to update ${XDR_LAB_SNAPSHOTS_JSON}" >&2
    rm -f "${linesf}" "${outjf}"
    return 1
  }
  rm -f "${linesf}" "${outjf}"
  snapshot_refresh_runtime_vms "${target_vms}"
  log_structured "INFO" "snapshot_create_end name=${nm} overall_rc=${overall}"
  if [[ "${overall}" -ne 0 ]]; then
    echo "snapshot create: failed (see per-VM lines above)" >&2
  fi
  return "${overall}"
}

snapshot_create_all() {
  snapshot_create_vms "${XDR_LAB_SNAPSHOT_VM_LIST}" "${1:-}"
}

snapshot_revert_vms() {
  local target_vms="${1:?}"
  local nm="${2:?}"
  local started finished overall=0 dryf=0
  started="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  log_structured "INFO" "snapshot_revert_begin name=${nm} vms=${target_vms}"
  require_cmd virsh || true
  _snapshot_helper_ok || return 2

  local linesf outjf vm errf reason policy
  linesf="$(mktemp)"
  outjf="$(mktemp)"
  linesf_global="${linesf}"
  dry_run_active && dryf=1

  for vm in ${target_vms}; do
    if dry_run_active; then
      log_structured "INFO" "snapshot_batch_revert_dry_run vm=${vm} name=${nm}"
      SNAPSHOT_MODE="$(snapshot_vm_policy "$vm")" _snapshot_result_line "$vm" "1" "dry_run_skip" "$linesf"
      continue
    fi
    if ! vm_exists "$vm"; then
      log_structured "ERROR" "snapshot_revert_failed vm=${vm} name=${nm} reason=domain_missing"
      _snapshot_result_line "$vm" "0" "domain_not_defined" "$linesf"
      overall=1
      continue
    fi
    policy="$(snapshot_vm_policy "$vm")"
    errf="$(mktemp)"
    if snapshot_revert_vm "$vm" "$nm" "$errf"; then
      log_structured "INFO" "snapshot_revert_ok vm=${vm} name=${nm} policy=${policy}"
      rm -f "${errf}"
      continue
    fi
    reason="$(head -c 2000 "${errf}" 2>/dev/null | tr '\n' ' ' || true)"
    log_structured "ERROR" "snapshot_revert_failed vm=${vm} name=${nm} policy=${policy} stderr=${reason:-unknown}"
    _snapshot_result_line "$vm" "0" "${reason}" "$linesf"
    overall=1
    rm -f "${errf}"
  done
  unset linesf_global

  python3 "${SNAPSHOT_HELPER}" merge-lines --input "${linesf}" --output "${outjf}" || {
    rm -f "${linesf}" "${outjf}"
    return 2
  }
  _snapshot_report_batch "revert" "${nm}" "${overall}" "${outjf}"
  finished="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  snapshot_state_write "revert" "${nm}" "${started}" "${finished}" "${dryf}" "${overall}" "${outjf}" "${target_vms}" || {
    echo "snapshot revert: failed to update ${XDR_LAB_SNAPSHOTS_JSON}" >&2
    rm -f "${linesf}" "${outjf}"
    return 1
  }
  rm -f "${linesf}" "${outjf}"
  snapshot_refresh_runtime_vms "${target_vms}"
  log_structured "INFO" "snapshot_revert_end name=${nm} overall_rc=${overall}"
  if [[ "${overall}" -ne 0 ]]; then
    echo "snapshot revert: failed (see per-VM lines above)" >&2
  fi
  return "${overall}"
}

snapshot_revert_all() {
  snapshot_revert_vms "${XDR_LAB_SNAPSHOT_VM_LIST}" "${1:?}"
}

snapshot_delete_vms() {
  local target_vms="${1:?}"
  local nm="${2:?}"
  local started finished overall=0 dryf=0
  started="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  log_structured "INFO" "snapshot_delete_begin name=${nm} vms=${target_vms}"
  require_cmd virsh || true
  _snapshot_helper_ok || return 2

  local linesf outjf vm errf reason policy
  linesf="$(mktemp)"
  outjf="$(mktemp)"
  linesf_global="${linesf}"
  dry_run_active && dryf=1

  for vm in ${target_vms}; do
    if dry_run_active; then
      log_structured "INFO" "snapshot_batch_delete_dry_run vm=${vm} name=${nm}"
      SNAPSHOT_MODE="$(snapshot_vm_policy "$vm")" _snapshot_result_line "$vm" "1" "dry_run_skip" "$linesf"
      continue
    fi
    if ! vm_exists "$vm"; then
      log_structured "WARN" "snapshot_delete_skip vm=${vm} name=${nm} reason=domain_missing"
      _snapshot_result_line "$vm" "1" "domain_not_defined_skipped" "$linesf"
      continue
    fi
    policy="$(snapshot_vm_policy "$vm")"
    errf="$(mktemp)"
    if snapshot_delete_vm "$vm" "$nm" "$errf"; then
      log_structured "INFO" "snapshot_delete_ok vm=${vm} name=${nm} policy=${policy}"
      rm -f "${errf}"
      continue
    fi
    reason="$(head -c 2000 "${errf}" 2>/dev/null | tr '\n' ' ' || true)"
    log_structured "ERROR" "snapshot_delete_failed vm=${vm} name=${nm} policy=${policy} stderr=${reason:-unknown}"
    _snapshot_result_line "$vm" "0" "${reason}" "$linesf"
    overall=1
    rm -f "${errf}"
  done
  unset linesf_global

  python3 "${SNAPSHOT_HELPER}" merge-lines --input "${linesf}" --output "${outjf}" || {
    rm -f "${linesf}" "${outjf}"
    return 2
  }
  _snapshot_report_batch "delete" "${nm}" "${overall}" "${outjf}"
  finished="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  snapshot_state_write "delete" "${nm}" "${started}" "${finished}" "${dryf}" "${overall}" "${outjf}" "${target_vms}" || {
    echo "snapshot delete: failed to update ${XDR_LAB_SNAPSHOTS_JSON}" >&2
    rm -f "${linesf}" "${outjf}"
    return 1
  }
  rm -f "${linesf}" "${outjf}"
  snapshot_refresh_runtime_vms "${target_vms}"
  log_structured "INFO" "snapshot_delete_end name=${nm} overall_rc=${overall}"
  if [[ "${overall}" -ne 0 ]]; then
    echo "snapshot delete: failed (see per-VM lines above)" >&2
  fi
  return "${overall}"
}

snapshot_delete_all() {
  snapshot_delete_vms "${XDR_LAB_SNAPSHOT_VM_LIST}" "${1:?}"
}

snapshot_list_vms() {
  local target_vms="${1:-${XDR_LAB_SNAPSHOT_VM_LIST}}"
  local started finished dryf=0 vcsv prc=0
  started="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  vcsv="$(echo "${target_vms}" | tr ' ' ',')"
  _snapshot_helper_ok || return 2
  dry_run_active && dryf=1
  log_structured "INFO" "snapshot_list_begin vms=${target_vms} dry_run=${dryf}"
  python3 "${SNAPSHOT_HELPER}" print-table \
    --snapshots-path "${XDR_LAB_SNAPSHOTS_JSON}" \
    --runtime-dir "${RUN}" \
    --vms "${vcsv}" || prc=$?
  finished="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  snapshot_state_write "list" "" "${started}" "${finished}" "${dryf}" 0 "" "${target_vms}" || return 1
  snapshot_refresh_runtime_vms "${target_vms}"
  log_structured "INFO" "snapshot_list_end dry_run=${dryf}"
  return "${prc}"
}

snapshot_list_all() {
  snapshot_list_vms "${XDR_LAB_SNAPSHOT_VM_LIST}"
}

_caldera_helper_ok() {
  if [[ ! -f "${CALDERA_HELPER}" ]]; then
    log_structured "ERROR" "caldera_helper_missing path=${CALDERA_HELPER}"
    return 1
  fi
  return 0
}

_caldera_key_resolver() {
  if [[ "${XDR_LAB_DEV_MODE}" == "1" && -f "${_XDR_VM_MGR_DIR}/caldera_api_key_resolve.py" ]]; then
    echo "${_XDR_VM_MGR_DIR}/caldera_api_key_resolve.py"
  elif [[ -f "${SCRIPTS}/caldera_api_key_resolve.py" ]]; then
    echo "${SCRIPTS}/caldera_api_key_resolve.py"
  else
    return 1
  fi
}

_caldera_read_api_key_safe() {
  local resolver cfg="${XDR_ROOT}/config/caldera-lab.json" key=""
  resolver="$(_caldera_key_resolver)" || return 1
  if [[ -f "${cfg}" ]]; then
    key="$(python3 "${resolver}" --xdr-root "${XDR_ROOT}" --config "${cfg}" 2>/dev/null || true)"
  else
    key="$(python3 "${resolver}" --xdr-root "${XDR_ROOT}" 2>/dev/null || true)"
  fi
  [[ -n "${key}" ]] || return 1
  printf '%s' "${key}"
}

_caldera_export_api_key_env() {
  local kf="${XDR_LAB_CALDERA_API_KEY_FILE}" file_key="" env_key="${XDR_CALDERA_API_KEY:-}"
  file_key="$(_caldera_read_api_key_safe 2>/dev/null || true)"
  if [[ -n "${file_key}" ]]; then
    if [[ -n "${env_key}" && "${env_key}" != "${file_key}" ]]; then
      log_structured "WARN" "stale_XDR_CALDERA_API_KEY ignored runtime_key hint=unset stale env"
    fi
    export XDR_CALDERA_API_KEY="${file_key}"
    return 0
  fi
  if [[ -n "${env_key}" ]]; then
    return 0
  fi
  log_structured "WARN" "caldera_api_key_unset canonical=${kf} runtime=${XDR_ROOT}/runtime/caldera-api-key hint=sudo bootstrap/ensure-caldera-api-key.sh"
  return 1
}

scenario_cli_dispatch() {
  local dryf=0
  if dry_run_active; then
    dryf=1
    export XDR_LAB_DRY_RUN=1
  else
    unset XDR_LAB_DRY_RUN || true
  fi
  _caldera_helper_ok || return 2
  _caldera_export_api_key_env || true
  log_structured "INFO" "scenario_cli_dispatch argv=${*} dry_run=${dryf}"
  python3 "${CALDERA_HELPER}" --xdr-root "${XDR_ROOT}" "$@"
}

runtime_cli_dispatch() {
  local dryf=0
  if dry_run_active; then
    dryf=1
    export XDR_LAB_DRY_RUN=1
  else
    unset XDR_LAB_DRY_RUN || true
  fi
  _caldera_helper_ok || return 2
  _caldera_export_api_key_env || true
  log_structured "INFO" "runtime_cli_dispatch argv=${*} dry_run=${dryf}"
  python3 "${CALDERA_HELPER}" --xdr-root "${XDR_ROOT}" runtime "$@"
}

tool_cli_dispatch() {
  if [[ ! -f "${TOOL_HELPER}" ]]; then
    log_structured "ERROR" "tool_helper_missing path=${TOOL_HELPER}"
    return 2
  fi
  log_structured "INFO" "tool_cli_dispatch argv=${*}"
  python3 "${TOOL_HELPER}" --xdr-root "${XDR_ROOT}" "$@"
}

snapshot_cli_dispatch() {
  local sub="${1:-}"
  local rc=0
  shift || true
  case "${sub}" in
    create)
      case $# in
        0)
          snapshot_create_all || rc=$?
          ;;
        1)
          if _snapshot_is_target_vm "${1}"; then
            echo "snapshot create: missing <snapshot-name> for VM ${1}" >&2
            _snapshot_usage
            return 2
          fi
          snapshot_create_all "${1}" || rc=$?
          ;;
        2)
          if ! _snapshot_is_target_vm "${1}"; then
            echo "snapshot create: unknown VM '${1}' (expected one of: ${XDR_LAB_SNAPSHOT_VM_LIST})" >&2
            _snapshot_usage
            return 2
          fi
          snapshot_create_vms "${1}" "${2}" || rc=$?
          ;;
        *)
          echo "snapshot create: too many arguments" >&2
          _snapshot_usage
          return 2
          ;;
      esac
      return "${rc}"
      ;;
    revert)
      case $# in
        1)
          if _snapshot_is_target_vm "${1}"; then
            echo "snapshot revert: missing <snapshot-name> for VM ${1}" >&2
            _snapshot_usage
            return 2
          fi
          snapshot_revert_all "${1}" || rc=$?
          ;;
        2)
          if ! _snapshot_is_target_vm "${1}"; then
            echo "snapshot revert: unknown VM '${1}'" >&2
            _snapshot_usage
            return 2
          fi
          snapshot_revert_vms "${1}" "${2}" || rc=$?
          ;;
        0)
          echo "snapshot revert: missing <snapshot-name>" >&2
          _snapshot_usage
          return 2
          ;;
        *)
          echo "snapshot revert: too many arguments" >&2
          _snapshot_usage
          return 2
          ;;
      esac
      return "${rc}"
      ;;
    list)
      case $# in
        0)
          snapshot_list_all || rc=$?
          ;;
        1)
          if ! _snapshot_is_target_vm "${1}"; then
            echo "snapshot list: unknown VM '${1}'" >&2
            _snapshot_usage
            return 2
          fi
          snapshot_list_vms "${1}" || rc=$?
          ;;
        *)
          echo "snapshot list: too many arguments" >&2
          _snapshot_usage
          return 2
          ;;
      esac
      return "${rc}"
      ;;
    delete)
      case $# in
        1)
          if _snapshot_is_target_vm "${1}"; then
            echo "snapshot delete: missing <snapshot-name> for VM ${1}" >&2
            _snapshot_usage
            return 2
          fi
          snapshot_delete_all "${1}" || rc=$?
          ;;
        2)
          if ! _snapshot_is_target_vm "${1}"; then
            echo "snapshot delete: unknown VM '${1}'" >&2
            _snapshot_usage
            return 2
          fi
          snapshot_delete_vms "${1}" "${2}" || rc=$?
          ;;
        0)
          echo "snapshot delete: missing <snapshot-name>" >&2
          _snapshot_usage
          return 2
          ;;
        *)
          echo "snapshot delete: too many arguments" >&2
          _snapshot_usage
          return 2
          ;;
      esac
      return "${rc}"
      ;;
    *)
      _snapshot_usage
      return 2
      ;;
  esac
}

usage() {
  cat <<'EOF'
Usage: xdr-lab-vm-manager.sh <download|deploy|start|stop|destroy|status|validate|access|cleanup|snapshot|scenario|runtime|mirror|nat|vnc-proxy|web-console|windows-console|images|sensor|atomic|tools> ...

Image cache (manifest-driven, opt-in: enabled in ${XDR_LAB_IMAGES_MANIFEST} or XDR_LAB_USE_IMAGE_MANIFEST=1):
  xdr-lab-vm-manager.sh download                  # all manifest artifacts
  xdr-lab-vm-manager.sh download --force
  xdr-lab-vm-manager.sh download <vm_role|image_name>
  xdr-lab-vm-manager.sh images status

Stellar Modular Data Sensor:
  xdr-lab-vm-manager.sh sensor download --version 6.2.0
  xdr-lab-vm-manager.sh sensor deploy --version 6.2.0 --cpus 4 --memory-mb 6144 --disk-gb 80
  xdr-lab-vm-manager.sh sensor verify

Examples:
  xdr-lab-vm-manager.sh deploy sensor-vm
  xdr-lab-vm-manager.sh deploy sensor-vm --cpus 4 --memory-mb 6144 --disk-gb 80
  xdr-lab-vm-manager.sh deploy windows-victim
  xdr-lab-vm-manager.sh windows-console windows-victim
  xdr-lab-vm-manager.sh web-console enable windows-victim
  xdr-lab-vm-manager.sh web-console start windows-victim
  xdr-lab-vm-manager.sh web-console status windows-victim
  xdr-lab-vm-manager.sh vnc-proxy start windows-victim
  xdr-lab-vm-manager.sh vnc-proxy verify windows-victim
  xdr-lab-vm-manager.sh start all
  xdr-lab-vm-manager.sh status
  xdr-lab-vm-manager.sh validate all
  xdr-lab-vm-manager.sh snapshot create pre-attack                    # batch all targets
  xdr-lab-vm-manager.sh snapshot create windows-victim test-delete    # single VM
  xdr-lab-vm-manager.sh snapshot list windows-victim
  xdr-lab-vm-manager.sh snapshot revert pre-attack                    # batch revert
  xdr-lab-vm-manager.sh snapshot delete windows-victim test-delete
  xdr-lab-vm-manager.sh scenario list
  xdr-lab-vm-manager.sh scenario bootstrap validate
  xdr-lab-vm-manager.sh scenario bootstrap validate --json
  xdr-lab-vm-manager.sh scenario atomic validate
  xdr-lab-vm-manager.sh scenario atomic validate --json
  xdr-lab-vm-manager.sh scenario pack validate
  xdr-lab-vm-manager.sh scenario pack validate --json
  xdr-lab-vm-manager.sh scenario run recon
  xdr-lab-vm-manager.sh scenario run recon --snapshot-before
  xdr-lab-vm-manager.sh scenario status
  xdr-lab-vm-manager.sh scenario status --human
  xdr-lab-vm-manager.sh scenario telemetry recon
  xdr-lab-vm-manager.sh scenario telemetry last
  xdr-lab-vm-manager.sh scenario telemetry verify
  xdr-lab-vm-manager.sh scenario stop
  xdr-lab-vm-manager.sh scenario agent status
  xdr-lab-vm-manager.sh scenario agent status --json
  xdr-lab-vm-manager.sh scenario agent deploy
  xdr-lab-vm-manager.sh scenario agent deploy --dry-run
  xdr-lab-vm-manager.sh runtime summary
  xdr-lab-vm-manager.sh runtime inspect
  xdr-lab-vm-manager.sh runtime jsonl tail --lines 30
  xdr-lab-vm-manager.sh runtime evidence bundle --out ~/xdr-lab-evidence
  xdr-lab-vm-manager.sh atomic install
  xdr-lab-vm-manager.sh atomic verify
  xdr-lab-vm-manager.sh atomic update
  xdr-lab-vm-manager.sh tools list
  xdr-lab-vm-manager.sh tools verify
  xdr-lab-vm-manager.sh mirror apply               # apply OVS mirror (state-aware)
  xdr-lab-vm-manager.sh mirror verify              # check mirror.json against OVS reality
  xdr-lab-vm-manager.sh mirror validate-traffic    # SSH tcpdump + host probe
  xdr-lab-vm-manager.sh mirror status              # print mirror.json
  xdr-lab-vm-manager.sh nat verify                 # read-only: validate Golden-Image NAT rules
  xdr-lab-vm-manager.sh nat status                 # refresh + print nat.json
  xdr-lab-vm-manager.sh access                     # print reverse-NAT / lab access summary
  xdr-lab-vm-manager.sh cleanup all                # stop + destroy all VMs from lab-vms.json

Notes:
  --nodownload skips re-downloading cached artifacts (Stellar sensor script/qcow2, victim-linux cloud base).
  sensor-vm is Stellar Cyber Modular Data Sensor only; --cpus/--memory-mb/--disk-gb enforce minimums 4/6144/80.
  victim-linux: set XDR_LAB_SKIP_REBOOT_TEST=1 to skip post-deploy reboot validation.
  victim-linux: deploy failures preserve VM, disk, seed.iso, and ${XDR_RUNTIME_DIR}/victim-linux/cloud-init/ (no auto rollback).
  windows-victim: deploy failures preserve VM, disk, and ${XDR_RUNTIME_DIR}/windows-victim/nvram/ (no auto rollback).
  victim-linux: SSH validation tries users in order: ubuntu, lab (override LINUX_SERVER_SSH_USER_CANDIDATES).
  victim-linux: SSH validation uses explicit identity (-i), IdentitiesOnly=yes, BatchMode=yes, ConnectTimeout=5 (override XDR_LAB_VICTIM_LINUX_SSH_IDENTITY, XDR_LAB_SSH_VALIDATION_TIMEOUT, XDR_LAB_SSH_USER_KNOWN_HOSTS_FILE).
  victim-linux: SSH keys auto-discovered (priority): XDR_LAB_VICTIM_LINUX_AUTHORIZED_KEYS, ${XDR_ROOT}/config/victim-linux-authorized_keys, operator ~/.ssh/id_ed25519.pub, id_rsa.pub, first ~/.ssh/*.pub (sudo uses SUDO_USER home)
  Runtime state JSON: one file per VM under XDR_RUNTIME_STATE_DIR (see config/paths.sh).
  Mirror state JSON: ${XDR_RUNTIME_STATE_DIR}/mirror.json (managed by ovs_mirror_state.py).
  NAT state JSON: ${XDR_RUNTIME_STATE_DIR}/nat.json (managed by nat_state.py).
  Snapshot aggregate JSON: ${XDR_RUNTIME_STATE_DIR}/snapshots.json (managed by snapshot_state.py).
  windows-victim (UEFI/pflash): external disk-only snapshots; Linux VMs: internal snapshots.
  CALDERA orchestration: ${XDR_LAB_SCENARIO_STATE_JSON}, ${XDR_LAB_CALDERA_STATE_JSON} (caldera_orchestration.py).
  NAT validator is READ-ONLY: it inspects iptables -S only; it never installs,
  modifies, or removes rules (constitution P-13). The authoritative mapping
  lives inside nat_state.py and assumes the KVM Host Golden Image already
  carries the rules (MASQUERADE for 10.10.10.0/24, DNAT 1022/2022/3389,
  FORWARD ACCEPT 10.10.10.0/24, plus a local websockify on tcp/6080).
  XDR_LAB_VNC_EXTERNAL_PORT / XDR_LAB_VNC_PROXY_DIR / XDR_LAB_VNC_PROXY_BIND (defaults in config/paths.sh)
  XDR_LAB_WEB_CONSOLE_PORT / XDR_LAB_WEB_CONSOLE_DIR / XDR_LAB_WEB_CONSOLE_BIND
  Emergency VNC: QEMU listens on 127.0.0.1 only; host socat forwards XDR_LAB_VNC_EXTERNAL_PORT -> localhost VNC.
  Web console: websockify listens on XDR_LAB_WEB_CONSOLE_BIND:PORT (default 127.0.0.1:6080) with --web noVNC -> 127.0.0.1:QEMU-VNC.
  Optional host packages: see installer/lab-host-web-console-deps.sh (novnc, websockify).
EOF
}

main() {
  local action="${1:-}"

  case "$action" in
    --help|-h|help)
      usage
      exit 0
      ;;
  esac

  if [[ -z "$action" ]]; then
    usage
    exit 2
  fi

  if ! is_known_cli_action "$action"; then
    usage
    echo "ERROR: Unknown action: $action" >&2
    exit 1
  fi

  if needs_runtime_environment "$@"; then
    _XDR_READONLY_CLI=0
    init_runtime_environment
  else
    _XDR_READONLY_CLI=1
  fi

  if [[ "$action" == "download" ]]; then
    shift
    log_structured "INFO" "cli action=download argv=${*}"
    download_main_cli "$@"
    exit $?
  fi
  if [[ "$action" == "images" ]]; then
    shift
    log_structured "INFO" "cli action=images argv=${*}"
    images_cli_dispatch "$@"
    exit $?
  fi
  if [[ "$action" == "sensor" ]]; then
    shift
    log_structured "INFO" "cli action=sensor argv=${*}"
    sensor_cli_dispatch "$@"
    exit $?
  fi

  [[ -f "$CFG" ]] || die "Config missing: $CFG"

  local target="${2:-}"
  local extra="${3:-}"
  local extra_args=( )
  if [[ $# -gt 2 ]]; then
    extra_args=("${@:3}")
  fi

  if [[ "$action" == "access" ]]; then
    log_structured "INFO" "cli action=access"
    show_lab_access
    exit $?
  fi
  if [[ "$action" == "cleanup" ]]; then
    log_structured "WARN" "cli action=cleanup target=${target:-}"
    if [[ "${target:-}" != "all" ]]; then
      echo "ERROR: cleanup requires explicit target: all" >&2
      usage
      exit 2
    fi
    lab_cleanup_all
    exit 0
  fi
  if [[ "$action" == "snapshot" ]]; then
    log_structured "INFO" "cli action=snapshot argv=${*}"
    snapshot_cli_dispatch "${@:2}"
    exit $?
  fi
  if [[ "$action" == "scenario" ]]; then
    log_structured "INFO" "cli action=scenario argv=${*}"
    scenario_cli_dispatch "${@:2}"
    exit $?
  fi
  if [[ "$action" == "runtime" ]]; then
    log_structured "INFO" "cli action=runtime argv=${*}"
    runtime_cli_dispatch "${@:2}"
    exit $?
  fi
  if [[ "$action" == "atomic" ]]; then
    log_structured "INFO" "cli action=atomic argv=${*}"
    tool_cli_dispatch atomic "${@:2}"
    exit $?
  fi
  if [[ "$action" == "tools" ]]; then
    log_structured "INFO" "cli action=tools argv=${*}"
    tool_cli_dispatch tools "${@:2}"
    exit $?
  fi
  # `mirror` is the only action whose target slot is itself a subcommand
  # (apply|verify|validate-traffic|status), so route it before the generic
  # "<action> <vm|all>" target-resolution path.
  if [[ "$action" == "mirror" ]]; then
    log_structured "INFO" "cli action=mirror sub=${target:-} sensor_vm=${extra:-${XDR_LAB_SENSOR_VM}}"
    mirror_dispatch "${target:-}" "${extra:-${XDR_LAB_SENSOR_VM}}"
    exit $?
  fi
  if [[ "$action" == "vm" ]]; then
    local vm_sub="${target:-}"
    local vm_name="${extra:-}"
    if [[ "${vm_sub}" != "repair" || -z "${vm_name}" ]]; then
      echo "Usage: $(basename "$0") vm repair <vm>" >&2
      exit 2
    fi
    log_structured "INFO" "cli action=vm sub=repair vm=${vm_name}"
    repair_windows_vm_runtime "${vm_name}"
    start_vm "${vm_name}"
    exit $?
  fi
  if [[ "$action" == "nat" ]]; then
    log_structured "INFO" "cli action=nat sub=${target:-} state_path=${XDR_LAB_NAT_STATE_JSON}"
    nat_dispatch "${target:-}"
    exit $?
  fi
  if [[ "$action" == "vnc-proxy" ]]; then
    log_structured "INFO" "cli action=vnc-proxy sub=${target:-} vm=${extra:-windows-victim}"
    if ! declare -F vnc_proxy_dispatch >/dev/null 2>&1; then
      die "vnc_proxy_helpers.sh not loaded"
    fi
    vnc_proxy_dispatch "${target:-}" "${extra:-windows-victim}"
    local _vrc=$?
    _invoke_state_refresh "${extra:-windows-victim}" 0
    exit "${_vrc}"
  fi
  if [[ "$action" == "web-console" ]]; then
    local wc_sub="${target:-}"
    local wc_vm="${extra:-windows-victim}"
    log_structured "INFO" "cli action=web-console sub=${wc_sub} vm=${wc_vm}"
    if ! declare -F web_console_dispatch >/dev/null 2>&1; then
      die "vnc_proxy_helpers.sh not loaded (web console helpers missing)"
    fi
    web_console_dispatch "${wc_sub}" "${wc_vm}"
    local _wcrc=$?
    _invoke_state_refresh "${wc_vm}" 0
    exit "${_wcrc}"
  fi
  if [[ "$action" == "windows-console" ]]; then
    local wvm="${target:-windows-victim}"
    log_structured "INFO" "cli action=windows-console vm=${wvm}"
    show_windows_console_info "${wvm}"
    exit $?
  fi
  if [[ -z "$target" ]]; then
    if [[ "$action" == "status" || "$action" == "validate" ]]; then
      target="all"
    else
      usage
      exit 2
    fi
  fi

  local nodownload=0 sensor_cpus="" sensor_memory_mb="" sensor_disk_gb=""
  local i=0
  while [[ "${i}" -lt "${#extra_args[@]}" ]]; do
    case "${extra_args[$i]}" in
      --nodownload)
        nodownload=1
        ;;
      --cpus|--memory-mb|--disk-gb)
        local flag="${extra_args[$i]}"
        i=$((i + 1))
        if [[ "${i}" -ge "${#extra_args[@]}" ]]; then
          die "${flag} requires a value"
        fi
        case "${flag}" in
          --cpus) sensor_cpus="${extra_args[$i]}" ;;
          --memory-mb) sensor_memory_mb="${extra_args[$i]}" ;;
          --disk-gb) sensor_disk_gb="${extra_args[$i]}" ;;
        esac
        ;;
      *)
        die "Unknown option for ${action} ${target}: ${extra_args[$i]}"
        ;;
    esac
    i=$((i + 1))
  done
  if [[ -n "${sensor_cpus}${sensor_memory_mb}${sensor_disk_gb}" ]]; then
    [[ "${action}" == "deploy" && "${target}" == "sensor-vm" ]] || die "--cpus/--memory-mb/--disk-gb are only supported for deploy sensor-vm"
    export XDR_LAB_SENSOR_CPUS_OVERRIDE="${sensor_cpus:-}"
    export XDR_LAB_SENSOR_MEMORY_MB_OVERRIDE="${sensor_memory_mb:-}"
    export XDR_LAB_SENSOR_DISK_GB_OVERRIDE="${sensor_disk_gb:-}"
  fi

  log_structured "INFO" "cli action=${action} target=${target} nodownload=${nodownload} sensor_cpus=${sensor_cpus:-} sensor_memory_mb=${sensor_memory_mb:-} sensor_disk_gb=${sensor_disk_gb:-}"

  case "$action" in
    deploy)
      if [[ "$target" == "all" ]]; then
        for v in $(list_vms); do
          deploy_vm "$v" "$nodownload"
        done
      else
        deploy_vm "$target" "$nodownload"
      fi
      ;;
    start)
      if [[ "$target" == "all" ]]; then
        for v in $(list_vms); do
          if vm_exists "$v"; then
            start_vm "$v"
          else
            log_structured "WARN" "start_skip_missing vm=${v}"
          fi
        done
      else
        start_vm "$target"
      fi
      ;;
    stop)
      if [[ "$target" == "all" ]]; then
        for v in $(list_vms); do
          if vm_exists "$v"; then
            stop_vm "$v"
          fi
        done
      else
        stop_vm "$target"
      fi
      ;;
    destroy)
      if [[ "$target" == "all" ]]; then
        for v in $(list_vms); do
          if vm_exists "$v"; then
            destroy_vm "$v"
          fi
        done
      else
        destroy_vm "$target"
      fi
      ;;
    status)
      show_vm_status "$target"
      ;;
    validate)
      validate_all_vms "$target"
      ;;
    *)
      usage
      echo "ERROR: Unknown action: $action" >&2
      exit 1
      ;;
  esac
}

main "$@"
