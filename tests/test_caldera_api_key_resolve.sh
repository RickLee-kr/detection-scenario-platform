#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESOLVER="${ROOT}/scripts/caldera_api_key_resolve.py"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

mkdir -p "${TMP}/runtime" "${TMP}/config"
printf '%s' 'test-runtime-key-abc' >"${TMP}/runtime/caldera-api-key"
chmod 0644 "${TMP}/runtime/caldera-api-key"
cat >"${TMP}/config/caldera-lab.json" <<'JSON'
{"api_key_file": "/etc/xdr-lab/caldera-api-key", "api_key_env": "XDR_CALDERA_API_KEY"}
JSON

key="$(python3 "${RESOLVER}" --xdr-root "${TMP}" --config "${TMP}/config/caldera-lab.json")"
[[ "${key}" == "test-runtime-key-abc" ]] || {
  echo "FAIL: expected runtime key, got: ${key}" >&2
  exit 1
}

unset XDR_CALDERA_API_KEY
if key="$(python3 "${RESOLVER}" --xdr-root "${TMP}" --config "${TMP}/config/caldera-lab.json" 2>/dev/null)"; then
  [[ "${key}" == "test-runtime-key-abc" ]] || {
    echo "FAIL: expected runtime fallback key, got: ${key}" >&2
    exit 1
  }
  :
else
  echo "FAIL: resolver should read runtime copy when /etc is unreadable" >&2
  exit 1
fi

PYTHONPATH="${ROOT}/scripts" python3 - <<'PY'
from caldera_api_key_resolve import read_key_file_if_readable


class PermissionDeniedPath:
    def __init__(self, fail_at):
        self.fail_at = fail_at

    def exists(self):
        if self.fail_at == "exists":
            raise PermissionError("exists denied")
        return True

    def is_file(self):
        if self.fail_at == "is_file":
            raise PermissionError("is_file denied")
        return True

    def stat(self):
        if self.fail_at == "stat":
            raise PermissionError("stat denied")

        class Stat:
            st_size = 1

        return Stat()

    def open(self, mode):
        if self.fail_at == "open":
            raise PermissionError("open denied")
        raise AssertionError("unexpected open")


for method in ("exists", "is_file", "stat", "open"):
    assert read_key_file_if_readable(PermissionDeniedPath(method)) is None, method
PY

echo "PASS: caldera_api_key_resolve runtime fallback"
