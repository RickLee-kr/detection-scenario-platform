#!/usr/bin/env python3
"""Diagnose CALDERA disk vs runtime auth (ExecStart, listener PID, config overrides)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from caldera_key_crypto import load_config, read_key_file, verify_api_key
from caldera_process_util import (
    classify_stale_server_pids,
    grace_active,
    list_server_processes,
    listener_on_port,
    startup_in_progress,
    systemd_main_pid,
)


def read_unit_field(unit_path: Path, field: str) -> str:
    if not unit_path.is_file():
        return ""
    for line in unit_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(f"{field}="):
            return line.split("=", 1)[1].strip()
    return ""


def parse_environment(execstart: str) -> str:
    if re.search(r"(?:^|\s)--insecure(?:\s|$)", execstart):
        return "default"
    m = re.search(r"(?:-E|--environment)(?:=|\s+)([A-Za-z0-9_-]+)", execstart)
    return m.group(1) if m else "local"


def diag(args: argparse.Namespace) -> dict:
    home = Path(args.caldera_home).resolve()
    unit = Path(args.unit_path)
    execstart = read_unit_field(unit, "ExecStart")
    env_name = parse_environment(execstart)
    main_yml = home / "conf" / f"{env_name}.yml"
    port = 8888
    if main_yml.is_file():
        cfg = load_config(main_yml)
        try:
            port = int(cfg.get("port", port))
        except (TypeError, ValueError):
            pass

    procs = list_server_processes(home)
    listener = listener_on_port(port)
    main_pid = systemd_main_pid()
    listener_pid = listener.get("pid", "")
    stale_rows = classify_stale_server_pids(
        home,
        grace_secs=args.grace_secs,
        min_orphan_age_secs=args.min_orphan_age_secs,
        port=port,
    )
    building = startup_in_progress(home, port)
    in_grace = grace_active(args.grace_secs)

    overrides = {}
    for name in ("local.yml", "chain.yml"):
        p = home / "conf" / name
        overrides[name] = {"path": str(p), "exists": p.is_file()}

    key_verify: dict[str, object] = {}
    if args.key_file.is_file() and main_yml.is_file():
        try:
            plain = read_key_file(args.key_file)
            data = load_config(main_yml)
            key_verify = {
                "readable": True,
                "matches_api_key_red": verify_api_key(str(data.get("api_key_red") or ""), plain),
            }
        except OSError as exc:
            key_verify = {"readable": False, "error": str(exc)}

    listener_int = int(listener_pid) if listener_pid.isdigit() else None
    aligned_listener = False
    if listener_int and main_pid:
        from caldera_process_util import is_descendant_of, same_systemd_cgroup

        aligned_listener = (
            listener_int == main_pid
            or is_descendant_of(listener_int, main_pid)
            or same_systemd_cgroup(listener_int, main_pid)
        )
    elif listener_int and not main_pid:
        aligned_listener = True

    runtime_aligned = bool(
        (not stale_rows)
        and (aligned_listener or building or in_grace or not listener_pid)
    )

    if stale_rows and listener_pid and listener_pid != str(main_pid or ""):
        diagnosis = (
            f"stale server.py PIDs { [r['pid'] for r in stale_rows] } — "
            "kill only after grace/build completes (see caldera_process_util)"
        )
    elif building or in_grace:
        diagnosis = "CALDERA startup/build or restart grace — multiple server.py children are expected"
    elif runtime_aligned:
        diagnosis = (
            "listener aligned with systemd scope — if 302 persists, enable XDR_CALDERA_AUTH_DEBUG=1 "
            "and check journal caldera.xdr.auth"
        )
    else:
        diagnosis = "check caldera.service active state, journal 'All systems ready', and port binding"

    return {
        "caldera_home": str(home),
        "systemd_unit": str(unit),
        "execstart": execstart,
        "environment": env_name,
        "uses_insecure": bool(re.search(r"--insecure", execstart)),
        "main_config_path": str(main_yml),
        "main_config_exists": main_yml.is_file(),
        "override_configs": overrides,
        "listen_port": port,
        "systemd_main_pid": main_pid,
        "listener": listener,
        "server_processes": procs,
        "stale_server_processes": stale_rows,
        "startup_in_progress": building,
        "stale_grace_active": in_grace,
        "runtime_aligned_with_systemd": runtime_aligned,
        "key_file": str(args.key_file),
        "disk_key_verify": key_verify,
        "diagnosis": diagnosis,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="CALDERA runtime vs disk auth diagnostics")
    p.add_argument("--caldera-home", type=Path, default=Path("/opt/caldera"))
    p.add_argument("--unit-path", type=Path, default=Path("/etc/systemd/system/caldera.service"))
    p.add_argument("--key-file", type=Path, default=Path("/etc/xdr-lab/caldera-api-key"))
    p.add_argument("--grace-secs", type=int, default=90)
    p.add_argument("--min-orphan-age-secs", type=int, default=300)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    doc = diag(args)
    if args.json:
        print(json.dumps(doc, indent=2, sort_keys=True))
    else:
        for k, v in doc.items():
            print(f"{k}: {v}")
    return 0 if doc.get("runtime_aligned_with_systemd") else 1


if __name__ == "__main__":
    raise SystemExit(main())
