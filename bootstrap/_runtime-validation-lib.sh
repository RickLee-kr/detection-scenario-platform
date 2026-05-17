#!/usr/bin/env bash
# Shared helpers for KVM host runtime validation / safe self-healing.
# Sourced by bootstrap/validate-*.sh and fix-runtime-state.sh — not executed directly.
# shellcheck shell=bash

if [[ -n "${_XDR_RUNTIME_VALIDATION_LIB_LOADED:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
readonly _XDR_RUNTIME_VALIDATION_LIB_LOADED=1

_XDR_BOOTSTRAP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${XDR_BASE:=/opt/xdr-lab}"
: "${XDR_ROOT:=${XDR_BASE}}"
: "${XDR_LAB_DEV_MODE:=0}"
if [[ "${XDR_LAB_DEV_MODE}" == "1" && -f "${_XDR_BOOTSTRAP_DIR}/../config/paths.sh" ]]; then
  # shellcheck source=../config/paths.sh
  . "${_XDR_BOOTSTRAP_DIR}/../config/paths.sh"
elif [[ -n "${XDR_ROOT:-}" && -f "${XDR_ROOT}/config/paths.sh" ]]; then
  # shellcheck source=/dev/null
  . "${XDR_ROOT}/config/paths.sh"
fi

: "${LAB_OVS_NETWORK:=ovs-net}"
: "${LAB_BRIDGE:=br0}"
: "${LAB_GATEWAY:=10.10.10.1}"
: "${LAB_SUBNET_CIDR:=10.10.10.0/24}"
: "${XDR_LOGS_DIR:=${XDR_ROOT}/logs}"
: "${XDR_LAB_NAT_STATE_JSON:=${XDR_ROOT}/runtime/state/nat.json}"
: "${XDR_LAB_CALDERA_CONFIG:=${XDR_ROOT}/config/caldera-lab.json}"
: "${XDR_LAB_PROBE_TIMEOUT_SECS:=15}"
: "${XDR_LAB_VIRSH_TIMEOUT_SECS:=15}"
: "${XDR_LAB_NAT_VERIFY_TIMEOUT_SECS:=30}"
: "${XDR_LAB_SYSTEMCTL_TIMEOUT_SECS:=10}"
: "${XDR_LAB_OVS_VSCTL_TIMEOUT_SECS:=15}"
: "${XDR_LAB_CALDERA_HOME:=/opt/caldera}"
: "${XDR_LAB_CALDERA_USER:=}"
: "${XDR_LAB_VENV_TIMEOUT_SECS:=120}"
: "${XDR_LAB_PIP_TIMEOUT_SECS:=600}"
: "${XDR_LAB_HTTP_PROBE_TIMEOUT_SECS:=8}"
: "${XDR_LAB_CALDERA_READY_TIMEOUT_SECS:=300}"
: "${XDR_LAB_CALDERA_READY_POLL_SECS:=5}"
: "${XDR_LAB_CALDERA_READY_PROGRESS_SECS:=5}"
: "${XDR_LAB_CALDERA_STALE_GRACE_SECS:=90}"
: "${XDR_LAB_CALDERA_STALE_MIN_ORPHAN_AGE_SECS:=300}"
# Exit code when a validator skipped root-only probes (not a runtime failure).
readonly RV_EXIT_PRIVILEGE_SKIP=77
# Exit code when CALDERA is still starting/building (use --wait to block).
readonly RV_EXIT_CALDERA_NOT_READY=25

if ! mkdir -p "${XDR_LOGS_DIR}" 2>/dev/null; then
  XDR_LOGS_DIR="${_XDR_BOOTSTRAP_DIR}/../logs"
  mkdir -p "${XDR_LOGS_DIR}" 2>/dev/null || XDR_LOGS_DIR="/tmp"
fi

readonly XDR_ROOT XDR_BASE XDR_LOGS_DIR LAB_BRIDGE LAB_OVS_NETWORK LAB_GATEWAY LAB_SUBNET_CIDR
readonly RV_LOG_FILE="${XDR_LOGS_DIR}/host-runtime-validation.log"

rv_ensure_log_target() {
  local log_dir log_file
  log_dir="$(dirname "${RV_LOG_FILE}")"
  log_file="${RV_LOG_FILE}"
  if [[ "$(id -u)" -eq 0 ]]; then
    install -d -m 0755 "${log_dir}"
    if [[ ! -e "${log_file}" ]]; then
      install -m 0664 /dev/null "${log_file}"
    else
      chmod 0664 "${log_file}" 2>/dev/null || true
    fi
    return 0
  fi
  if [[ -w "${log_dir}" ]]; then
    touch "${log_file}" 2>/dev/null || true
  fi
}

rv_ensure_log_target

rv_log() {
  local level="$1"
  shift
  local ts msg line
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  msg="$*"
  line="[${ts}] [${level}] ${msg}"
  echo "${line}" >&2
  if [[ -w "$(dirname "${RV_LOG_FILE}")" ]]; then
    echo "${line}" >>"${RV_LOG_FILE}" 2>/dev/null || true
  fi
}

rv_check_pass() {
  local id="$1" detail="${2:-ok}"
  printf 'PASS\t%s\t%s\n' "${id}" "${detail}"
}

rv_check_fail() {
  local id="$1" detail="$2"
  printf 'FAIL\t%s\t%s\n' "${id}" "${detail}"
}

rv_check_skip() {
  local id="$1" detail="$2"
  printf 'SKIP\t%s\t%s\n' "${id}" "${detail}"
}

rv_is_root() {
  [[ "$(id -u)" -eq 0 ]]
}

# True when passwordless sudo works (non-interactive validators / CI).
rv_sudo_noninteractive_available() {
  command -v sudo &>/dev/null && sudo -n true 2>/dev/null
}

# Alias used by privilege-aware validators and validate-appliance.
rv_can_sudo_noninteractive() {
  rv_sudo_noninteractive_available
}

# True when sudo exists and may prompt (interactive shell).
rv_sudo_available() {
  command -v sudo &>/dev/null
}

# Classify stderr/stdout from a probe as a privilege failure vs runtime failure.
rv_text_is_permission_denied() {
  local text="${1:-}"
  [[ -n "${text}" ]] || return 1
  grep -qiE \
    'permission denied|operation not permitted|access denied|must be root|are you root|insufficient privileges|authentication unavailable|auth cancel|connect to permission denied|failed to connect to .*socket|cannot connect to hypervisor|/var/run/libvirt/libvirt-sock|iptables.*permission|xtables_lock|couldn.?t connect to .*ovsdb|ovs-vsctl: .*permission|db\.sock' \
    <<<"${text}"
}

rv_text_is_ovs_permission_denied() {
  local text="${1:-}"
  [[ -n "${text}" ]] || return 1
  grep -qiE 'ovs-vsctl|ovsdb|db\.sock' <<<"${text}" \
    && grep -qiE 'permission denied|operation not permitted|access denied|must be root|are you root|insufficient privileges' <<<"${text}"
}

rv_text_is_iptables_permission_denied() {
  local text="${1:-}"
  [[ -n "${text}" ]] || return 1
  grep -qiE 'iptables|xtables|nft|permission denied|operation not permitted|must be root|are you root|insufficient privileges' <<<"${text}"
}

rv_text_is_virsh_permission_denied() {
  local text="${1:-}"
  [[ -n "${text}" ]] || return 1
  grep -qiE 'virsh|libvirt|hypervisor|libvirt-sock' <<<"${text}" \
    && grep -qiE 'permission denied|operation not permitted|access denied|authentication unavailable|auth cancel|failed to connect' <<<"${text}"
}

# Re-exec the current validator with root when possible.
rv_reexec_as_root_if_needed() {
  if rv_is_root; then
    return 1
  fi
  if rv_sudo_noninteractive_available; then
    rv_log INFO "re-exec validator as root (sudo -n)"
    exec sudo -n -E bash "$0" "$@"
  fi
  if rv_sudo_available && [[ -t 0 ]]; then
    rv_log INFO "re-exec validator as root (sudo, interactive)"
    exec sudo -E bash "$0" "$@"
  fi
  export XDR_LAB_VALIDATOR_NON_ROOT=1
  rv_log WARN "validator running without root — root-only probes will SKIP"
  return 1
}

# Read REQUIRE_ROOT=0|1 from a validator script header (default 0).
rv_validator_require_root() {
  local script="$1" val
  [[ -f "${script}" ]] || return 1
  val="$(grep -E '^[[:space:]]*REQUIRE_ROOT=' "${script}" 2>/dev/null | tail -n1 | cut -d= -f2-)"
  val="${val//[[:space:]]/}"
  val="${val//\"/}"
  val="${val//\'/}"
  [[ "${val}" == "1" ]]
}

# Returns 0 when the current process has root; 1 when caller should SKIP.
rv_require_root_or_skip() {
  local _id="${1:-}" _reason="${2:-requires root privileges}"
  if rv_is_root; then
    return 0
  fi
  return 1
}

# Execute a validator with privilege-aware wrapping.
# Root-required validators run as root, via non-interactive sudo when available,
# or return RV_EXIT_PRIVILEGE_SKIP when elevation is unavailable.
rv_exec_validator() {
  local script_path="$1"
  shift
  if rv_validator_require_root "${script_path}"; then
    if rv_is_root; then
      bash "${script_path}" "$@"
      return $?
    fi
    if rv_can_sudo_noninteractive; then
      rv_log INFO "elevating validator via sudo -n: ${script_path}"
      sudo -n -E bash "${script_path}" "$@"
      return $?
    fi
    rv_log WARN "validator requires root but sudo -n unavailable: ${script_path}"
    return "${RV_EXIT_PRIVILEGE_SKIP}"
  fi
  bash "${script_path}" "$@"
}

# Run a command with a wall-clock cap. Exit 124 on timeout (GNU coreutils).
rv_run_with_timeout() {
  local secs="$1" label="$2" rc
  shift 2
  if command -v timeout &>/dev/null; then
    timeout --foreground "${secs}" "$@"
    rc=$?
    if [[ "${rc}" -eq 124 ]]; then
      rv_log ERROR "timeout (${secs}s): ${label}"
    fi
    return "${rc}"
  fi
  rv_log WARN "timeout unavailable — running unbounded: ${label}"
  "$@"
}

rv_step_begin() {
  rv_log INFO "step begin: $*"
}

rv_step_end() {
  local step="$1" rc="$2"
  if [[ "${rc}" -eq 0 ]]; then
    rv_log INFO "step end: ${step} ok"
  else
    rv_log ERROR "step end: ${step} failed rc=${rc}"
  fi
}

rv_probe_begin() {
  rv_log INFO "probe begin: $*"
}

rv_probe_end() {
  local probe="$1" ok="$2"
  if [[ "${ok}" == "1" ]]; then
    rv_log INFO "probe end: ${probe} PASS"
  else
    rv_log INFO "probe end: ${probe} FAIL"
  fi
}

rv_iface_exists() {
  ip link show "${LAB_BRIDGE}" &>/dev/null
}

rv_iface_oper_up() {
  local state flags
  state="$(ip -br link show "${LAB_BRIDGE}" 2>/dev/null | awk 'NR==1 {print $2}')"
  flags="$(ip link show "${LAB_BRIDGE}" 2>/dev/null | head -n1)"
  # OVS bridges often report operstate UNKNOWN while IFF_UP is set — treat as healthy.
  [[ "${state}" == "UP" || "${state}" == "UNKNOWN" ]] \
    && grep -q '<[^>]*UP' <<<"${flags}"
}

rv_iface_has_gateway_ip() {
  ip -4 addr show dev "${LAB_BRIDGE}" 2>/dev/null \
    | grep -Fq "inet ${LAB_GATEWAY}/"
}

rv_virsh_net_info() {
  rv_run_with_timeout "${XDR_LAB_VIRSH_TIMEOUT_SECS}" \
    "virsh net-info ${LAB_OVS_NETWORK}" \
    virsh net-info "${LAB_OVS_NETWORK}" 2>/dev/null
}

rv_virsh_net_active() {
  local active
  active="$(rv_virsh_net_info | awk -F: '/^Active:/ {gsub(/ /,"",$2); print $2}')"
  [[ "${active}" == "yes" ]]
}

rv_virsh_net_defined() {
  rv_virsh_net_info >/dev/null
}

rv_ip_forward_enabled() {
  local v
  v="$(sysctl -n net.ipv4.ip_forward 2>/dev/null || echo 0)"
  [[ "${v}" == "1" ]]
}

rv_nat_helper() {
  local helper="${XDR_ROOT}/scripts/nat_state.py"
  [[ -f "${helper}" ]] || helper="${_XDR_BOOTSTRAP_DIR}/../scripts/nat_state.py"
  [[ -f "${helper}" ]] && echo "${helper}"
}

rv_nat_state_path() {
  echo "${XDR_LAB_NAT_STATE_JSON}"
}

# Lab egress NIC for POSTROUTING MASQUERADE (-o). Never hard-code eth0.
rv_uplink_iface() {
  if [[ -n "${LAB_UPLINK_IFACE:-}" ]]; then
    echo "${LAB_UPLINK_IFACE}"
    return 0
  fi
  local vms_json="${XDR_LAB_VMS_JSON:-}"
  if [[ -f "${vms_json}" ]] && command -v jq &>/dev/null; then
    local from_cfg
    from_cfg="$(jq -r '.network.uplink_interface // empty' "${vms_json}" 2>/dev/null || true)"
    if [[ -n "${from_cfg}" && "${from_cfg}" != "null" ]]; then
      echo "${from_cfg}"
      return 0
    fi
  fi
  local dev
  dev="$(ip -4 route show default 2>/dev/null | awk '{
    for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit }
  }')"
  if [[ -n "${dev}" && "${dev}" != "${LAB_BRIDGE}" ]]; then
    echo "${dev}"
    return 0
  fi
  dev="$(ip -4 route get 203.0.113.1 2>/dev/null | awk '{
    for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit }
  }')"
  if [[ -n "${dev}" && "${dev}" != "${LAB_BRIDGE}" ]]; then
    echo "${dev}"
    return 0
  fi
  return 1
}

rv_nat_verify_json() {
  local helper state_path
  helper="$(rv_nat_helper)" || return 1
  state_path="$(rv_nat_state_path)"
  rv_run_with_timeout "${XDR_LAB_NAT_VERIFY_TIMEOUT_SECS}" \
    "nat_state.py verify --iptables-only" \
    python3 "${helper}" verify --state-path "${state_path}" --iptables-only --print-json 2>/dev/null
}

rv_masquerade_present() {
  local line
  line="$(rv_nat_verify_json 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print("yes" if d.get("masquerade",{}).get("present") else "no")' 2>/dev/null || echo no)"
  [[ "${line}" == "yes" ]]
}

rv_reverse_nat_present() {
  local helper rc state_path
  helper="$(rv_nat_helper)" || return 1
  state_path="$(rv_nat_state_path)"
  rv_run_with_timeout "${XDR_LAB_NAT_VERIFY_TIMEOUT_SECS}" \
    "nat_state.py verify --iptables-only" \
    python3 "${helper}" verify --state-path "${state_path}" --iptables-only &>/dev/null
  rc=$?
  [[ "${rc}" -eq 0 ]]
}

rv_script_path() {
  local name="$1"
  local candidate
  local -a candidates=()
  if [[ -n "${XDR_LAB_BOOTSTRAP_DIR:-}" ]]; then
    candidates+=("${XDR_LAB_BOOTSTRAP_DIR}/${name}")
    if [[ -n "${XDR_ROOT:-}" ]]; then
      candidates+=("${XDR_ROOT}/bootstrap/${name}")
    fi
  else
    candidates+=(
      "${XDR_LAB_BOOTSTRAP_DIR:-}/${name}"
      "${_XDR_BOOTSTRAP_DIR}/${name}"
      "${XDR_ROOT}/bootstrap/${name}"
    )
  fi
  for candidate in "${candidates[@]}"; do
    [[ -n "${candidate}" && "${candidate}" != "/${name}" ]] || continue
    if [[ -f "${candidate}" ]]; then
      echo "${candidate}"
      return 0
    fi
  done
  return 1
}

rv_caldera_base_url() {
  local cfg="${XDR_LAB_CALDERA_CONFIG}"
  if [[ ! -f "${cfg}" ]]; then
    cfg="${_XDR_BOOTSTRAP_DIR}/../config/caldera-lab.json"
  fi
  if [[ -f "${cfg}" ]] && command -v jq &>/dev/null; then
    jq -r '.caldera.base_url // .base_url // "http://127.0.0.1:8888"' "${cfg}"
    return 0
  fi
  echo "http://127.0.0.1:8888"
}

rv_caldera_agent_base_url() {
  local cfg="${XDR_LAB_CALDERA_CONFIG}"
  if [[ ! -f "${cfg}" ]]; then
    cfg="${_XDR_BOOTSTRAP_DIR}/../config/caldera-lab.json"
  fi
  if [[ -f "${cfg}" ]] && command -v jq &>/dev/null; then
    jq -r '.caldera.agent_base_url // .agent_base_url // "http://10.10.10.1:8888"' "${cfg}"
    return 0
  fi
  echo "http://10.10.10.1:8888"
}

rv_caldera_bind_host() {
  local cfg="${XDR_LAB_CALDERA_CONFIG}"
  if [[ ! -f "${cfg}" ]]; then
    cfg="${_XDR_BOOTSTRAP_DIR}/../config/caldera-lab.json"
  fi
  if [[ -f "${cfg}" ]] && command -v jq &>/dev/null; then
    jq -r '.caldera.bind_host // .bind_host // "0.0.0.0"' "${cfg}"
    return 0
  fi
  echo "0.0.0.0"
}

rv_caldera_port() {
  local cfg url port
  cfg="${XDR_LAB_CALDERA_CONFIG}"
  if [[ ! -f "${cfg}" ]]; then
    cfg="${_XDR_BOOTSTRAP_DIR}/../config/caldera-lab.json"
  fi
  if [[ -f "${cfg}" ]] && command -v jq &>/dev/null; then
    port="$(jq -r '.caldera.listen_port // .listen_port // empty' "${cfg}" 2>/dev/null || true)"
    if [[ "${port}" =~ ^[0-9]+$ ]]; then
      echo "${port}"
      return 0
    fi
  fi
  url="$(rv_caldera_base_url)"
  if [[ "${url}" =~ :([0-9]+)(/|$) ]]; then
    port="${BASH_REMATCH[1]}"
  else
    port="8888"
  fi
  echo "${port}"
}

rv_current_boot_id() {
  if [[ -r /proc/sys/kernel/random/boot_id ]]; then
    tr -d '[:space:]' </proc/sys/kernel/random/boot_id
    return 0
  fi
  return 1
}

rv_systemd_unit_enabled() {
  local unit="$1"
  rv_run_with_timeout "${XDR_LAB_SYSTEMCTL_TIMEOUT_SECS}" \
    "systemctl is-enabled ${unit}" \
    systemctl is-enabled "${unit}" &>/dev/null
}

rv_systemd_unit_active() {
  local unit="$1"
  rv_run_with_timeout "${XDR_LAB_SYSTEMCTL_TIMEOUT_SECS}" \
    "systemctl is-active ${unit}" \
    systemctl is-active "${unit}" &>/dev/null
}

rv_ovs_vsctl_show() {
  rv_run_with_timeout "${XDR_LAB_OVS_VSCTL_TIMEOUT_SECS}" \
    "ovs-vsctl show" \
    ovs-vsctl show 2>&1
}

rv_host_network_boot_state() {
  echo "${XDR_RUNTIME_STATE_DIR}/host-network-boot.json"
}

rv_host_network_boot_ok() {
  local state_path boot_id recorded
  state_path="$(rv_host_network_boot_state)"
  [[ -f "${state_path}" ]] || return 1
  boot_id="$(rv_current_boot_id)" || return 1
  recorded="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("boot_id",""))' "${state_path}" 2>/dev/null || echo "")"
  [[ -n "${recorded}" && "${recorded}" == "${boot_id}" ]]
}

rv_user_exists() {
  local user="$1"
  [[ -n "${user}" ]] && id -u "${user}" &>/dev/null
}

rv_caldera_home() {
  echo "${CALDERA_HOME:-${XDR_LAB_CALDERA_HOME}}"
}

rv_caldera_service_unit_path() {
  echo "${XDR_LAB_CALDERA_SERVICE_UNIT:-/etc/systemd/system/caldera.service}"
}

rv_caldera_service_user_from_unit() {
  local path user
  path="$(rv_caldera_service_unit_path)"
  if [[ -f "${path}" ]]; then
    user="$(awk -F= '/^User=/ {gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2; exit}' "${path}" 2>/dev/null || true)"
    echo "${user}"
  fi
}

rv_caldera_execstart_from_unit() {
  local path line
  path="$(rv_caldera_service_unit_path)"
  if [[ -f "${path}" ]]; then
    line="$(awk -F= '/^ExecStart=/ {sub(/^ExecStart=/, ""); print; exit}' "${path}" 2>/dev/null || true)"
    echo "${line}"
  fi
}

rv_caldera_execstart_python() {
  local execstart
  execstart="$(rv_caldera_execstart_from_unit)"
  [[ -n "${execstart}" ]] || return 1
  awk '{print $1}' <<<"${execstart}"
}

# Safe URL path append (avoid bash ${url}/path treating / as pattern substitution).
rv_url_join_path() {
  local base="$1" suffix="$2"
  printf '%s/%s' "${base%/}" "${suffix#/}"
}

# CALDERA main config path from WorkingDirectory + ExecStart (-E / --insecure).
# With --insecure, server.py forces conf/default.yml (not local.yml).
rv_caldera_main_config_path() {
  local home execstart env_name
  home="$(rv_caldera_home)"
  execstart="$(rv_caldera_execstart_from_unit 2>/dev/null || true)"
  env_name="default"
  if [[ -n "${execstart}" ]]; then
    if grep -qE '(^|[[:space:]])--insecure([[:space:]]|$)' <<<"${execstart}"; then
      env_name="default"
    elif [[ "${execstart}" =~ (^|[[:space:]])-E[[:space:]]+([A-Za-z0-9_-]+) ]]; then
      env_name="${BASH_REMATCH[2]}"
    elif [[ "${execstart}" =~ (^|[[:space:]])--environment(=|[[:space:]]+)([A-Za-z0-9_-]+) ]]; then
      env_name="${BASH_REMATCH[3]}"
    else
      env_name="local"
    fi
  fi
  echo "${home}/conf/${env_name}.yml"
}

rv_caldera_config_diag_json() {
  local py home unit diag_py
  home="$(rv_caldera_home)"
  unit="$(rv_caldera_service_unit_path)"
  diag_py="${_XDR_BOOTSTRAP_DIR}/../scripts/caldera_config_diag.py"
  if [[ ! -f "${diag_py}" ]]; then
    diag_py="${XDR_ROOT:-}/scripts/caldera_config_diag.py"
  fi
  py="$(command -v python3 || true)"
  if [[ -x "${home}/.venv/bin/python3" ]]; then
    py="${home}/.venv/bin/python3"
  fi
  if [[ ! -f "${diag_py}" || -z "${py}" ]]; then
    echo '{}'
    return 1
  fi
  local diag_args=(--caldera-home "${home}" --unit-path "${unit}" --key-file "${API_KEY_FILE:-/etc/xdr-lab/caldera-api-key}")
  if [[ -n "${CALDERA_MAIN_CONFIG:-}" ]]; then
    diag_args+=(--config "${CALDERA_MAIN_CONFIG}")
  fi
  "${py}" "${diag_py}" "${diag_args[@]}" 2>/dev/null || echo '{}'
}

rv_caldera_log_config_diag() {
  local json
  json="$(rv_caldera_config_diag_json)"
  [[ -n "${json}" && "${json}" != '{}' ]] || return 0
  python3 -c 'import json,sys; d=json.load(sys.stdin); kv=d.get("key_verify") or {}; print(
    "caldera_config_diag main_config_path=%s environment=%s key_readable=%s key_matches_api_key_red=%s local_yml=%s" % (
      d.get("main_config_path","?"),
      d.get("environment","?"),
      kv.get("readable"),
      kv.get("matches_api_key_red"),
      next((o.get("exists") for o in (d.get("override_candidates") or []) if o.get("name")=="local.yml"), False),
    ))' <<<"${json}" 2>/dev/null | while read -r line; do rv_log INFO "${line}"; done
}

rv_caldera_server_pid() {
  pgrep -f "${CALDERA_HOME:-/opt/caldera}/.*server\\.py" 2>/dev/null | head -1 || true
}

# All CALDERA server.py PIDs (systemd + manual nohup).
rv_caldera_server_pids() {
  pgrep -f "${CALDERA_HOME:-/opt/caldera}/.*server\\.py" 2>/dev/null || true
}

rv_caldera_systemd_main_pid() {
  systemctl show caldera.service -p MainPID --value 2>/dev/null | tr -d ' ' || true
}

# PIDs listening on CALDERA HTTP port (from conf/default.yml port field).
rv_caldera_listener_pid() {
  local port="${1:-8888}"
  ss -lntp 2>/dev/null | awk -v p=":${port}" '
    $0 ~ p && match($0, /pid=([0-9]+)/, m) { print m[1]; exit }
  ' || true
}

rv_caldera_process_util_py() {
  local root="${XDR_ROOT:-${_XDR_BOOTSTRAP_DIR}/..}"
  local p="${root}/scripts/caldera_process_util.py"
  [[ -f "${p}" ]] && echo "${p}" && return 0
  p="${_XDR_BOOTSTRAP_DIR}/../scripts/caldera_process_util.py"
  [[ -f "${p}" ]] && echo "${p}" && return 0
  return 1
}

rv_caldera_process_util_python() {
  local home venv_py
  home="$(rv_caldera_home)"
  venv_py="${home}/.venv/bin/python3"
  if [[ -x "${venv_py}" ]]; then
    echo "${venv_py}"
    return 0
  fi
  command -v python3
}

rv_caldera_journal_all_systems_ready() {
  local journal="${1:-}"
  [[ -n "${journal}" ]] || journal="$(rv_caldera_journal_recent 150)"
  grep -qF 'All systems ready' <<<"${journal}"
}

rv_caldera_startup_in_progress() {
  local util py port rc state journal
  util="$(rv_caldera_process_util_py)" || return 1
  py="$(rv_caldera_process_util_python)" || return 1
  port="$(rv_caldera_port)"
  if "${py}" "${util}" startup-in-progress --caldera-home "$(rv_caldera_home)" --port "${port}" 2>/dev/null; then
    return 0
  fi
  state="$(rv_caldera_classify_startup_state)"
  [[ "${state}" == "BUILDING" || "${state}" == "STARTING" ]] && return 0
  if rv_systemd_unit_active caldera.service; then
    journal="$(rv_caldera_journal_recent 120)"
    rv_caldera_journal_all_systems_ready "${journal}" && return 1
    rv_caldera_journal_suggests_building "${journal}" && return 0
    return 0
  fi
  return 1
}

rv_caldera_stale_grace_active() {
  local util py
  util="$(rv_caldera_process_util_py)" || return 1
  py="$(rv_caldera_process_util_python)" || return 1
  "${py}" "${util}" grace-active \
    --grace-secs "${XDR_LAB_CALDERA_STALE_GRACE_SECS}" 2>/dev/null
}

rv_caldera_record_restart_grace() {
  local util py until
  util="$(rv_caldera_process_util_py)" || return 1
  py="$(rv_caldera_process_util_python)" || return 1
  until="$("${py}" "${util}" record-grace \
    --grace-secs "${XDR_LAB_CALDERA_STALE_GRACE_SECS}" 2>/dev/null || true)"
  [[ -n "${until}" ]] && rv_log INFO "CALDERA stale-kill grace until epoch=${until} (${XDR_LAB_CALDERA_STALE_GRACE_SECS}s)"
}

# Orphan / foreign-cgroup / old server.py only (never MainPID children or same cgroup).
rv_caldera_stale_server_pids() {
  local util py port
  util="$(rv_caldera_process_util_py)" || return 0
  py="$(rv_caldera_process_util_python)" || return 0
  port="$(rv_caldera_port)"
  "${py}" "${util}" stale-pids \
    --caldera-home "$(rv_caldera_home)" \
    --port "${port}" \
    --grace-secs "${XDR_LAB_CALDERA_STALE_GRACE_SECS}" \
    --min-orphan-age-secs "${XDR_LAB_CALDERA_STALE_MIN_ORPHAN_AGE_SECS}" 2>/dev/null || true
}

rv_caldera_kill_stale_servers() {
  local pid stale=() killed=0
  if rv_caldera_stale_grace_active; then
    rv_log INFO "stale CALDERA cleanup skipped (restart grace ${XDR_LAB_CALDERA_STALE_GRACE_SECS}s)"
    return 0
  fi
  if rv_caldera_startup_in_progress; then
    rv_log INFO "stale CALDERA cleanup skipped (startup/build in progress)"
    return 0
  fi
  while IFS= read -r pid; do
    [[ -n "${pid}" ]] && stale+=("${pid}")
  done < <(rv_caldera_stale_server_pids)
  if [[ "${#stale[@]}" -eq 0 ]]; then
    return 0
  fi
  rv_log WARN "killing stale CALDERA server.py PIDs (orphan/foreign cgroup/old): ${stale[*]}"
  for pid in "${stale[@]}"; do
    if kill "${pid}" 2>/dev/null; then
      killed=$(( killed + 1 ))
    fi
  done
  sleep 2
  for pid in "${stale[@]}"; do
    kill -0 "${pid}" 2>/dev/null && kill -9 "${pid}" 2>/dev/null || true
  done
  [[ "${killed}" -gt 0 ]]
}

rv_caldera_assert_listener_is_systemd() {
  local port="${1:-8888}" main_pid listener util py util_dir
  main_pid="$(rv_caldera_systemd_main_pid)"
  listener="$(rv_caldera_listener_pid "${port}")"
  if [[ -z "${listener}" ]]; then
    if rv_caldera_startup_in_progress || rv_caldera_stale_grace_active; then
      rv_log INFO "no listener on port ${port} yet (startup/grace — expected)"
      return 0
    fi
    rv_log WARN "no process listening on port ${port}"
    return 1
  fi
  if [[ -n "${main_pid}" && "${listener}" == "${main_pid}" ]]; then
    rv_log INFO "CALDERA listener pid=${listener} matches systemd MainPID"
    return 0
  fi
  if [[ -n "${main_pid}" ]]; then
    util="$(rv_caldera_process_util_py)" || true
    py="$(rv_caldera_process_util_python)" || true
    if [[ -n "${util}" && -n "${py}" ]]; then
      util_dir="$(dirname "${util}")"
      if "${py}" -c 'import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from caldera_process_util import is_descendant_of, same_systemd_cgroup; c,a=int(sys.argv[2]),int(sys.argv[3]); raise SystemExit(0 if is_descendant_of(c,a) or same_systemd_cgroup(c,a) else 1)' \
          "${util_dir}" "${listener}" "${main_pid}" 2>/dev/null; then
        rv_log INFO "CALDERA listener pid=${listener} in systemd scope of MainPID=${main_pid}"
        return 0
      fi
    fi
    local ppid walk="${listener}"
    while [[ -n "${walk}" && "${walk}" != "1" ]]; do
      if [[ "${walk}" == "${main_pid}" ]]; then
        rv_log INFO "CALDERA listener pid=${listener} is child of MainPID=${main_pid}"
        return 0
      fi
      ppid="$(awk '{print $4}' "/proc/${walk}/stat" 2>/dev/null || true)"
      [[ "${ppid}" == "${walk}" ]] && break
      walk="${ppid}"
    done
  fi
  if rv_caldera_startup_in_progress || rv_caldera_stale_grace_active; then
    rv_log INFO "listener pid=${listener} != MainPID=${main_pid:-none} during startup/grace (allowed)"
    return 0
  fi
  rv_log ERROR "port ${port} listener pid=${listener} != systemd MainPID=${main_pid:-none} (stale server?)"
  return 1
}

# Restart caldera.service and confirm Main PID changed (reloads api_key_red from disk).
rv_caldera_restart_service() {
  local reason="${1:-reload config}"
  local old_pid new_pid
  if ! rv_caldera_stale_grace_active && ! rv_caldera_startup_in_progress; then
    rv_caldera_kill_stale_servers || true
  fi
  rv_caldera_record_restart_grace || true
  old_pid="$(rv_caldera_server_pid)"
  if ! rv_run_with_timeout "${XDR_LAB_SYSTEMCTL_TIMEOUT_SECS}" \
      "systemctl restart caldera.service" \
      systemctl restart caldera.service 2>/dev/null; then
    rv_log ERROR "systemctl restart caldera.service failed (sudo required) — CALDERA keeps in-memory api_key_red until restart; reason=${reason}"
    return 1
  fi
  local waited=0
  while (( waited < 30 )); do
    new_pid="$(rv_caldera_server_pid)"
    if [[ -n "${new_pid}" && "${new_pid}" != "${old_pid}" ]] \
        && rv_systemd_unit_active caldera.service; then
      if ! rv_caldera_stale_grace_active && ! rv_caldera_startup_in_progress; then
        rv_caldera_kill_stale_servers || true
      fi
      if rv_caldera_assert_listener_is_systemd; then
        rv_log INFO "caldera.service restarted old_pid=${old_pid:-none} new_pid=${new_pid} (${reason})"
        return 0
      fi
    fi
    sleep 1
    waited=$(( waited + 1 ))
  done
  rv_log ERROR "caldera.service restart did not produce a new server PID (old=${old_pid:-none} new=${new_pid:-none})"
  rv_caldera_log_runtime_auth_diag || true
  return 1
}

rv_caldera_log_runtime_auth_diag() {
  local py home diag_py
  home="$(rv_caldera_home)"
  diag_py="${_XDR_BOOTSTRAP_DIR}/../scripts/caldera_runtime_auth_diag.py"
  if [[ ! -f "${diag_py}" ]]; then
    diag_py="${XDR_ROOT:-}/scripts/caldera_runtime_auth_diag.py"
  fi
  py="$(command -v python3 || true)"
  [[ -x "${home}/.venv/bin/python3" ]] && py="${home}/.venv/bin/python3"
  [[ -f "${diag_py}" && -n "${py}" ]] || return 0
  "${py}" "${diag_py}" --caldera-home "${home}" 2>/dev/null | while read -r line; do
    rv_log INFO "caldera_runtime_auth_diag ${line}"
  done
}

# Resolve CALDERA runtime user without hard-coding appliance accounts.
rv_resolve_caldera_runtime_user() {
  local u
  if [[ -n "${XDR_LAB_CALDERA_USER}" ]] && rv_user_exists "${XDR_LAB_CALDERA_USER}"; then
    echo "${XDR_LAB_CALDERA_USER}"
    return 0
  fi
  if rv_user_exists caldera; then
    echo caldera
    return 0
  fi
  u="$(rv_caldera_service_user_from_unit)"
  if [[ -n "${u}" ]] && rv_user_exists "${u}"; then
    echo "${u}"
    return 0
  fi
  u="${SUDO_USER:-}"
  if [[ -n "${u}" ]] && rv_user_exists "${u}"; then
    echo "${u}"
    return 0
  fi
  u="$(logname 2>/dev/null || true)"
  if [[ -n "${u}" ]] && rv_user_exists "${u}"; then
    echo "${u}"
    return 0
  fi
  return 1
}

rv_systemd_show_field() {
  local unit="$1" field="$2" val
  val="$(rv_run_with_timeout "${XDR_LAB_SYSTEMCTL_TIMEOUT_SECS}" \
    "systemctl show ${unit} -p ${field}" \
    systemctl show "${unit}" -p "${field}" --value 2>/dev/null || true)"
  echo "${val}"
}

rv_decode_systemd_exec_failure() {
  local status="$1" code="$2"
  case "${status}/${code}" in
    217/*|*/217)
      echo "217/USER: configured User/Group missing or invalid — run bootstrap/ensure-caldera-runtime.sh and bootstrap/repair-caldera-service.sh"
      ;;
    203/*|*/203)
      echo "203/EXEC: ExecStart binary missing or not executable — run bootstrap/ensure-caldera-runtime.sh (venv repair)"
      ;;
    */126)
      echo "126: ExecStart found but not executable"
      ;;
    */127)
      echo "127: ExecStart command not found"
      ;;
    *)
      if [[ -n "${status}" || -n "${code}" ]]; then
        echo "systemd ExecMainStatus=${status} ExecMainCode=${code}"
      else
        echo "systemd service failed to start"
      fi
      ;;
  esac
}

rv_caldera_port_listening() {
  local port="$1"
  if command -v ss &>/dev/null; then
    rv_run_with_timeout "${XDR_LAB_PROBE_TIMEOUT_SECS}" \
      "ss -lntp port ${port}" \
      ss -lntp 2>/dev/null | grep -qE ":${port}\\b"
    return $?
  fi
  if command -v netstat &>/dev/null; then
    rv_run_with_timeout "${XDR_LAB_PROBE_TIMEOUT_SECS}" \
      "netstat -lntp port ${port}" \
      netstat -lntp 2>/dev/null | grep -qE ":${port}\\b"
    return $?
  fi
  return 1
}

rv_caldera_api_key_file() {
  echo "${API_KEY_FILE:-/etc/xdr-lab/caldera-api-key}"
}

rv_caldera_runtime_key_file() {
  local root="${XDR_ROOT:-/opt/xdr-lab}"
  echo "${root}/runtime/caldera-api-key"
}

rv_read_caldera_key_file() {
  local kf="$1" key="" runtime
  [[ -f "${kf}" ]] || return 1
  if [[ -r "${kf}" ]]; then
    key="$(tr -d '\n\r' <"${kf}")"
  elif runtime="$(rv_caldera_runtime_key_file)" && [[ -r "${runtime}" ]]; then
    key="$(tr -d '\n\r' <"${runtime}")"
  elif command -v sudo &>/dev/null && [[ "$(id -u)" -ne 0 ]]; then
    key="$(sudo tr -d '\n\r' <"${kf}" 2>/dev/null || true)"
  fi
  [[ -n "${key}" ]] || return 1
  printf '%s' "${key}"
}

rv_caldera_api_key() {
  local kf file_key env_key resolver root="${XDR_ROOT:-/opt/xdr-lab}"
  kf="$(rv_caldera_api_key_file)"
  file_key="$(rv_read_caldera_key_file "${kf}" 2>/dev/null || true)"
  env_key="${XDR_CALDERA_API_KEY:-}"
  if [[ -n "${file_key}" ]]; then
    if [[ -n "${env_key}" && "${env_key}" != "${file_key}" ]]; then
      rv_log WARN "XDR_CALDERA_API_KEY differs from readable key — using file (unset stale env)"
    fi
    printf '%s' "${file_key}"
    return 0
  fi
  if [[ -n "${env_key}" ]]; then
    printf '%s' "${env_key}"
    return 0
  fi
  resolver="${root}/scripts/caldera_api_key_resolve.py"
  if [[ ! -f "${resolver}" && -f "${_XDR_BOOTSTRAP_DIR}/../scripts/caldera_api_key_resolve.py" ]]; then
    resolver="${_XDR_BOOTSTRAP_DIR}/../scripts/caldera_api_key_resolve.py"
  fi
  if [[ -f "${resolver}" ]]; then
    file_key="$(python3 "${resolver}" --xdr-root "${root}" 2>/dev/null || true)"
    if [[ -n "${file_key}" ]]; then
      printf '%s' "${file_key}"
      return 0
    fi
  fi
  return 0
}

rv_caldera_log_auth_journal() {
  local lines="${1:-40}" journal filtered
  journal="$(rv_caldera_journal_recent "${lines}")"
  filtered="$(grep -F 'caldera.xdr.auth' <<<"${journal}" || true)"
  if [[ -z "${filtered}" ]]; then
    rv_log INFO "caldera.xdr.auth: no recent journal lines (enable: bootstrap/enable-caldera-auth-debug.sh)"
    return 0
  fi
  rv_log INFO "caldera.xdr.auth journal (from last ${lines} caldera.service lines):"
  while IFS= read -r line; do
    [[ -n "${line}" ]] && rv_log INFO "  ${line}"
  done <<<"${filtered}"
}

# CALDERA 5.x REST API auth header (app/service/auth_svc.py: HEADER_API_KEY = 'KEY').
# Not Authorization/Bearer. Legacy index routes: GET /api/{index} (e.g. /api/agents).
readonly RV_CALDERA_API_AUTH_HEADER="KEY"

# GET /api/agents without following redirects. Prints: code<TAB>location<TAB>content_type
rv_caldera_agents_http_meta() {
  local url="$1"
  shift || true
  local agents_url hdr code location ctype
  agents_url="${url%/}/api/agents"
  hdr="$(rv_run_with_timeout "${XDR_LAB_HTTP_PROBE_TIMEOUT_SECS}" \
    "curl -D - ${agents_url}" \
    curl -sS -D - -o /dev/null --connect-timeout 3 --max-time "${XDR_LAB_HTTP_PROBE_TIMEOUT_SECS}" \
      "$@" "${agents_url}" 2>/dev/null || true)"
  code="$(awk 'toupper($1) ~ /^HTTP\// { c=$2 } END { if (c == "") print "000"; else print c }' <<<"${hdr}")"
  location="$(awk -F': ' 'tolower($1) == "location" { sub(/\r$/, "", $2); print $2; exit }' <<<"${hdr}")"
  ctype="$(awk -F': ' 'tolower($1) == "content-type" { sub(/\r$/, "", $2); print $2; exit }' <<<"${hdr}")"
  printf '%s\t%s\t%s\n' "${code}" "${location}" "${ctype}"
}

# Probe GET /api/agents with CALDERA KEY header. Prints: header_name<TAB>http_code<TAB>location<TAB>content_type
rv_caldera_auth_probe() {
  local url="$1"
  local key="${2:-}"
  local header_name="${RV_CALDERA_API_AUTH_HEADER}"
  local meta
  if [[ -n "${key}" ]]; then
    meta="$(rv_caldera_agents_http_meta "${url}" -H "${header_name}: ${key}")"
  else
    meta="$(rv_caldera_agents_http_meta "${url}")"
  fi
  local code location ctype
  IFS=$'\t' read -r code location ctype <<<"${meta}"
  printf '%s\t%s\t%s\t%s\n' "${header_name}" "${code}" "${location}" "${ctype}"
}

rv_caldera_format_auth_failure() {
  local header_name="$1" http_code="$2" location="${3:-}" content_type="${4:-}"
  printf 'auth_probe header=%s http_code=%s location=%s content_type=%s' \
    "${header_name}" "${http_code}" "${location:-none}" "${content_type:-none}"
}

rv_caldera_http_probe_code() {
  local url="$1" meta code
  meta="$(rv_caldera_agents_http_meta "${url}")"
  code="${meta%%$'\t'*}"
  echo "${code}"
}

rv_caldera_login_http_code() {
  local url="$1" login_url hdr code
  login_url="${url%/}/login"
  hdr="$(rv_run_with_timeout "${XDR_LAB_HTTP_PROBE_TIMEOUT_SECS}" \
    "curl -D - ${login_url}" \
    curl -sS -D - -o /dev/null --connect-timeout 3 --max-time "${XDR_LAB_HTTP_PROBE_TIMEOUT_SECS}" \
      "${login_url}" 2>/dev/null || true)"
  code="$(awk 'toupper($1) ~ /^HTTP\// { c=$2 } END { if (c == "") print "000"; else print c }' <<<"${hdr}")"
  echo "${code}"
}

rv_caldera_http_ready() {
  local url="$1" code
  code="$(rv_caldera_login_http_code "${url}")"
  if [[ "${code}" == "200" ]]; then
    return 0
  fi
  code="$(rv_caldera_http_probe_code "${url}")"
  [[ "${code}" =~ ^(200|302|401|403)$ ]]
}

rv_caldera_api_authenticated() {
  local url="$1" key _hn code _loc _ct
  key="$(rv_caldera_api_key)"
  [[ -n "${key}" ]] || return 1
  IFS=$'\t' read -r _hn code _loc _ct < <(rv_caldera_auth_probe "${url}" "${key}")
  [[ "${code}" == "200" ]]
}

rv_caldera_journal_recent() {
  local lines="${1:-100}"
  rv_run_with_timeout "${XDR_LAB_SYSTEMCTL_TIMEOUT_SECS}" \
    "journalctl -u caldera.service -n ${lines}" \
    journalctl -u caldera.service -n "${lines}" --no-pager 2>/dev/null || true
}

rv_caldera_journal_suggests_building() {
  local journal="${1:-}"
  [[ -n "${journal}" ]] || return 1
  grep -qiE \
    'pip install|pip3 install|building wheel|compiling|downloading|setup\.py|requirements\.txt|--build|npm install|webpack|collecting |installing collected|getting requirements' \
    <<<"${journal}"
}

rv_caldera_journal_suggests_crash_loop() {
  local journal="${1:-}"
  [[ -n "${journal}" ]] || return 1
  grep -qiE \
    'traceback \(most recent|main process exited|failed with result|auto-restart|segmentation fault|fatal python error|modulenotfounderror|importerror|no module named' \
    <<<"${journal}"
}

# STARTING | BUILDING | RUNNING | FAILED
rv_caldera_classify_startup_state() {
  local active_state sub_state port journal listen_ok http_ok base_url
  active_state="$(rv_systemd_show_field caldera.service ActiveState)"
  sub_state="$(rv_systemd_show_field caldera.service SubState)"
  port="$(rv_caldera_port)"
  base_url="$(rv_caldera_base_url)"

  if [[ "${active_state}" == "activating" ]]; then
    echo "STARTING"
    return 0
  fi

  if [[ "${active_state}" == "failed" ]]; then
    echo "FAILED"
    return 0
  fi

  journal="$(rv_caldera_journal_recent 80)"
  if rv_caldera_journal_suggests_crash_loop "${journal}" \
      && [[ "${active_state}" != "active" || "${sub_state}" != "running" ]]; then
    echo "FAILED"
    return 0
  fi

  if [[ "${active_state}" == "active" && "${sub_state}" == "running" ]]; then
    listen_ok=0
    http_ok=0
    if rv_caldera_port_listening "${port}"; then
      listen_ok=1
    fi
    if rv_caldera_http_ready "${base_url}"; then
      http_ok=1
    fi
    if [[ "${listen_ok}" -eq 1 && "${http_ok}" -eq 1 ]]; then
      echo "RUNNING"
      return 0
    fi
    if rv_caldera_journal_suggests_building "${journal}"; then
      echo "BUILDING"
      return 0
    fi
    if rv_caldera_journal_suggests_crash_loop "${journal}"; then
      echo "FAILED"
      return 0
    fi
    if [[ "${listen_ok}" -eq 0 ]]; then
      echo "STARTING"
      return 0
    fi
    echo "STARTING"
    return 0
  fi

  echo "FAILED"
}

# Poll CALDERA until LISTENING + HTTP reachable (302 counts as up). Args: [timeout_secs].
# Do not pass a URL as $1 — use rv_caldera_wait_api_authenticated for KEY auth readiness.
rv_caldera_wait_ready() {
  local timeout_secs="${1:-${XDR_LAB_CALDERA_READY_TIMEOUT_SECS}}"
  local poll_secs="${XDR_LAB_CALDERA_READY_POLL_SECS}"
  local progress_secs="${XDR_LAB_CALDERA_READY_PROGRESS_SECS}"
  local port base_url started last_progress=0 elapsed state listen_ok http_ok agents_url login_code

  if [[ "${timeout_secs}" =~ ^https?:// ]]; then
    rv_log WARN "rv_caldera_wait_ready: numeric timeout expected, got URL — using default timeout"
    timeout_secs="${XDR_LAB_CALDERA_READY_TIMEOUT_SECS}"
  fi
  if ! [[ "${timeout_secs}" =~ ^[0-9]+$ ]]; then
    timeout_secs="${XDR_LAB_CALDERA_READY_TIMEOUT_SECS}"
  fi

  port="$(rv_caldera_port)"
  base_url="$(rv_caldera_base_url)"
  agents_url="$(rv_url_join_path "${base_url}" "api/agents")"
  started="$(date +%s)"

  while true; do
    elapsed=$(( $(date +%s) - started ))
    if (( elapsed >= timeout_secs )); then
      echo "FAILED timeout after ${timeout_secs}s (last_state=${state:-unknown})"
      return 1
    fi

    state="$(rv_caldera_classify_startup_state)"
    listen_ok=0
    http_ok=0
    if rv_caldera_port_listening "${port}"; then
      listen_ok=1
    fi
    login_code="$(rv_caldera_login_http_code "${base_url}")"
    if [[ "${login_code}" == "200" ]] || rv_caldera_http_ready "${base_url}"; then
      http_ok=1
    fi

    if [[ "${state}" == "FAILED" ]]; then
      echo "FAILED caldera.service unhealthy (see journalctl -u caldera.service)"
      return 1
    fi

    if [[ "${http_ok}" -eq 1 ]]; then
      echo "HTTP READY /login http_code=${login_code} api_probe=${agents_url} (${elapsed}s)"
      return 0
    fi
    if [[ "${listen_ok}" -eq 1 ]]; then
      phase="LISTENING"
    elif [[ "${state}" == "BUILDING" ]]; then
      phase="BUILDING"
    else
      phase="${state:-STARTING}"
    fi

    if (( elapsed >= last_progress )); then
      echo "${phase} elapsed=${elapsed}s port=${port}"
      last_progress=$(( elapsed + progress_secs ))
    fi

    sleep "${poll_secs}"
  done
}

# Wait for tcp/port, HTTP up, then GET /api/agents with KEY returns 200. Args: api_key [timeout_secs].
rv_caldera_wait_api_authenticated() {
  local api_key="$1"
  local timeout_secs="${2:-${XDR_LAB_CALDERA_READY_TIMEOUT_SECS}}"
  local poll_secs="${XDR_LAB_CALDERA_READY_POLL_SECS}"
  local progress_secs="${XDR_LAB_CALDERA_READY_PROGRESS_SECS}"
  local port base_url started last_progress=0 elapsed listen_ok auth_ok _hn code _loc _ct agents_url

  if [[ "${timeout_secs}" =~ ^https?:// ]]; then
    timeout_secs="${XDR_LAB_CALDERA_READY_TIMEOUT_SECS}"
  fi
  if ! [[ "${timeout_secs}" =~ ^[0-9]+$ ]]; then
    timeout_secs="${XDR_LAB_CALDERA_READY_TIMEOUT_SECS}"
  fi
  [[ -n "${api_key}" ]] || return 1

  port="$(rv_caldera_port)"
  base_url="$(rv_caldera_base_url)"
  agents_url="$(rv_url_join_path "${base_url}" "api/agents")"
  started="$(date +%s)"

  while true; do
    elapsed=$(( $(date +%s) - started ))
    if (( elapsed >= timeout_secs )); then
      echo "AUTH_FAILED timeout after ${timeout_secs}s header=${RV_CALDERA_API_AUTH_HEADER} http_code=${code:-000}"
      return 1
    fi

    listen_ok=0
    auth_ok=0
    if rv_caldera_port_listening "${port}"; then
      listen_ok=1
      IFS=$'\t' read -r _hn code _loc _ct < <(rv_caldera_auth_probe "${base_url}" "${api_key}")
      [[ "${code}" == "200" ]] && auth_ok=1
    fi

    if [[ "${auth_ok}" -eq 1 ]]; then
      echo "API_AUTH_READY ${agents_url} header=${RV_CALDERA_API_AUTH_HEADER} http_code=200 (${elapsed}s)"
      return 0
    fi

    if (( elapsed >= last_progress )); then
      if [[ "${listen_ok}" -eq 1 ]]; then
        echo "API_AUTH_WAIT header=${RV_CALDERA_API_AUTH_HEADER} http_code=${code:-000} location=${_loc:-none} elapsed=${elapsed}s"
      else
        echo "LISTEN_WAIT elapsed=${elapsed}s port=${port}"
      fi
      last_progress=$(( elapsed + progress_secs ))
    fi

    sleep "${poll_secs}"
  done
}

rv_write_host_network_boot_marker() {
  local state_path boot_id ts
  state_path="$(rv_host_network_boot_state)"
  boot_id="$(rv_current_boot_id)" || boot_id="unknown"
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  mkdir -p "$(dirname "${state_path}")"
  python3 - "${state_path}" "${boot_id}" "${ts}" <<'PY'
import json, sys
path, boot_id, ts = sys.argv[1:4]
payload = {
    "boot_id": boot_id,
    "finished_at": ts,
    "script": "ensure-host-network.sh",
}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2, sort_keys=True)
    fh.write("\n")
PY
}

rv_mirror_helper() {
  local candidate
  for candidate in \
    "${XDR_SCRIPTS_DIR:-}/ovs_mirror_state.py" \
    "${XDR_ROOT}/scripts/ovs_mirror_state.py" \
    "${_XDR_BOOTSTRAP_DIR}/../scripts/ovs_mirror_state.py"; do
    [[ -n "${candidate}" && -f "${candidate}" ]] || continue
    echo "${candidate}"
    return 0
  done
  return 1
}

# Sensor VM name from lab-vms.json (network.ovs_mirror.sensor_vm / type=sensor) or default.
rv_resolve_sensor_vm() {
  local cfg="${XDR_LAB_VMS_JSON:-}"
  if [[ -f "${cfg}" ]] && command -v jq &>/dev/null; then
    local from_cfg
    from_cfg="$(jq -r '
      .network.ovs_mirror.sensor_vm //
      ([.vms[]? | select(.type == "sensor") | .name] | first) //
      empty
    ' "${cfg}" 2>/dev/null || true)"
    if [[ -n "${from_cfg}" && "${from_cfg}" != "null" ]]; then
      echo "${from_cfg}"
      return 0
    fi
  fi
  echo "${XDR_LAB_SENSOR_VM:-sensor-vm}"
}

rv_virsh_system() {
  rv_run_with_timeout "${XDR_LAB_VIRSH_TIMEOUT_SECS}" \
    "virsh -c qemu:///system $*" \
    virsh -c qemu:///system "$@"
}

rv_virsh_system_domstate() {
  local vm="$1" state
  state="$(rv_virsh_system domstate "${vm}" 2>/dev/null | tr -d '\r' | awk 'END{print $0}')"
  echo "${state}"
}

rv_virsh_system_domiflist() {
  local vm="$1"
  rv_virsh_system domiflist "${vm}" 2>/dev/null
}

# Return the OVS/Linux bridge name from a libvirt network XML (e.g. ovs-net → br0).
rv_libvirt_network_bridge_name() {
  local net_name="$1" xml bridge
  xml="$(rv_virsh_system net-dumpxml "${net_name}" 2>/dev/null)" || return 1
  bridge="$(printf '%s\n' "${xml}" | sed -n \
    -e "s/.*<bridge[^>]*name=['\"]\\([^'\"]*\\)['\"].*/\\1/p" \
    | head -n1)"
  [[ -n "${bridge}" ]] || return 1
  echo "${bridge}"
}

# True when domiflist Source is the target bridge or a libvirt net that bridges to it.
rv_domiflist_source_targets_bridge() {
  local source="$1" bridge="$2" net_bridge
  if [[ "${source}" == "${bridge}" ]]; then
    return 0
  fi
  net_bridge="$(rv_libvirt_network_bridge_name "${source}" 2>/dev/null)" || return 1
  [[ "${net_bridge}" == "${bridge}" ]]
}

# Discover all sensor taps (vnetN) on LAB_BRIDGE via virsh domiflist (qemu:///system).
rv_sensor_vnets_on_bridge() {
  local vm="$1" bridge="${2:-${LAB_BRIDGE}}"
  local domiflist ports_out ports_rc=0
  local iface source row stale_iface="" stale_source=""
  local -a vnet_rows=() matched_rows=()

  domiflist="$(rv_virsh_system_domiflist "${vm}" 2>/dev/null)" || true
  if [[ -z "${domiflist}" ]]; then
    echo "No libvirt vnet interface found for ${vm}" >&2
    return 1
  fi

  while IFS=$'\t' read -r iface source; do
    [[ -n "${iface}" ]] || continue
    vnet_rows+=("${iface}|${source}")
  done < <(printf '%s\n' "${domiflist}" | awk '
    NR>2 && $1 != "" && $1 !~ /^---/ && tolower($1) != "interface" && $1 ~ /^vnet/ {
      print $1 "\t" $3
    }
  ')

  if [[ "${#vnet_rows[@]}" -eq 0 ]]; then
    echo "No libvirt vnet interface found for ${vm}" >&2
    return 1
  fi

  if command -v ovs-vsctl &>/dev/null; then
    set +e
    ports_out="$(rv_run_with_timeout "${XDR_LAB_OVS_VSCTL_TIMEOUT_SECS}" \
      "ovs-vsctl list-ports ${bridge}" \
      ovs-vsctl list-ports "${bridge}" 2>&1)"
    ports_rc=$?
    set -e
    if [[ "${ports_rc}" -ne 0 ]]; then
      echo "${ports_out}" >&2
      return 1
    fi
  else
    ports_out=""
  fi

  for row in "${vnet_rows[@]}"; do
    IFS='|' read -r iface source <<<"${row}"
    if ! rv_domiflist_source_targets_bridge "${source}" "${bridge}"; then
      continue
    fi
    if [[ -z "${ports_out}" ]] || grep -qxF "${iface}" <<<"${ports_out}"; then
      matched_rows+=("${iface}")
      continue
    fi
    stale_iface="${iface}"
    stale_source="${source}"
  done

  if [[ "${#matched_rows[@]}" -gt 0 ]]; then
    printf '%s\n' "${matched_rows[@]}"
    return 0
  fi

  if [[ -n "${stale_iface}" ]]; then
    echo "VM interface ${stale_iface} found via ${stale_source} but not present on OVS bridge ${bridge}" >&2
    return 1
  fi

  echo "No libvirt vnet interface found for ${vm}" >&2
  return 1
}

# Legacy helper: first sensor tap is the management NIC.
rv_sensor_vnet_on_bridge() {
  rv_sensor_vnets_on_bridge "$@" | head -n1
}

rv_sensor_mgmt_vnet_on_bridge() {
  rv_sensor_vnets_on_bridge "$@" | head -n1
}

# Official Stellar sensor model: first tap is management, second tap is capture.
rv_sensor_capture_vnet_on_bridge() {
  local vm="$1" bridge="${2:-${LAB_BRIDGE}}"
  local taps
  taps="$(rv_sensor_vnets_on_bridge "${vm}" "${bridge}")" || return 1
  local count
  count="$(printf '%s\n' "${taps}" | awk 'NF {n++} END {print n+0}')"
  if [[ "${count}" -lt 2 ]]; then
    echo "Dedicated capture interface missing for ${vm}; single-NIC mirror reuse is unsupported" >&2
    return 1
  fi
  printf '%s\n' "${taps}" | awk 'NF {n++; if (n == 2) {print; exit}}'
}

rv_ovs_br_exists() {
  command -v ovs-vsctl &>/dev/null || return 1
  rv_run_with_timeout "${XDR_LAB_OVS_VSCTL_TIMEOUT_SECS}" \
    "ovs-vsctl br-exists ${LAB_BRIDGE}" \
    ovs-vsctl br-exists "${LAB_BRIDGE}" &>/dev/null
}

rv_ovs_mirror_uuid_by_name() {
  local mirror_name="${1:-${XDR_LAB_MIRROR_NAME}}"
  rv_run_with_timeout "${XDR_LAB_OVS_VSCTL_TIMEOUT_SECS}" \
    "ovs-vsctl find mirror name=${mirror_name}" \
    ovs-vsctl --columns=_uuid --bare find mirror "name=${mirror_name}" 2>/dev/null \
    | head -n1
}

rv_ovs_mirror_output_port_name() {
  local mirror_uuid="$1" port_uuid
  [[ -n "${mirror_uuid}" ]] || return 1
  port_uuid="$(rv_run_with_timeout "${XDR_LAB_OVS_VSCTL_TIMEOUT_SECS}" \
    "ovs-vsctl list mirror output_port" \
    ovs-vsctl --columns=output_port --bare list mirror "${mirror_uuid}" 2>/dev/null \
    | head -n1)"
  [[ -n "${port_uuid}" ]] || return 1
  rv_run_with_timeout "${XDR_LAB_OVS_VSCTL_TIMEOUT_SECS}" \
    "ovs-vsctl list port name" \
    ovs-vsctl --columns=name --bare list port "${port_uuid}" 2>/dev/null
}

rv_ovs_mirror_select_all_enabled() {
  local mirror_uuid="$1" val
  [[ -n "${mirror_uuid}" ]] || return 1
  val="$(rv_run_with_timeout "${XDR_LAB_OVS_VSCTL_TIMEOUT_SECS}" \
    "ovs-vsctl list mirror select_all" \
    ovs-vsctl --columns=select_all --bare list mirror "${mirror_uuid}" 2>/dev/null \
    | head -n1)"
  [[ "${val}" == "true" ]]
}

rv_ovs_mirror_attached_to_bridge() {
  local mirror_uuid="$1" bridge="${2:-${LAB_BRIDGE}}"
  local mirrors_raw
  [[ -n "${mirror_uuid}" ]] || return 1
  mirrors_raw="$(rv_run_with_timeout "${XDR_LAB_OVS_VSCTL_TIMEOUT_SECS}" \
    "ovs-vsctl list bridge mirrors" \
    ovs-vsctl --columns=mirrors --bare list bridge "${bridge}" 2>/dev/null)"
  grep -qF "${mirror_uuid}" <<<"${mirrors_raw}"
}
