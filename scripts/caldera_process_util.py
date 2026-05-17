#!/usr/bin/env python3
"""CALDERA server.py process classification (systemd cgroup, parent chain, stale detection)."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_HOME = Path("/opt/caldera")
DEFAULT_GRACE_SECS = 90
DEFAULT_MIN_ORPHAN_AGE_SECS = 300
GRACE_UNTIL_PATH = Path("/run/xdr-lab/caldera-stale-grace-until")


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def systemd_field(field: str, unit: str = "caldera.service") -> str:
    return _run(["systemctl", "show", unit, f"-p{field}", "--value"])


def systemd_main_pid(unit: str = "caldera.service") -> int | None:
    raw = systemd_field("MainPID", unit)
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return None


def systemd_active_enter_epoch(unit: str = "caldera.service") -> float | None:
    raw = systemd_field("ActiveEnterTimestamp", unit)
    if not raw or raw == "n/a":
        return None
    for fmt in (
        "%a %Y-%m-%d %H:%M:%S %Z",
        "%Y-%m-%d %H:%M:%S UTC",
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    return None


def record_restart_grace(grace_secs: int = DEFAULT_GRACE_SECS) -> int:
    until = int(time.time()) + grace_secs
    GRACE_UNTIL_PATH.parent.mkdir(parents=True, exist_ok=True)
    GRACE_UNTIL_PATH.write_text(f"{until}\n", encoding="utf-8")
    return until


def grace_active(grace_secs: int = DEFAULT_GRACE_SECS) -> bool:
    now = time.time()
    if GRACE_UNTIL_PATH.is_file():
        try:
            until = int(GRACE_UNTIL_PATH.read_text(encoding="utf-8").strip())
            if now < until:
                return True
        except ValueError:
            pass
    entered = systemd_active_enter_epoch()
    if entered is not None and (now - entered) < grace_secs:
        return True
    return False


def proc_ppid(pid: int) -> int | None:
    stat = Path(f"/proc/{pid}/stat")
    if not stat.is_file():
        return None
    # pid (comm) state ppid ...
    m = re.match(r"\d+ \([^)]*\) \S (\d+)", stat.read_text(encoding="utf-8", errors="replace"))
    if not m:
        return None
    ppid = int(m.group(1))
    return ppid if ppid > 0 else None


def proc_start_epoch(pid: int) -> float | None:
    stat = Path(f"/proc/{pid}/stat")
    if not stat.is_file():
        return None
    boot = Path("/proc/stat")
    if not boot.is_file():
        return None
    boot_line = boot.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    m = re.search(r"btime\s+(\d+)", boot_line)
    if not m:
        return None
    btime = int(m.group(1))
    fields = stat.read_text(encoding="utf-8", errors="replace").split()
    if len(fields) < 22:
        return None
    try:
        start_ticks = int(fields[21])
    except ValueError:
        return None
    clk = os_clock_ticks()
    if clk <= 0:
        return None
    return btime + (start_ticks / clk)


def os_clock_ticks() -> int:
    try:
        return int(_run(["getconf", "CLK_TCK"]) or "100")
    except ValueError:
        return 100


def proc_cgroup_key(pid: int) -> str:
    cg = Path(f"/proc/{pid}/cgroup")
    if not cg.is_file():
        return ""
    lines = [ln.strip() for ln in cg.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    if not lines:
        return ""
    # cgroup v2: 0::/system.slice/caldera.service/...
    last = lines[-1]
    if ":" in last:
        return last.split(":", 2)[-1]
    return last


def is_descendant_of(pid: int, ancestor: int, *, max_depth: int = 32) -> bool:
    if pid <= 0 or ancestor <= 0:
        return False
    if pid == ancestor:
        return True
    cur = pid
    for _ in range(max_depth):
        if cur == ancestor:
            return True
        ppid = proc_ppid(cur)
        if ppid is None or ppid <= 1:
            return False
        cur = ppid
    return False


def same_systemd_cgroup(a: int, b: int) -> bool:
    ca, cb = proc_cgroup_key(a), proc_cgroup_key(b)
    if not ca or not cb:
        return False
    if ca == cb:
        return True
    # Same service slice prefix (caldera.service scope).
    for needle in ("/caldera.service", ".service/"):
        if needle in ca and needle in cb:
            prefix_a = ca.split(needle)[0] + needle.rstrip("/")
            prefix_b = cb.split(needle)[0] + needle.rstrip("/")
            if prefix_a == prefix_b:
                return True
    return False


def list_server_processes(caldera_home: Path) -> list[dict[str, object]]:
    home = str(caldera_home.resolve())
    pattern = f"{home}/.*server\\.py"
    out = _run(["pgrep", "-af", pattern]) or _run(["pgrep", "-af", "server.py"])
    rows: list[dict[str, object]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or "server.py" not in line:
            continue
        pid_s, _, cmd = line.partition(" ")
        if not pid_s.isdigit():
            continue
        pid = int(pid_s)
        if home not in cmd:
            continue
        start = proc_start_epoch(pid)
        rows.append(
            {
                "pid": pid,
                "cmd": cmd,
                "ppid": proc_ppid(pid),
                "cgroup": proc_cgroup_key(pid),
                "start_epoch": start,
                "age_secs": int(time.time() - start) if start else None,
            }
        )
    return rows


def journal_recent(lines: int = 120) -> str:
    return _run(["journalctl", "-u", "caldera.service", "-n", str(lines), "--no-pager"])


def journal_all_systems_ready(text: str | None = None) -> bool:
    body = text if text is not None else journal_recent(150)
    return "All systems ready" in body


def journal_suggests_building(text: str | None = None) -> bool:
    body = text if text is not None else journal_recent(80)
    return bool(
        re.search(
            r"pip install|building wheel|compiling|downloading|npm install|collecting |installing collected",
            body,
            re.I,
        )
    )


def classify_startup_state(caldera_home: Path, port: int = 8888) -> str:
    active = systemd_field("ActiveState")
    sub = systemd_field("SubState")
    if active == "activating":
        return "STARTING"
    if active == "failed":
        return "FAILED"
    journal = journal_recent(80)
    if active == "active" and sub == "running":
        listener = listener_on_port(port)
        if listener.get("pid") and journal_all_systems_ready(journal):
            return "RUNNING"
        if journal_suggests_building(journal) or not journal_all_systems_ready(journal):
            return "BUILDING"
        if not listener.get("pid"):
            return "STARTING"
        return "STARTING"
    return "FAILED"


def startup_in_progress(caldera_home: Path, port: int = 8888) -> bool:
    active = systemd_field("ActiveState")
    sub = systemd_field("SubState")
    if active != "active" or sub != "running":
        return active in ("activating", "reloading") or active == "active"
    state = classify_startup_state(caldera_home, port)
    if state in ("STARTING", "BUILDING"):
        return True
    journal = journal_recent(120)
    if not journal_all_systems_ready(journal):
        return True
    if journal_suggests_building(journal):
        return True
    return False


def listener_on_port(port: int) -> dict[str, str]:
    out = _run(["ss", "-lntp"])
    for line in out.splitlines():
        if f":{port}" not in line:
            continue
        m = re.search(r"pid=(\d+)", line)
        return {"line": line.strip(), "pid": m.group(1) if m else ""}
    return {"line": "", "pid": ""}


def classify_stale_server_pids(
    caldera_home: Path,
    *,
    grace_secs: int = DEFAULT_GRACE_SECS,
    min_orphan_age_secs: int = DEFAULT_MIN_ORPHAN_AGE_SECS,
    port: int = 8888,
    unit: str = "caldera.service",
) -> list[dict[str, object]]:
    """Return server.py PIDs that are safe to treat as stale (orphan / foreign cgroup / old)."""
    if grace_active(grace_secs):
        return []
    if startup_in_progress(caldera_home, port):
        return []

    main_pid = systemd_main_pid(unit)
    procs = list_server_processes(caldera_home)
    if not procs:
        return []

    listener_pid_s = listener_on_port(port).get("pid") or ""
    listener_pid = int(listener_pid_s) if listener_pid_s.isdigit() else None
    now = time.time()
    stale: list[dict[str, object]] = []

    for row in procs:
        pid = int(row["pid"])
        if main_pid and pid == main_pid:
            continue
        if main_pid and is_descendant_of(pid, main_pid):
            continue
        if main_pid and same_systemd_cgroup(pid, main_pid):
            continue

        age = row.get("age_secs")
        if isinstance(age, int) and age < min_orphan_age_secs:
            # Young subprocess during handoff — not stale.
            if listener_pid is None or listener_pid == pid or listener_pid == main_pid:
                continue

        cgroup = str(row.get("cgroup") or "")
        ppid = row.get("ppid")
        orphan = ppid in (None, 0, 1) or (main_pid and not is_descendant_of(pid, main_pid))
        foreign_cgroup = bool(main_pid and cgroup and not same_systemd_cgroup(pid, main_pid))
        holds_port = listener_pid == pid and main_pid and pid != main_pid

        if holds_port or (orphan and foreign_cgroup) or (orphan and isinstance(age, int) and age >= min_orphan_age_secs):
            reason_parts = []
            if holds_port:
                reason_parts.append("holds_listen_port")
            if foreign_cgroup:
                reason_parts.append("foreign_cgroup")
            if orphan:
                reason_parts.append("orphan")
            if isinstance(age, int) and age >= min_orphan_age_secs:
                reason_parts.append(f"age_secs={age}")
            stale.append({**row, "reason": ",".join(reason_parts) or "stale_candidate"})

    return stale


def stale_pids_only(caldera_home: Path, **kwargs: object) -> list[int]:
    return [int(r["pid"]) for r in classify_stale_server_pids(caldera_home, **kwargs)]


def main() -> int:
    p = argparse.ArgumentParser(description="CALDERA server.py stale process helpers")
    p.add_argument("--caldera-home", type=Path, default=DEFAULT_HOME)
    p.add_argument("--grace-secs", type=int, default=DEFAULT_GRACE_SECS)
    p.add_argument("--min-orphan-age-secs", type=int, default=DEFAULT_MIN_ORPHAN_AGE_SECS)
    p.add_argument("--port", type=int, default=8888)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("record-grace", help="Mark restart grace window (no stale kills)")
    sp = sub.add_parser("stale-pids", help="Print stale PIDs one per line")
    sp.add_argument("--json", action="store_true")

    sub.add_parser("grace-active", help="Exit 0 if grace window active")
    sub.add_parser("startup-in-progress", help="Exit 0 if CALDERA build/startup still running")

    args = p.parse_args()
    home = args.caldera_home.resolve()

    if args.cmd == "record-grace":
        until = record_restart_grace(args.grace_secs)
        print(until)
        return 0
    if args.cmd == "grace-active":
        return 0 if grace_active(args.grace_secs) else 1
    if args.cmd == "startup-in-progress":
        return 0 if startup_in_progress(home, args.port) else 1
    if args.cmd == "stale-pids":
        rows = classify_stale_server_pids(
            home,
            grace_secs=args.grace_secs,
            min_orphan_age_secs=args.min_orphan_age_secs,
            port=args.port,
        )
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            for row in rows:
                print(row["pid"])
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
