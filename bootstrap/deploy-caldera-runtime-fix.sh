#!/usr/bin/env bash
# One-shot deploy for CALDERA runtime persistence fixes.
#
# Usage:
#   sudo ./bootstrap/deploy-caldera-runtime-fix.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
XDR_ROOT="${XDR_ROOT:-/opt/xdr-lab}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 2
fi

mkdir -p "${XDR_ROOT}/bootstrap" "${XDR_ROOT}/scripts"

install -m 0755 "${ROOT}/scripts/caldera_key_crypto.py" "${XDR_ROOT}/scripts/caldera_key_crypto.py"
install -m 0755 "${ROOT}/scripts/caldera_api_key_util.py" "${XDR_ROOT}/scripts/caldera_api_key_util.py"
install -m 0755 "${ROOT}/scripts/caldera_config_diag.py" "${XDR_ROOT}/scripts/caldera_config_diag.py"
install -m 0755 "${ROOT}/scripts/caldera_runtime_auth_diag.py" "${XDR_ROOT}/scripts/caldera_runtime_auth_diag.py"
install -m 0755 "${ROOT}/scripts/patch_caldera_auth_debug.py" "${XDR_ROOT}/scripts/patch_caldera_auth_debug.py"
install -m 0644 "${ROOT}/patches/caldera/xdr_auth_debug.py" "${XDR_ROOT}/patches/caldera/xdr_auth_debug.py"

for f in \
  _runtime-validation-lib.sh \
  ensure-caldera-runtime.sh \
  ensure-caldera-api-key.sh \
  repair-caldera-service.sh \
  validate-caldera.sh \
  validate-appliance.sh; do
  install -m 0755 "${ROOT}/bootstrap/${f}" "${XDR_ROOT}/bootstrap/${f}"
done

echo "=== ensure-caldera-runtime ==="
set +e
"${XDR_ROOT}/bootstrap/ensure-caldera-runtime.sh" --apt-repair
ensure_rc=$?
set -e
echo "ensure_exit=${ensure_rc}"
if [[ "${ensure_rc}" -ne 0 ]]; then
  echo "ensure-caldera-runtime failed (exit ${ensure_rc}) — fix above then re-run" >&2
  exit "${ensure_rc}"
fi

echo "=== ensure-caldera-api-key ==="
set +e
"${XDR_ROOT}/bootstrap/ensure-caldera-api-key.sh"
apikey_rc=$?
set -e
echo "ensure_api_key_exit=${apikey_rc}"
if [[ "${apikey_rc}" -ne 0 ]]; then
  echo "ensure-caldera-api-key failed (exit ${apikey_rc}) — fix CALDERA auth before scenario list" >&2
  exit "${apikey_rc}"
fi

echo "=== repair-caldera-service --start ==="
set +e
"${XDR_ROOT}/bootstrap/repair-caldera-service.sh" --start
repair_rc=$?
set -e
echo "repair_exit=${repair_rc}"
if [[ "${repair_rc}" -ne 0 ]]; then
  echo "repair-caldera-service failed (exit ${repair_rc})" >&2
  exit "${repair_rc}"
fi

echo "=== validate-caldera ==="
set +e
"${XDR_ROOT}/bootstrap/validate-caldera.sh"
validate_rc=$?
set -e
echo "validate_exit=${validate_rc}"

echo ""
echo "=== next steps ==="
echo "  systemctl status caldera.service --no-pager"
echo "  journalctl -u caldera.service -n 80 --no-pager"
echo "  ${XDR_ROOT}/bootstrap/validate-appliance.sh"
echo "  ${XDR_ROOT}/bootstrap/validate-caldera.sh --json"

exit "${validate_rc}"
