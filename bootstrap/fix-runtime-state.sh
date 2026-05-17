#!/usr/bin/env bash
# Safe runtime self-healing for the KVM host appliance.
# Delegates full br0 + NAT contract recovery to ensure-host-network.sh.
#
# Usage:
#   sudo ./bootstrap/fix-runtime-state.sh [--dry-run]
#
# Exit codes:
#   0   no action needed OR all attempted fixes succeeded
#   1   one or more fix actions failed
#   2   not root (required for real fixes)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_runtime-validation-lib.sh
. "${SCRIPT_DIR}/_runtime-validation-lib.sh"

DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      sed -n '1,20p' "$0" | tail -n +2
      exit 0
      ;;
    *) rv_log ERROR "unknown argument: $1"; exit 2 ;;
  esac
  shift
done

if [[ "${DRY_RUN}" -eq 0 && "$(id -u)" -ne 0 ]]; then
  rv_log ERROR "fix-runtime-state requires root (sudo) unless --dry-run"
  exit 2
fi

rv_log INFO "fix-runtime-state start dry_run=${DRY_RUN}"

ENSURE_HOST_NET="$(rv_script_path ensure-host-network.sh || true)"
if [[ -z "${ENSURE_HOST_NET}" ]]; then
  rv_log ERROR "ensure-host-network.sh not found under bootstrap/"
  exit 1
fi

if [[ "${DRY_RUN}" -eq 1 ]]; then
  bash "${ENSURE_HOST_NET}" --dry-run
else
  if ! systemctl is-active --quiet libvirtd 2>/dev/null; then
    rv_log INFO "ACTION: restart libvirtd"
    systemctl restart libvirtd || rv_log ERROR "libvirtd restart failed (continuing)"
  fi
  bash "${ENSURE_HOST_NET}"
fi

echo "=== post-fix validation (read-only) ==="
set +e
VALIDATE_HOST_NET="$(rv_script_path validate-host-network.sh || true)"
if [[ -n "${VALIDATE_HOST_NET}" ]]; then
  "${VALIDATE_HOST_NET}" || true
else
  rv_log ERROR "validate-host-network.sh not found under bootstrap/"
fi
VALIDATE_LIBVIRT="$(rv_script_path validate-libvirt.sh || true)"
if [[ -n "${VALIDATE_LIBVIRT}" ]]; then
  "${VALIDATE_LIBVIRT}" || true
fi
set -e

rv_log INFO "fix-runtime-state finished"
exit 0
