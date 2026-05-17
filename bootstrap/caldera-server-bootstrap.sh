#!/usr/bin/env bash
# XDR Lab — MITRE CALDERA server bootstrap for Ubuntu 24.04 (appliance host or admin VM).
#
# Installs: Python venv, pip requirements, Node/npm (UI build), git, CALDERA clone,
#           patches conf/default.yml bind address, API key, optional plugins, systemd unit.
#
# Usage:
#   sudo CALDERA_LISTEN_HOST=0.0.0.0 CALDERA_PORT=8888 \
#        ./bootstrap/caldera-server-bootstrap.sh
#   ./bootstrap/caldera-server-bootstrap.sh --dry-run   # no root; no changes
#
# If CALDERA_PLUGINS is empty, default.yml is patched with sed for a few keys only
# (preserves comments and order as much as possible).
# If CALDERA_PLUGINS is set (comma-separated), plugins are rewritten via PyYAML
# (comments in default.yml may be lost).
#
# CALDERA_SKIP_SYSTEMD=1 skips writing the systemd unit, daemon-reload, enable/start.
#
# API key:
#   By default a random key is written to /etc/xdr-lab/caldera-api-key (0600) and
#   mirrored into api_key_red in conf/default.yml. Operators must align the same value
#   with XDR Lab via XDR_CALDERA_API_KEY or api_key_file in config/caldera-lab.json
#   (docs/caldera-integration.md).
#
# Note: first start may take several minutes for UI build. Do not put '/' or other
#       sed-special characters in CALDERA_LISTEN_HOST (sed-based patch path).
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DRY_RUN=0
CALDERA_HOME="${CALDERA_HOME:-/opt/caldera}"
CALDERA_USER="${CALDERA_USER:-caldera}"
CALDERA_LISTEN_HOST="${CALDERA_LISTEN_HOST:-0.0.0.0}"
CALDERA_PORT="${CALDERA_PORT:-8888}"
CALDERA_AGENT_BASE_URL="${CALDERA_AGENT_BASE_URL:-http://10.10.10.1:${CALDERA_PORT}}"
API_KEY_FILE="${API_KEY_FILE:-/etc/xdr-lab/caldera-api-key}"
CALDERA_PLUGINS="${CALDERA_PLUGINS:-}"
CALDERA_GIT_URL="${CALDERA_GIT_URL:-https://github.com/mitre/caldera.git}"
SYSTEMD_UNIT="${SYSTEMD_UNIT:-caldera.service}"
CALDERA_SKIP_SYSTEMD="${CALDERA_SKIP_SYSTEMD:-0}"

usage() {
  sed -n '1,35p' "$0" | tail -n +2
}

log() { echo "[caldera-bootstrap] $*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) log "Unknown argument: $1"; usage; exit 2 ;;
  esac
  shift
done

if [[ "${DRY_RUN}" -ne 1 ]] && [[ "$(id -u)" -ne 0 ]]; then
  log "Run as root (sudo) for install. Use --dry-run for preflight without changes."
  exit 1
fi

if [[ "${DRY_RUN}" -eq 1 ]]; then
  log "DRY-RUN: no files, packages, or services will be modified."
  cat <<EOF
Planned configuration:
  CALDERA_HOME=${CALDERA_HOME}
  CALDERA_USER=${CALDERA_USER}
  CALDERA_LISTEN_HOST=${CALDERA_LISTEN_HOST}
  CALDERA_PORT=${CALDERA_PORT}
  CALDERA_AGENT_BASE_URL=${CALDERA_AGENT_BASE_URL}
  API_KEY_FILE=${API_KEY_FILE}
  CALDERA_PLUGINS=${CALDERA_PLUGINS:-<empty: sed-only patch>}
  CALDERA_GIT_URL=${CALDERA_GIT_URL}
  SYSTEMD_UNIT=${SYSTEMD_UNIT}
  CALDERA_SKIP_SYSTEMD=${CALDERA_SKIP_SYSTEMD}

Steps (when executed for real):
  1) apt: python3 venv pip dev git curl build-essential nodejs npm (+ python3-yaml if CALDERA_PLUGINS set)
  2) system user ${CALDERA_USER} and permissions on ${CALDERA_HOME}
  3) git clone --recursive ${CALDERA_GIT_URL}
  4) venv + pip install -r requirements.txt
  5) backup conf/default.yml then patch host/port/api_key_red/app.contact.http
     (sed if CALDERA_PLUGINS empty, else PyYAML full rewrite)
  6) if CALDERA_SKIP_SYSTEMD=0: write /etc/systemd/system/${SYSTEMD_UNIT} + systemctl enable --now
EOF
  exit 0
fi

if ! grep -q '^VERSION_ID="24.04"' /etc/os-release 2>/dev/null; then
  log "Warning: host is not Ubuntu 24.04. Package names and paths may differ."
fi

APT_PKGS=(python3 python3-venv python3-pip python3-dev git curl ca-certificates build-essential nodejs npm)
if [[ -n "${CALDERA_PLUGINS// /}" ]]; then
  APT_PKGS+=(python3-yaml)
fi

log "Installing packages: ${APT_PKGS[*]} …"
apt-get update -qq
env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${APT_PKGS[@]}"

if ! id -u "${CALDERA_USER}" >/dev/null 2>&1; then
  log "Creating system user: ${CALDERA_USER}"
  useradd --system --home-dir "${CALDERA_HOME}" --create-home --shell /bin/bash "${CALDERA_USER}"
fi

mkdir -p /etc/xdr-lab
chmod 0750 /etc/xdr-lab

if [[ ! -d "${CALDERA_HOME}/.git" ]]; then
  log "Cloning CALDERA: ${CALDERA_GIT_URL} → ${CALDERA_HOME}"
  mkdir -p "$(dirname "${CALDERA_HOME}")"
  git clone --recursive --depth 1 "${CALDERA_GIT_URL}" "${CALDERA_HOME}"
else
  log "Keeping existing repo: ${CALDERA_HOME} (updates: manual git pull recommended)"
fi

chown -R "${CALDERA_USER}:${CALDERA_USER}" "${CALDERA_HOME}"

VENV="${CALDERA_HOME}/.venv"
log "Python venv + requirements.txt …"
sudo -u "${CALDERA_USER}" python3 -m venv "${VENV}"
sudo -u "${CALDERA_USER}" "${VENV}/bin/pip" install -U pip setuptools wheel
sudo -u "${CALDERA_USER}" bash -lc "cd '${CALDERA_HOME}' && '${VENV}/bin/pip' install -r requirements.txt"

DEF_YML="${CALDERA_HOME}/conf/default.yml"
if [[ ! -f "${DEF_YML}" ]]; then
  log "Error: ${DEF_YML} missing — clone may have failed."
  exit 1
fi

if [[ -s "${API_KEY_FILE}" ]]; then
  KEY_PLACEHOLDER="$(tr -d '\n\r' <"${API_KEY_FILE}")"
  log "Using existing API key file: ${API_KEY_FILE}"
else
  KEY_PLACEHOLDER="$(openssl rand -hex 24)"
  install -m 0600 -o root -g root /dev/null "${API_KEY_FILE}" || true
  printf '%s' "${KEY_PLACEHOLDER}" >"${API_KEY_FILE}"
  chmod 0600 "${API_KEY_FILE}"
  log "Wrote new API key: ${API_KEY_FILE} (match caldera-lab.json / XDR_CALDERA_API_KEY)"
fi

DEF_BAK="${DEF_YML}.pre-xdr-lab-$(date -u +%Y%m%dT%H%M%SZ)"
cp -a "${DEF_YML}" "${DEF_BAK}"
log "Backup: ${DEF_BAK}"

sync_api_key_red_hash() {
  local util_py root
  root="${SCRIPT_DIR}/.."
  util_py="${root}/scripts/caldera_api_key_util.py"
  if [[ ! -f "${util_py}" ]]; then
    log "Error: missing ${util_py} — cannot hash api_key_red for CALDERA"
    exit 1
  fi
  local tmp_plain action
  tmp_plain="$(mktemp)"
  printf '%s' "${KEY_PLACEHOLDER}" >"${tmp_plain}"
  action="$("${VENV}/bin/python3" "${util_py}" sync --config "${DEF_YML}" --key-file "${API_KEY_FILE}" --plaintext "${tmp_plain}")"
  rm -f "${tmp_plain}"
  log "api_key_red sync via caldera_api_key_util: ${action}"
  chown "${CALDERA_USER}:${CALDERA_USER}" "${DEF_YML}"
}

if [[ -n "${CALDERA_PLUGINS// /}" ]]; then
  log "CALDERA_PLUGINS set — rewriting default.yml with PyYAML (comments may be lost)"
  PATCH_PY=$(cat <<'PY'
import sys
import yaml

path, host, port, agent_base_url, plugins_csv = sys.argv[1:6]
plugins = [p.strip() for p in plugins_csv.split(",") if p.strip()] if plugins_csv else None

with open(path, "r", encoding="utf-8") as f:
    data = yaml.safe_load(f)

data["host"] = host
data["port"] = int(port)
data["app.contact.http"] = agent_base_url
if plugins:
    data["plugins"] = plugins

with open(path, "w", encoding="utf-8") as f:
    yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
PY
  )
  sudo -u "${CALDERA_USER}" python3 -c "${PATCH_PY}" "${DEF_YML}" "${CALDERA_LISTEN_HOST}" "${CALDERA_PORT}" "${CALDERA_AGENT_BASE_URL}" "${CALDERA_PLUGINS}"
  sync_api_key_red_hash
else
  log "conf/default.yml — sed patch host/port/app.contact.http; api_key_red via caldera_api_key_util (argon2)"
  sed -i \
    -e "s/^host:.*/host: ${CALDERA_LISTEN_HOST}/" \
    -e "s/^port:.*/port: ${CALDERA_PORT}/" \
    -e "s|^app.contact.http:.*|app.contact.http: ${CALDERA_AGENT_BASE_URL}|" \
    "${DEF_YML}"
  sync_api_key_red_hash
fi

if [[ "${CALDERA_SKIP_SYSTEMD}" == "1" ]]; then
  log "CALDERA_SKIP_SYSTEMD=1 — not writing systemd unit. Manual start example:"
  log "  sudo -u ${CALDERA_USER} -H bash -lc 'cd ${CALDERA_HOME} && ${VENV}/bin/python3 server.py --insecure --build'"
  exit 0
fi

UNIT_PATH="/etc/systemd/system/${SYSTEMD_UNIT}"
log "Writing systemd unit: ${UNIT_PATH}"
if [[ -f "${SCRIPT_DIR}/../installer/caldera.service" ]]; then
  install -m 0644 "${SCRIPT_DIR}/../installer/caldera.service" "${UNIT_PATH}"
else
  SERVICE_BODY=$(cat <<EOF
[Unit]
Description=MITRE CALDERA (XDR Lab bootstrap)
After=network-online.target xdr-lab-host-network.service
Wants=network-online.target xdr-lab-host-network.service
ConditionPathExists=${CALDERA_HOME}/server.py

[Service]
Type=simple
User=${CALDERA_USER}
Group=${CALDERA_USER}
WorkingDirectory=${CALDERA_HOME}
Environment=PYTHONUNBUFFERED=1
ExecStart=${VENV}/bin/python3 ${CALDERA_HOME}/server.py --insecure --build
Restart=on-failure
RestartSec=5
TimeoutStartSec=900
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF
  )
  printf '%s\n' "${SERVICE_BODY}" >"${UNIT_PATH}"
fi
chmod 0644 "${UNIT_PATH}"
systemctl daemon-reload
if ! systemctl enable "${SYSTEMD_UNIT}"; then
  log "Error: systemctl enable ${SYSTEMD_UNIT} failed"
  exit 1
fi
log "Starting service: systemctl start ${SYSTEMD_UNIT}"
if ! systemctl restart "${SYSTEMD_UNIT}" && ! systemctl start "${SYSTEMD_UNIT}"; then
  log "Error: systemctl start ${SYSTEMD_UNIT} failed — journalctl -u ${SYSTEMD_UNIT}"
  exit 1
fi

log "Done."
log "Status: systemctl status ${SYSTEMD_UNIT} --no-pager"
log "UI/REST: http://${CALDERA_LISTEN_HOST}:${CALDERA_PORT}/"
log "API key file: ${API_KEY_FILE}  →  XDR Lab api_key_file or export XDR_CALDERA_API_KEY"
