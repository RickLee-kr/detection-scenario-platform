#!/usr/bin/env bash
# Tests for caldera_key_crypto.py + post-rotate diag match (no live CALDERA).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${CALDERA_PYTHON:-python3}"
if [[ -x /opt/caldera/.venv/bin/python3 ]]; then
  PY="/opt/caldera/.venv/bin/python3"
fi
export PYTHONPATH="${ROOT}/scripts${PYTHONPATH:+:${PYTHONPATH}}"
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
unit="${tmp}/caldera.service"
home="${tmp}/caldera"
mkdir -p "${home}/conf"
cp "${cfg}" "${home}/conf/default.yml" 2>/dev/null || true

cat >"${cfg}" <<'YML'
api_key_red: plaintext-test-key
host: 127.0.0.1
port: 8888
YML
cp "${cfg}" "${home}/conf/default.yml"
printf '%s\n' '[Service]' "ExecStart=${PY} ${home}/server.py --insecure --build" >"${unit}"

UTIL="${ROOT}/scripts/caldera_api_key_util.py"
DIAG="${ROOT}/scripts/caldera_config_diag.py"

rot="$("${PY}" "${UTIL}" sync --config "${cfg}" --key-file "${kf}" --generate 2>&1)"
assert_eq "rotate returns rotated" "rotated" "${rot}"

grep -q "'" "${cfg}" && grep 'api_key_red' "${cfg}" | grep -q "'" && {
  echo "PASS api_key_red quoted in yaml"
  PASS=$((PASS + 1))
} || {
  echo "FAIL api_key_red not single-quoted" >&2
  FAIL=$((FAIL + 1))
}

diag_out="$("${PY}" "${DIAG}" --caldera-home "${home}" --unit-path "${unit}" --config "${cfg}" --key-file "${kf}" --require-key-match 2>&1)" && {
  echo "PASS diag require-key-match after rotate"
  PASS=$((PASS + 1))
} || {
  echo "FAIL diag require-key-match: ${diag_out}" >&2
  FAIL=$((FAIL + 1))
}

# key with embedded newline must match hash of normalized key
printf 'line-key\n' >"${kf}"
"${PY}" "${UTIL}" sync --config "${cfg}" --key-file "${kf}" >/dev/null
printf 'line-key' >"${kf}"
"${PY}" "${DIAG}" --config "${cfg}" --key-file "${kf}" --require-key-match >/dev/null && {
  echo "PASS newline-normalized key verifies"
  PASS=$((PASS + 1))
} || {
  echo "FAIL newline-normalized key verifies" >&2
  FAIL=$((FAIL + 1))
}

if ROOT="${ROOT}" PY="${PY}" python3 <<'PY'
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.environ["ROOT"], "scripts"))
from caldera_key_crypto import dump_config, hash_fields_single_quoted_in_text, load_config

plus_hash = "$argon2id$v=19$m=65536,t=3,p=4$x+$alt$xK2FiYw+ZGVm"
cfg = Path(tempfile.mkdtemp()) / "default.yml"
dump_config(cfg, {"api_key_red": plus_hash, "port": 1})
text = cfg.read_text(encoding="utf-8")
assert hash_fields_single_quoted_in_text(text), text
assert load_config(cfg)["api_key_red"] == plus_hash
print("plus_yaml_ok")
PY
then
  echo "PASS argon2 plus preserved in YAML load"
  PASS=$((PASS + 1))
else
  echo "FAIL argon2 plus preserved in YAML load" >&2
  FAIL=$((FAIL + 1))
fi

rm -rf "${tmp}"
echo "--- passed=${PASS} failed=${FAIL}"
[[ "${FAIL}" -eq 0 ]]
