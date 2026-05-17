#!/usr/bin/env bash
# Copy /etc/xdr-lab/caldera-api-key → ${XDR_ROOT}/runtime/caldera-api-key (group-readable).
# Requires root to read the canonical key file.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XDR_ROOT="${XDR_ROOT:-/opt/xdr-lab}"
RESOLVER="${SCRIPT_DIR}/../scripts/caldera_api_key_resolve.py"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi

exec python3 "${RESOLVER}" --sync-runtime --xdr-root "${XDR_ROOT}" --group xdr-lab
