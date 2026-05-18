#!/usr/bin/env bash
# Stellar appliance CLI installer — installs Python entrypoint and XDR Lab assets.
# Does not install distro packages (apt/yum) or embed VM images.
#
# Layout (xdr-lab-appliance):
#   installer/cli-installer.sh   <-- this script
#   installer/lab-host-web-console-deps.sh  <-- optional apt/dnf: novnc + websockify
#   appliance/appliance_cli.py   <-- Python entrypoint installed via pip
#   appliance/setup.py
#   scripts/vm_runtime_state.py     <-- installed to ${XDR_ROOT}/scripts/
#   scripts/ovs_mirror_state.py
#   scripts/nat_state.py
#   scripts/snapshot_state.py
#   scripts/caldera_orchestration.py
#   scripts/tool_runtime_manager.py
#   scripts/image_download_manager.py
#   scripts/windows_lab_helpers.sh
#   scripts/vnc_proxy_helpers.sh
#   scripts/xdr-lab-vm-manager.sh <-- installed to ${XDR_ROOT}/scripts/
#   config/paths.sh                 <-- installed to ${XDR_ROOT}/config/
#   config/lab-vms.json             <-- installed to ${XDR_ROOT}/config/
#   config/images-manifest.json     <-- installed to ${XDR_ROOT}/config/
#   config/tool-runtime.json        <-- installed to ${XDR_ROOT}/config/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -f "${PROJECT_ROOT}/config/paths.sh" ]]; then
  # shellcheck source=../config/paths.sh
  . "${PROJECT_ROOT}/config/paths.sh"
fi

XDR_ROOT="${XDR_ROOT:-/opt/xdr-lab}"
XDR_LAB_GROUP="${XDR_LAB_GROUP:-xdr-lab}"
XDR_LAB_OPERATOR_USER="${XDR_LAB_OPERATOR_USER:-${SUDO_USER:-}}"
APP_DIR="${PROJECT_ROOT}/appliance"
SRC_SCRIPTS="${PROJECT_ROOT}/scripts"
SRC_CONFIG="${PROJECT_ROOT}/config"
SRC_BOOTSTRAP="${PROJECT_ROOT}/bootstrap"
SRC_SCENARIOS="${PROJECT_ROOT}/scenarios"
CLI_VENV_DIR="${CLI_VENV_DIR:-${XDR_ROOT}/venv}"
CLI_INSTALL_MODE="${CLI_INSTALL_MODE:-venv}"  # venv | pipx | system (legacy; PEP668 may block)

if [[ ! -f "${APP_DIR}/appliance_cli.py" || ! -f "${APP_DIR}/setup.py" ]]; then
  echo "ERROR: appliance/appliance_cli.py or appliance/setup.py missing under ${PROJECT_ROOT}." >&2
  exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "This installer expects root so it can write to ${XDR_ROOT}." >&2
  echo "Re-run with sudo, or set XDR_ROOT to a user-writable path." >&2
  exit 1
fi

mkdir -p \
  "${XDR_ROOT}/images" \
  "${XDR_ROOT}/scripts" \
  "${XDR_ROOT}/config" \
  "${XDR_ROOT}/scenarios" \
  "${XDR_ROOT}/bootstrap" \
  "${XDR_ROOT}/runtime" \
  "${XDR_ROOT}/runtime/state" \
  "${XDR_ROOT}/runtime/tools" \
  "${XDR_ROOT}/runtime/vnc-proxy" \
  "${XDR_ROOT}/runtime/web-console" \
  "${XDR_ROOT}/installer" \
  "${XDR_ROOT}/patches/caldera" \
  "${XDR_ROOT}/logs"

install -m 0644 "${SRC_CONFIG}/paths.sh"              "${XDR_ROOT}/config/paths.sh"
install -m 0644 "${SRC_CONFIG}/lab-vms.json"          "${XDR_ROOT}/config/lab-vms.json"
install -m 0644 "${SRC_CONFIG}/images-manifest.json"  "${XDR_ROOT}/config/images-manifest.json"
install -m 0644 "${SRC_CONFIG}/caldera-lab.json"      "${XDR_ROOT}/config/caldera-lab.json"
install -m 0644 "${SRC_CONFIG}/tool-runtime.json"     "${XDR_ROOT}/config/tool-runtime.json"
install -m 0644 "${SRC_SCRIPTS}/vm_runtime_state.py"   "${XDR_ROOT}/scripts/vm_runtime_state.py"
install -m 0644 "${SRC_SCRIPTS}/ovs_mirror_state.py"   "${XDR_ROOT}/scripts/ovs_mirror_state.py"
install -m 0644 "${SRC_SCRIPTS}/nat_state.py"          "${XDR_ROOT}/scripts/nat_state.py"
install -m 0644 "${SRC_SCRIPTS}/snapshot_state.py"     "${XDR_ROOT}/scripts/snapshot_state.py"
install -m 0644 "${SRC_SCRIPTS}/caldera_orchestration.py" "${XDR_ROOT}/scripts/caldera_orchestration.py"
install -m 0644 "${SRC_SCRIPTS}/tool_runtime_manager.py" "${XDR_ROOT}/scripts/tool_runtime_manager.py"
install -m 0644 "${SRC_SCRIPTS}/image_download_manager.py" "${XDR_ROOT}/scripts/image_download_manager.py"
install -m 0644 "${SRC_SCRIPTS}/caldera_api_key_resolve.py" "${XDR_ROOT}/scripts/caldera_api_key_resolve.py"
install -m 0644 "${SRC_SCRIPTS}/caldera_api_key_util.py" "${XDR_ROOT}/scripts/caldera_api_key_util.py"
install -m 0644 "${SRC_SCRIPTS}/caldera_key_crypto.py" "${XDR_ROOT}/scripts/caldera_key_crypto.py"
install -m 0644 "${SRC_SCRIPTS}/caldera_config_diag.py" "${XDR_ROOT}/scripts/caldera_config_diag.py"
install -m 0644 "${SRC_SCRIPTS}/caldera_runtime_auth_diag.py" "${XDR_ROOT}/scripts/caldera_runtime_auth_diag.py"
install -m 0644 "${SRC_SCRIPTS}/caldera_process_util.py" "${XDR_ROOT}/scripts/caldera_process_util.py"
install -m 0644 "${SRC_SCRIPTS}/windows_lab_helpers.sh" "${XDR_ROOT}/scripts/windows_lab_helpers.sh"
install -m 0644 "${SRC_SCRIPTS}/vnc_proxy_helpers.sh" "${XDR_ROOT}/scripts/vnc_proxy_helpers.sh"
install -m 0755 "${SRC_SCRIPTS}/xdr-lab-vm-manager.sh" "${XDR_ROOT}/scripts/xdr-lab-vm-manager.sh"
if [[ -f "${PROJECT_ROOT}/scripts/patch_caldera_auth_debug.py" ]]; then
  install -m 0644 "${PROJECT_ROOT}/scripts/patch_caldera_auth_debug.py" "${XDR_ROOT}/scripts/patch_caldera_auth_debug.py"
fi
if [[ -f "${PROJECT_ROOT}/patches/caldera/xdr_auth_debug.py" ]]; then
  install -m 0644 "${PROJECT_ROOT}/patches/caldera/xdr_auth_debug.py" "${XDR_ROOT}/patches/caldera/xdr_auth_debug.py"
fi
install -m 0755 "${PROJECT_ROOT}/installer/lab-host-web-console-deps.sh" "${XDR_ROOT}/installer/lab-host-web-console-deps.sh"
install -m 0755 "${PROJECT_ROOT}/xdr-lab.sh" "${XDR_ROOT}/xdr-lab.sh"

for _rv_script in \
  _runtime-validation-lib.sh \
  validate-host-network.sh \
  validate-libvirt.sh \
  validate-caldera.sh \
  verify-caldera-runtime.sh \
  validate-sensor-identity.sh \
  validate-web-console.sh \
  validate-appliance.sh \
  ensure-caldera-runtime.sh \
  ensure-caldera-api-key.sh \
  repair-caldera-service.sh \
  sync-caldera-api-key-runtime.sh \
  reconcile-caldera-auth-runtime.sh \
  deploy-caldera-runtime-fix.sh \
  fix-runtime-state.sh \
  ensure-ovs-mirror.sh \
  validate-ovs-mirror.sh \
  ensure-host-network.sh \
  ensure-nat-contract.sh; do
  install -m 0755 "${SRC_BOOTSTRAP}/${_rv_script}" "${XDR_ROOT}/bootstrap/${_rv_script}"
done

verify_installed_mirror_asset() {
  local src="$1" dst="$2"
  if [[ ! -f "${dst}" ]]; then
    echo "ERROR: required mirror diagnostics asset missing after install: ${dst}" >&2
    exit 1
  fi
  if ! cmp -s "${src}" "${dst}"; then
    echo "ERROR: installed mirror diagnostics asset differs from source: ${dst}" >&2
    exit 1
  fi
  echo "Installed mirror diagnostics asset: ${dst}"
}

verify_installed_mirror_asset "${SRC_SCRIPTS}/ovs_mirror_state.py" "${XDR_ROOT}/scripts/ovs_mirror_state.py"
verify_installed_mirror_asset "${SRC_SCRIPTS}/xdr-lab-vm-manager.sh" "${XDR_ROOT}/scripts/xdr-lab-vm-manager.sh"
verify_installed_mirror_asset "${SRC_SCRIPTS}/caldera_orchestration.py" "${XDR_ROOT}/scripts/caldera_orchestration.py"
verify_installed_mirror_asset "${SRC_BOOTSTRAP}/_runtime-validation-lib.sh" "${XDR_ROOT}/bootstrap/_runtime-validation-lib.sh"
verify_installed_mirror_asset "${SRC_BOOTSTRAP}/validate-ovs-mirror.sh" "${XDR_ROOT}/bootstrap/validate-ovs-mirror.sh"
verify_installed_mirror_asset "${SRC_BOOTSTRAP}/ensure-ovs-mirror.sh" "${XDR_ROOT}/bootstrap/ensure-ovs-mirror.sh"

if [[ -d "${SRC_SCENARIOS}" ]]; then
  find "${XDR_ROOT}/scenarios" -maxdepth 1 -type f \( -name '*.json' -o -name '*.yaml' -o -name '*.yml' \) -delete
  find "${SRC_SCENARIOS}" -maxdepth 1 -type f \( -name '*.json' -o -name '*.yaml' -o -name '*.yml' \) -print0 \
    | while IFS= read -r -d '' _scenario; do
        install -m 0644 "${_scenario}" "${XDR_ROOT}/scenarios/$(basename "${_scenario}")"
      done
fi

for _atomic_script in \
  atomic-red-team-linux.sh \
  atomic-red-team-windows.ps1; do
  if [[ -f "${SRC_BOOTSTRAP}/${_atomic_script}" ]]; then
    install -m 0755 "${SRC_BOOTSTRAP}/${_atomic_script}" "${XDR_ROOT}/bootstrap/${_atomic_script}"
  fi
done

install -m 0644 "${PROJECT_ROOT}/installer/99-xdr-lab-ip-forward.conf" \
  /etc/sysctl.d/99-xdr-lab-ip-forward.conf
sysctl --system >/dev/null 2>&1 || sysctl -p /etc/sysctl.d/99-xdr-lab-ip-forward.conf >/dev/null 2>&1 || true

if [[ ! -f /etc/systemd/system/caldera.service ]]; then
  install -m 0644 "${PROJECT_ROOT}/installer/caldera.service" \
    /etc/systemd/system/caldera.service.tmp
  sed "s|/opt/xdr-lab|${XDR_ROOT}|g" \
    /etc/systemd/system/caldera.service.tmp \
    > /etc/systemd/system/caldera.service
  rm -f /etc/systemd/system/caldera.service.tmp
else
  echo "Existing caldera.service preserved; bootstrap/repair-caldera-service.sh owns CALDERA unit reconciliation."
fi

install -m 0644 "${PROJECT_ROOT}/installer/xdr-lab-host-network.service" \
  /etc/systemd/system/xdr-lab-host-network.service.tmp
sed -e "s|/opt/xdr-lab|${XDR_ROOT}|g" \
  /etc/systemd/system/xdr-lab-host-network.service.tmp \
  > /etc/systemd/system/xdr-lab-host-network.service
rm -f /etc/systemd/system/xdr-lab-host-network.service.tmp

install -m 0644 "${PROJECT_ROOT}/installer/xdr-lab-web-console@.service" \
  /etc/systemd/system/xdr-lab-web-console@.service.tmp
sed -e "s|/opt/xdr-lab|${XDR_ROOT}|g" \
  /etc/systemd/system/xdr-lab-web-console@.service.tmp \
  > /etc/systemd/system/xdr-lab-web-console@.service
rm -f /etc/systemd/system/xdr-lab-web-console@.service.tmp

ensure_xdr_lab_group() {
  if ! getent group "${XDR_LAB_GROUP}" >/dev/null 2>&1; then
    groupadd --system "${XDR_LAB_GROUP}"
  fi
  if [[ -n "${XDR_LAB_OPERATOR_USER}" && "${XDR_LAB_OPERATOR_USER}" != "root" ]]; then
    if id "${XDR_LAB_OPERATOR_USER}" >/dev/null 2>&1; then
      usermod -aG "${XDR_LAB_GROUP}" "${XDR_LAB_OPERATOR_USER}" 2>/dev/null || true
    fi
  fi
}

configure_group_tree_writable() {
  local _dir
  ensure_xdr_lab_group
  chown -R root:root "${XDR_ROOT}/config" "${XDR_ROOT}/scripts" "${XDR_ROOT}/bootstrap" "${XDR_ROOT}/installer" "${XDR_ROOT}/scenarios"
  chmod 0755 "${XDR_ROOT}/config" "${XDR_ROOT}/scripts" "${XDR_ROOT}/bootstrap" "${XDR_ROOT}/installer" "${XDR_ROOT}/scenarios"
  for _dir in "${XDR_ROOT}/logs" "${XDR_ROOT}/runtime" "${XDR_ROOT}/runtime/state" "${XDR_ROOT}/runtime/tools" "${XDR_ROOT}/images"; do
    chown root:"${XDR_LAB_GROUP}" "${_dir}"
    chmod 2775 "${_dir}"
    if command -v setfacl >/dev/null 2>&1; then
      setfacl -m "g:${XDR_LAB_GROUP}:rwx" "${_dir}" 2>/dev/null || true
      setfacl -d -m "g:${XDR_LAB_GROUP}:rwx" "${_dir}" 2>/dev/null || true
    fi
  done
  if [[ -d "${XDR_ROOT}/images" ]]; then
    find "${XDR_ROOT}/images" -type d -exec chown root:"${XDR_LAB_GROUP}" {} \;
    find "${XDR_ROOT}/images" -type d -exec chmod 2775 {} \;
    find "${XDR_ROOT}/images" -type f -exec chown root:"${XDR_LAB_GROUP}" {} \;
    find "${XDR_ROOT}/images" -type f -exec chmod g+rw {} \;
  fi
  for _logf in \
    host-runtime-validation.log \
    vm-manager.log \
    caldera-orchestration.jsonl; do
    touch "${XDR_ROOT}/logs/${_logf}"
    chown root:"${XDR_LAB_GROUP}" "${XDR_ROOT}/logs/${_logf}"
    chmod 0664 "${XDR_ROOT}/logs/${_logf}"
  done
  if [[ -d "${XDR_ROOT}/runtime/state" ]]; then
    find "${XDR_ROOT}/runtime/state" -maxdepth 1 -type f -exec chown root:"${XDR_LAB_GROUP}" {} \;
    find "${XDR_ROOT}/runtime/state" -maxdepth 1 -type f -exec chmod 0664 {} \;
  fi
}

configure_group_tree_writable

configure_etc_xdr_lab_permissions() {
  ensure_xdr_lab_group
  mkdir -p /etc/xdr-lab
  chown root:"${XDR_LAB_GROUP}" /etc/xdr-lab
  chmod 0750 /etc/xdr-lab
}

configure_caldera_api_key_readable() {
  local etc_key="/etc/xdr-lab/caldera-api-key"
  local resolver="${SRC_SCRIPTS}/caldera_api_key_resolve.py"
  mkdir -p "${XDR_ROOT}/runtime"
  configure_etc_xdr_lab_permissions
  if [[ -f "${etc_key}" ]]; then
    if getent group "${XDR_LAB_GROUP}" >/dev/null 2>&1; then
      chown root:"${XDR_LAB_GROUP}" "${etc_key}"
      chmod 0640 "${etc_key}"
    fi
  fi
  if [[ -f "${resolver}" ]]; then
    python3 "${resolver}" --sync-runtime --xdr-root "${XDR_ROOT}" --group "${XDR_LAB_GROUP}" \
      || echo "WARN: runtime CALDERA API key copy not synced (run: sudo bootstrap/ensure-caldera-api-key.sh)" >&2
  fi
}

configure_caldera_api_key_readable

configure_stellar_download_credentials_readable() {
  local stellar_env="/etc/xdr-lab/stellar-download.env"
  configure_etc_xdr_lab_permissions
  if [[ -f "${stellar_env}" ]]; then
    chown root:"${XDR_LAB_GROUP}" "${stellar_env}"
    chmod 0640 "${stellar_env}"
    echo "Normalized Stellar download credential file permissions: ${stellar_env} owner=root group=${XDR_LAB_GROUP} mode=0640"
  else
    echo "Stellar download credential file not found: ${stellar_env}"
    echo "Create it when credentials are available; installer will not create an empty credential file."
    echo "Expected permissions after creation: owner=root group=${XDR_LAB_GROUP} mode=0640"
  fi
}

configure_stellar_download_credentials_readable

systemctl daemon-reload

install_systemd_unit() {
  local unit="$1"
  if ! systemctl enable "${unit}"; then
    echo "ERROR: failed to enable ${unit}" >&2
    exit 1
  fi
  if ! systemctl start "${unit}"; then
    echo "ERROR: failed to start ${unit} — check journalctl -u ${unit}" >&2
    exit 1
  fi
  if ! systemctl is-enabled --quiet "${unit}"; then
    echo "ERROR: ${unit} is not enabled after install" >&2
    exit 1
  fi
}

install_systemd_unit xdr-lab-host-network.service

if ! systemctl enable xdr-lab-web-console@windows-victim.service; then
  echo "WARN: failed to enable xdr-lab-web-console@windows-victim.service (optional management console)" >&2
fi

if [[ -f /opt/caldera/server.py ]]; then
  CALDERA_RUNTIME_CHANGED=0
  id -u caldera >/dev/null 2>&1 || useradd --system --home-dir /opt/caldera --create-home --shell /bin/bash caldera 2>/dev/null || true
  "${XDR_ROOT}/bootstrap/ensure-caldera-runtime.sh" \
    || echo "WARN: ensure-caldera-runtime failed; run sudo ${XDR_ROOT}/bootstrap/deploy-caldera-runtime-fix.sh" >&2
  if [[ -f /opt/caldera/.venv/.xdr-lab-runtime-changed ]]; then
    CALDERA_RUNTIME_CHANGED="$(tr -d '\n\r' </opt/caldera/.venv/.xdr-lab-runtime-changed 2>/dev/null || echo 0)"
  fi
  "${XDR_ROOT}/bootstrap/ensure-caldera-api-key.sh" --wait \
    || echo "WARN: ensure-caldera-api-key failed; run sudo ${XDR_ROOT}/bootstrap/ensure-caldera-api-key.sh --wait" >&2
  XDR_LAB_CALDERA_RUNTIME_CHANGED="${CALDERA_RUNTIME_CHANGED}" \
    "${XDR_ROOT}/bootstrap/repair-caldera-service.sh" --start \
    || echo "WARN: repair-caldera-service failed; inspect journalctl -u caldera.service" >&2
fi

install_cli_editable() {
  case "${CLI_INSTALL_MODE}" in
    venv)
      python3 -m venv "${CLI_VENV_DIR}"
      "${CLI_VENV_DIR}/bin/python" -m pip install --upgrade pip wheel
      "${CLI_VENV_DIR}/bin/pip" install --upgrade "${APP_DIR}"
      install -m 0755 /dev/stdin /usr/local/bin/aella_cli <<EOF
#!/usr/bin/env bash
exec "${CLI_VENV_DIR}/bin/aella_cli" "\$@"
EOF
      ;;
    pipx)
      if ! command -v pipx >/dev/null 2>&1; then
        echo "ERROR: pipx not found. Install pipx or set CLI_INSTALL_MODE=venv." >&2
        exit 1
      fi
      pipx install --force "${APP_DIR}"
      ;;
    system)
      python3 -m pip install --upgrade "${APP_DIR}"
      ;;
    *)
      echo "ERROR: unknown CLI_INSTALL_MODE=${CLI_INSTALL_MODE} (use venv, pipx, or system)." >&2
      exit 1
      ;;
  esac
}

install_cli_editable

echo "Installed aella_cli (${CLI_INSTALL_MODE}) and ${XDR_ROOT} lab assets."
if [[ -n "${XDR_LAB_OPERATOR_USER}" && "${XDR_LAB_OPERATOR_USER}" != "root" ]]; then
  echo "Operator ${XDR_LAB_OPERATOR_USER} added to group ${XDR_LAB_GROUP} (re-login for new group membership)."
  echo "Current shells may not see the new group yet; run: id; groups; newgrp ${XDR_LAB_GROUP}"
  echo "Logs: ${XDR_ROOT}/logs (group-writable; setgid 2775)."
fi
echo ""
echo "Development editable install (PEP668-safe):"
echo "  cd ${APP_DIR} && python3 -m venv .venv && source .venv/bin/activate && pip install -e ."
