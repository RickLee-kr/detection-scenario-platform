#!/usr/bin/env bash
# Tests for caldera_api_key_util.py (no live CALDERA).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UTIL="${ROOT}/scripts/caldera_api_key_util.py"
PY="${CALDERA_PYTHON:-python3}"
if [[ -x /opt/caldera/.venv/bin/python3 ]]; then
  PY="/opt/caldera/.venv/bin/python3"
fi
PASS=0
FAIL=0

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [[ "${actual}" == "${expected}" ]]; then
    echo "PASS ${label}"
    PASS=$((PASS + 1))
  else
    echo "FAIL ${label} expected=${expected} actual=${actual}" >&2
    FAIL=$((FAIL + 1))
  fi
}

tmp="$(mktemp -d)"
cfg="${tmp}/default.yml"
kf="${tmp}/caldera-api-key"
cat >"${cfg}" <<'YML'
api_key_red: plaintext-test-key
host: 127.0.0.1
port: 8888
YML

out="$("${PY}" "${UTIL}" sync --config "${cfg}" --key-file "${kf}" 2>&1)"
assert_eq "sync plaintext config" "synced" "${out}"
assert_eq "key file written" "plaintext-test-key" "$(tr -d '\n\r' <"${kf}")"

"${PY}" "${UTIL}" verify --config "${cfg}" --plaintext "${kf}" | grep -q '^ok$' && {
  echo "PASS verify matches"
  PASS=$((PASS + 1))
} || {
  echo "FAIL verify matches" >&2
  FAIL=$((FAIL + 1))
}

rot="$("${PY}" "${UTIL}" sync --config "${cfg}" --key-file "${kf}" --generate 2>&1)"
assert_eq "rotate returns rotated" "rotated" "${rot}"
grep -q 'argon2id' "${cfg}" && {
  echo "PASS config hashed"
  PASS=$((PASS + 1))
} || {
  echo "FAIL config hashed" >&2
  FAIL=$((FAIL + 1))
}

grep -E "api_key_red:[[:space:]]*'" "${cfg}" && {
  echo "PASS api_key_red single-quoted after rotate"
  PASS=$((PASS + 1))
} || {
  echo "FAIL api_key_red not single-quoted after rotate" >&2
  FAIL=$((FAIL + 1))
}

"${PY}" "${UTIL}" verify --config "${cfg}" --plaintext "${kf}" | grep -q '^ok$' && {
  echo "PASS verify after rotate (on-disk)"
  PASS=$((PASS + 1))
} || {
  echo "FAIL verify after rotate (on-disk)" >&2
  FAIL=$((FAIL + 1))
}

if ROOT="${ROOT}" PY="${PY}" python3 <<'PY'
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.environ["ROOT"], "scripts"))
from caldera_key_crypto import (
    dump_config,
    hash_fields_single_quoted_in_text,
    hash_plaintext_key,
    load_config,
    verify_api_key_red_on_disk,
)

plus_hash = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdCtkZW1v$c2FsdCtkZW1vK2FiYw+ZGVm"
tmp = Path(tempfile.mkdtemp())
cfg = tmp / "default.yml"
data = {"api_key_red": plus_hash, "api_key_blue": plus_hash, "port": 8888}
dump_config(cfg, data)
text = cfg.read_text(encoding="utf-8")
assert hash_fields_single_quoted_in_text(text), text
assert "api_key_red: '" in text and "api_key_blue: '" in text, text
reloaded = load_config(cfg)
assert reloaded["api_key_red"] == plus_hash, reloaded["api_key_red"]
assert "+" in str(reloaded["api_key_blue"]), reloaded["api_key_blue"]

plain = "plus-roundtrip-key"
try:
    real_hash = hash_plaintext_key(plain)
except RuntimeError:
    print("python_plus_ok")
    raise SystemExit(0)
data["api_key_red"] = real_hash
dump_config(cfg, data)
assert hash_fields_single_quoted_in_text(cfg.read_text(encoding="utf-8"))
assert verify_api_key_red_on_disk(cfg, plain), "key_matches_api_key_red after hash dump"
print("python_plus_ok")
PY
then
  echo "PASS argon2 plus hash YAML round-trip"
  PASS=$((PASS + 1))
else
  echo "FAIL argon2 plus hash YAML round-trip" >&2
  FAIL=$((FAIL + 1))
fi

rm -rf "${tmp}"
echo "--- passed=${PASS} failed=${FAIL}"
[[ "${FAIL}" -eq 0 ]]
