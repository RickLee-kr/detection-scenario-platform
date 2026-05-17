#!/usr/bin/env bash
# Tests for caldera_config_diag.py (no live CALDERA).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${CALDERA_PYTHON:-python3}"
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
home="${tmp}/caldera"
mkdir -p "${home}/conf"
cat >"${home}/conf/default.yml" <<'YML'
api_key_red: plaintext-red
host: 127.0.0.1
port: 8888
YML
unit="${tmp}/caldera.service"
printf '%s\n' '[Service]' "ExecStart=${home}/.venv/bin/python3 ${home}/server.py --insecure --build" >"${unit}"

export PYTHONPATH="${ROOT}/scripts${PYTHONPATH:+:${PYTHONPATH}}"
keyf="${tmp}/key"
printf 'plaintext-red' >"${keyf}"
out="$("${PY}" "${ROOT}/scripts/caldera_config_diag.py" \
  --caldera-home "${home}" \
  --unit-path "${unit}" \
  --config "${home}/conf/default.yml" \
  --key-file "${keyf}" \
  --format shell 2>/dev/null)"
assert_eq "environment default" "default" "$(grep '^environment=' <<<"${out}" | cut -d= -f2)"
assert_eq "main config path" "${home}/conf/default.yml" "$(grep '^main_config_path=' <<<"${out}" | cut -d= -f2)"
match="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("matches_api_key_red"))' <<<"$(grep '^key_verify=' <<<"${out}" | cut -d= -f2-)")"
assert_eq "plaintext key matches" "True" "${match}"

rm -rf "${tmp}"
echo "--- passed=${PASS} failed=${FAIL}"
[[ "${FAIL}" -eq 0 ]]
