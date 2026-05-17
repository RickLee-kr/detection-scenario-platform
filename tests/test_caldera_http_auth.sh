#!/usr/bin/env bash
# Unit tests for CALDERA HTTP auth classification (no live CALDERA).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

if ROOT="${ROOT}" python3 <<'PY'
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.environ["ROOT"], "scripts"))
import caldera_orchestration as mod

assert mod.classify_caldera_http_error(
    302, "", location="/login", content_type=None, final_url=None, api_key=""
) == "auth_required"
assert mod.classify_caldera_http_error(
    200,
    "<html><body>login</body></html>",
    location=None,
    content_type="text/html",
    final_url="http://127.0.0.1:8888/login",
    api_key="",
    parse_error="json_decode_error",
) == "auth_required"
assert mod.classify_caldera_http_error(
    200,
    "not json",
    location=None,
    content_type="text/plain",
    final_url=None,
    api_key="secret",
    parse_error="json_decode_error",
) == "json_decode_error"

import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as td:
    kf = Path(td) / "caldera-api-key"
    kf.write_text("file-key-abc", encoding="utf-8")
    runtime = Path(td) / "runtime"
    runtime.mkdir()
    (runtime / "caldera-api-key").write_text("runtime-key-abc", encoding="utf-8")
    os.environ["XDR_CALDERA_API_KEY"] = "stale-env-key"
    try:
        cfg = {"api_key_file": str(kf)}
        assert mod.resolve_api_key(cfg, warn_stale_env=False) == "file-key-abc"
        os.environ.pop("XDR_CALDERA_API_KEY", None)
        assert mod.resolve_api_key(cfg) == "file-key-abc"
        cfg_missing = {"api_key_file": str(kf / "missing"), "_xdr_root": td}
        assert mod.resolve_api_key(cfg_missing) == "runtime-key-abc"
    finally:
        os.environ.pop("XDR_CALDERA_API_KEY", None)


class RedirectLoginHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/agents":
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        return


srv = HTTPServer(("127.0.0.1", 0), RedirectLoginHandler)
port = srv.server_address[1]
thread = threading.Thread(target=srv.serve_forever, daemon=True)
thread.start()
base = f"http://127.0.0.1:{port}"
client = mod.CalderaClient(base, "")
code, data, err = client.get_index("agents", None)
assert code == 302, (code, data, err)
assert err == "auth_required", err
assert client.last_location == "/login"
srv.shutdown()
print("python_ok")
PY
then
  echo "PASS python auth classification"
  PASS=$((PASS + 1))
else
  echo "FAIL python auth classification" >&2
  FAIL=$((FAIL + 1))
fi

test_meta_parser() {
  local tmp out hdr code loc ct mock_curl
  tmp="$(mktemp -d)"
  mkdir -p "${tmp}/bin"
  mock_curl="${tmp}/bin/curl"
  cat >"${mock_curl}" <<'MOCK'
#!/bin/bash
if [[ " $* " == *" -H KEY:"* ]]; then
  printf 'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n'
else
  printf 'HTTP/1.1 302 Found\r\nLocation: /login\r\nContent-Type: text/html\r\n\r\n'
fi
exit 0
MOCK
  chmod +x "${mock_curl}"
  # shellcheck source=../bootstrap/_runtime-validation-lib.sh
  # shellcheck disable=SC1091
  . "${ROOT}/bootstrap/_runtime-validation-lib.sh"
  out="$(PATH="${tmp}/bin:${PATH}" rv_caldera_agents_http_meta "http://127.0.0.1:8888")"
  IFS=$'\t' read -r code loc ct <<<"${out}"
  assert_eq "meta unauthenticated code" "302" "${code}"
  assert_eq "meta unauthenticated location" "/login" "${loc}"
  out="$(PATH="${tmp}/bin:${PATH}" rv_caldera_auth_probe "http://127.0.0.1:8888" "test")"
  IFS=$'\t' read -r hdr code loc ct <<<"${out}"
  assert_eq "auth probe header" "KEY" "${hdr}"
  assert_eq "auth probe authenticated code" "200" "${code}"
  rm -rf "${tmp}"
}

test_meta_parser

echo "---"
echo "passed=${PASS} failed=${FAIL}"
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
exit 0
