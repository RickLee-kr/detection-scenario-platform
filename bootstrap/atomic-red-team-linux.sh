#!/usr/bin/env bash
# XDR Lab — Atomic Red Team preparation for Linux (victim-linux role).
#
# - git clone of atomics YAML / docs repository
# - (optional) PowerShell Core + Invoke-AtomicRedTeam module for some -WhatIf / review flows
# - default is "no execution": Invoke-AtomicTest is never invoked automatically
#
# Usage:
#   sudo ATOMIC_INSTALL_PATH=/opt/atomic-red-team ./bootstrap/atomic-red-team-linux.sh
#   ./bootstrap/atomic-red-team-linux.sh --dry-run
#   sudo WITH_PWSH=1 ./bootstrap/atomic-red-team-linux.sh --with-pwsh
#
# In most labs, abilities run through CALDERA stockpile/atomic plugins; the ART repo is
# optional reference material for custom abilities.
#
set -euo pipefail

DRY_RUN=0
WITH_PWSH="${WITH_PWSH:-0}"
ATOMIC_INSTALL_PATH="${ATOMIC_INSTALL_PATH:-/opt/atomic-red-team}"
ATOMIC_GIT_URL="${ATOMIC_GIT_URL:-https://github.com/redcanaryco/atomic-red-team.git}"

usage() {
  sed -n '1,20p' "$0" | tail -n +2
}

log() { echo "[atomic-linux] $*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --with-pwsh) WITH_PWSH=1 ;;
    -h|--help) usage; exit 0 ;;
    *) log "Unknown argument: $1"; usage; exit 2 ;;
  esac
  shift
done

if [[ "${DRY_RUN}" -eq 1 ]]; then
  log "DRY-RUN: no disk or package changes."
  cat <<EOF
Planned configuration:
  ATOMIC_INSTALL_PATH=${ATOMIC_INSTALL_PATH}
  ATOMIC_GIT_URL=${ATOMIC_GIT_URL}
  WITH_PWSH=${WITH_PWSH}

Steps (when executed for real, as root):
  1) apt: git curl ca-certificates jq
  2) git clone --depth 1 → \${ATOMIC_INSTALL_PATH}
  3) XDR-LAB-ATOMIC-SAFE.md + timestamp marker
  4) (optional --with-pwsh) Microsoft package repo + powershell + Install-Module invoke-atomicredteam
  5) /etc/profile.d/xdr-atomic-red-team.sh (ATOMIC_RED_TEAM_PATH)
EOF
  exit 0
fi

if [[ "$(id -u)" -ne 0 ]]; then
  log "sudo is required for system paths. For a user-only clone, run git clone manually."
  exit 1
fi

log "Packages: git, curl, ca-certificates, jq …"
apt-get update -qq
env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git curl ca-certificates jq

mkdir -p "$(dirname "${ATOMIC_INSTALL_PATH}")"

if [[ ! -d "${ATOMIC_INSTALL_PATH}/.git" ]]; then
  log "git clone → ${ATOMIC_INSTALL_PATH}"
  git clone --depth 1 "${ATOMIC_GIT_URL}" "${ATOMIC_INSTALL_PATH}"
else
  log "Already cloned: ${ATOMIC_INSTALL_PATH}"
fi

SAFE_README="${ATOMIC_INSTALL_PATH}/XDR-LAB-ATOMIC-SAFE.md"
MARKER="${ATOMIC_INSTALL_PATH}/.xdr-lab-atomic-safe-defaults"
cat >"${SAFE_README}" <<'MD'
# XDR Lab — Atomic Red Team safe defaults

- This bootstrap does **not** provide an auto-execution harness. Before running any atomics,
  take a **VM snapshot** and confirm lab isolation (`docs/caldera-integration.md` §7).
- When using PowerShell `Invoke-AtomicTest` on Linux, prefer `-WhatIf` (where supported) or
  tightly scoped `-TestNumbers` for pre-reviewed technique IDs only.
- Destructive, privilege-escalation, and credential-theft techniques are **out of scope** for
  default lab activation lists.

Recommended workflow: run abilities through CALDERA operations with scenario pack `adversary_id`
configured; use ART as reference or custom-ability source only.
MD
echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") bootstrap/atomic-red-team-linux.sh" >"${MARKER}"

if [[ "${WITH_PWSH}" -eq 1 ]]; then
  log "Installing PowerShell Core (packages.microsoft.com) …"
  apt-get install -y -qq wget apt-transport-https software-properties-common
  wget -qO /tmp/packages-microsoft-prod.deb https://packages.microsoft.com/config/ubuntu/24.04/packages-microsoft-prod.deb
  dpkg -i /tmp/packages-microsoft-prod.deb
  apt-get update -qq
  apt-get install -y -qq powershell
  log "Installing Invoke-AtomicRedTeam module …"
  INSTALL_PS='Set-PSRepository PSGallery -InstallationPolicy Trusted; Install-Module -Name invoke-atomicredteam -Scope AllUsers -Force -AllowClobber'
  pwsh -NoLogo -NonInteractive -Command "${INSTALL_PS}" || log "Warning: if module install fails, check proxy and gallery policy."
fi

ENV_SNIPPET="/etc/profile.d/xdr-atomic-red-team.sh"
cat >"${ENV_SNIPPET}" <<EOF
# XDR Lab — Atomic Red Team path (bootstrap/atomic-red-team-linux.sh)
export ATOMIC_RED_TEAM_PATH="${ATOMIC_INSTALL_PATH}"
EOF
chmod 0644 "${ENV_SNIPPET}"

log "Done. ATOMIC_RED_TEAM_PATH=${ATOMIC_INSTALL_PATH}"
log "See: ${SAFE_README}"
if [[ "${WITH_PWSH}" -ne 1 ]]; then
  log "Hint: sudo WITH_PWSH=1 $0 --with-pwsh  →  optional pwsh + Invoke-AtomicRedTeam"
fi
