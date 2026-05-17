#!/usr/bin/env bash
# Unit tests for CALDERA stale process classification (mocked /proc where needed).
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
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.environ["ROOT"], "scripts"))
from caldera_process_util import (
    grace_active,
    is_descendant_of,
    proc_cgroup_key,
    record_restart_grace,
    same_systemd_cgroup,
)

tmp = tempfile.mkdtemp()
grace_file = Path("/run/xdr-lab/caldera-stale-grace-until")
# use temp grace path by patching
import caldera_process_util as mod

orig = mod.GRACE_UNTIL_PATH
mod.GRACE_UNTIL_PATH = Path(tmp) / "grace-until"
mod.record_restart_grace(60)
assert mod.grace_active(90), "grace should be active after record"
mod.GRACE_UNTIL_PATH = orig

# /proc may exist on Linux test host
if Path("/proc/self/stat").is_file():
    self_pid = os.getpid()
    ppid = os.getppid()
    assert is_descendant_of(self_pid, ppid) or self_pid == ppid
    cg = proc_cgroup_key(self_pid)
    assert isinstance(cg, str)
    if ppid > 1:
        assert same_systemd_cgroup(self_pid, ppid) or cg

print("python_ok")
PY
then
  echo "PASS python caldera_process_util"
  PASS=$((PASS + 1))
else
  echo "FAIL python caldera_process_util" >&2
  FAIL=$((FAIL + 1))
fi

# shellcheck source=../bootstrap/_runtime-validation-lib.sh
# shellcheck disable=SC1091
. "${ROOT}/bootstrap/_runtime-validation-lib.sh"

if rv_caldera_journal_all_systems_ready $'line\nAll systems ready\n'; then
  echo "PASS journal all systems ready"
  PASS=$((PASS + 1))
else
  echo "FAIL journal all systems ready" >&2
  FAIL=$((FAIL + 1))
fi

if ! rv_caldera_journal_all_systems_ready $'still building\n'; then
  echo "PASS journal not ready"
  PASS=$((PASS + 1))
else
  echo "FAIL journal not ready" >&2
  FAIL=$((FAIL + 1))
fi

echo "---"
echo "passed=${PASS} failed=${FAIL}"
[[ "${FAIL}" -eq 0 ]]
