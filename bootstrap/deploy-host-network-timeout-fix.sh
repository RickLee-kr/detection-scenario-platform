#!/usr/bin/env bash
# One-shot deploy for host-network hang fixes (bootstrap + systemd unit).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
XDR_ROOT="${XDR_ROOT:-/opt/xdr-lab}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 2
fi

for f in \
  _runtime-validation-lib.sh \
  ensure-host-network.sh \
  ensure-nat-contract.sh \
  validate-host-network.sh; do
  install -m 0755 "${ROOT}/bootstrap/${f}" "${XDR_ROOT}/bootstrap/${f}"
done
install -m 0755 "${ROOT}/scripts/nat_state.py" "${XDR_ROOT}/scripts/nat_state.py"
install -m 0644 "${ROOT}/installer/xdr-lab-host-network.service" \
  /etc/systemd/system/xdr-lab-host-network.service

systemctl daemon-reload
systemctl stop xdr-lab-host-network.service 2>/dev/null || true
systemctl reset-failed xdr-lab-host-network.service 2>/dev/null || true
systemctl restart xdr-lab-host-network.service
systemctl status xdr-lab-host-network.service --no-pager
"${XDR_ROOT}/bootstrap/validate-host-network.sh"
echo "validate_exit=$?"
