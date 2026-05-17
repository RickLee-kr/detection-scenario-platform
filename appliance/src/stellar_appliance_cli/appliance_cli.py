"""
REFERENCE / LEGACY SNAPSHOT — not installed by setup.py.

Canonical CLI module: repository-root ``appliance_cli.py`` (``aella_cli=appliance_cli:main``).

KVM / virsh / qemu-img / sensor deploy logic lives in
/opt/xdr-lab/scripts/xdr-lab-vm-manager.sh (not here).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from functools import wraps
from pathlib import Path
from typing import FrozenSet, List, Optional, Sequence, Tuple

LOG = logging.getLogger("aella_cli")

_XDR_BASE = Path(os.environ.get("XDR_BASE", "/opt/xdr-lab"))
LAB_MANAGER = Path(os.environ.get("XDR_LAB_MANAGER", str(_XDR_BASE / "scripts" / "xdr-lab-vm-manager.sh")))
LAB_CONFIG = Path(os.environ.get("XDR_LAB_CONFIG", str(_XDR_BASE / "config" / "lab-vms.json")))

# Baseline VM keys (used if config is missing or incomplete).
LAB_KNOWN_VMS: FrozenSet[str] = frozenset(
    {"sensor-vm", "windows-victim", "victim-linux", "test-vm1"}
)


def _configure_logging() -> None:
    if LOG.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    LOG.setLevel(logging.INFO)


def log_command(func):
    """Preserve logging decorator pattern for command handlers."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        LOG.info(
            "structured_log",
            extra={
                "event": "command_enter",
                "command": func.__name__,
            },
        )
        t0 = time.monotonic()
        try:
            return func(*args, **kwargs)
        finally:
            dt = time.monotonic() - t0
            LOG.info(
                "structured_log",
                extra={
                    "event": "command_exit",
                    "command": func.__name__,
                    "duration_sec": round(dt, 4),
                },
            )

    return wrapper


def shell_cmd_exec(
    argv: Sequence[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    check: bool = False,
) -> Tuple[int, str, str]:
    """
    Execute argv without a shell. Returns (returncode, stdout, stderr).
    Execution model is intentionally minimal and unchanged in semantics.
    """
    argv_list = list(argv)
    LOG.info(
        "structured_log",
        extra={
            "event": "shell_cmd_exec",
            "argv": argv_list,
        },
    )
    proc = subprocess.Popen(
        argv_list,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out, err = proc.communicate()
    rc = int(proc.returncode if proc.returncode is not None else 0)
    if check and rc != 0:
        LOG.error(
            "structured_log",
            extra={
                "event": "shell_cmd_exec_failed",
                "argv": argv_list,
                "rc": rc,
                "stderr_preview": (err or "")[:2000],
            },
        )
        raise RuntimeError(f"Command failed (rc={rc}): {' '.join(argv_list)}")
    return rc, out or "", err or ""


def _lab_vm_names_effective() -> FrozenSet[str]:
    if not LAB_CONFIG.is_file():
        return LAB_KNOWN_VMS
    try:
        data = json.loads(LAB_CONFIG.read_text(encoding="utf-8"))
        keys = set(data.get("vms", {}).keys())
        return frozenset(keys) | LAB_KNOWN_VMS
    except (json.JSONDecodeError, OSError, TypeError) as exc:
        LOG.warning(
            "structured_log",
            extra={
                "event": "lab_config_read_failed",
                "path": str(LAB_CONFIG),
                "error": str(exc),
            },
        )
        return LAB_KNOWN_VMS


def _require_lab_manager() -> None:
    if not LAB_MANAGER.is_file():
        LOG.error(
            "structured_log",
            extra={
                "event": "lab_manager_missing",
                "path": str(LAB_MANAGER),
            },
        )
        print(
            f"XDR Lab manager not found: {LAB_MANAGER}. "
            "Install assets to /opt/xdr-lab (see cli-installer.sh).",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _validate_lab_vm(name: str, *, allow_all: bool) -> None:
    if allow_all and name == "all":
        return
    valid = _lab_vm_names_effective()
    if name not in valid:
        LOG.error(
            "structured_log",
            extra={"event": "lab_invalid_vm", "vm": name, "allowed": sorted(valid)},
        )
        print(
            f"Invalid VM name {name!r}. Expected one of: {', '.join(sorted(valid))}"
            + (", all" if allow_all else ""),
            file=sys.stderr,
        )
        raise SystemExit(2)


def _emit_streams(rc: int, out: str, err: str) -> int:
    if out:
        sys.stdout.write(out)
    if err:
        sys.stderr.write(err)
    return rc


@log_command
def cmd_appliance_status(_args: argparse.Namespace) -> int:
    rc, out, err = shell_cmd_exec(["uptime"])
    return _emit_streams(rc, out, err)


@log_command
def cmd_appliance_info(_args: argparse.Namespace) -> int:
    rc, out, err = shell_cmd_exec(["uname", "-a"])
    return _emit_streams(rc, out, err)


def _lab_argv(action: str, target: str, extra: Optional[List[str]] = None) -> List[str]:
    _require_lab_manager()
    cmd: List[str] = [str(LAB_MANAGER), action, target]
    if extra:
        cmd.extend(extra)
    return cmd


@log_command
def cmd_lab_deploy(args: argparse.Namespace) -> int:
    _validate_lab_vm(args.target, allow_all=True)
    extra: List[str] = []
    if getattr(args, "nodownload", False):
        extra.append("--nodownload")
    rc, out, err = shell_cmd_exec(_lab_argv("deploy", args.target, extra))
    return _emit_streams(rc, out, err)


@log_command
def cmd_lab_download(args: argparse.Namespace) -> int:
    _validate_lab_vm(args.target, allow_all=True)
    rc, out, err = shell_cmd_exec(_lab_argv("download", args.target))
    return _emit_streams(rc, out, err)


@log_command
def cmd_lab_start(args: argparse.Namespace) -> int:
    _validate_lab_vm(args.target, allow_all=True)
    rc, out, err = shell_cmd_exec(_lab_argv("start", args.target))
    return _emit_streams(rc, out, err)


@log_command
def cmd_lab_stop(args: argparse.Namespace) -> int:
    _validate_lab_vm(args.target, allow_all=True)
    rc, out, err = shell_cmd_exec(_lab_argv("stop", args.target))
    return _emit_streams(rc, out, err)


@log_command
def cmd_lab_destroy(args: argparse.Namespace) -> int:
    _validate_lab_vm(args.target, allow_all=True)
    rc, out, err = shell_cmd_exec(_lab_argv("destroy", args.target))
    return _emit_streams(rc, out, err)


@log_command
def cmd_lab_status(args: argparse.Namespace) -> int:
    target = args.target or "all"
    if target != "all":
        _validate_lab_vm(target, allow_all=False)
    rc, out, err = shell_cmd_exec(_lab_argv("status", target))
    return _emit_streams(rc, out, err)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aella_cli",
        description="Stellar appliance CLI (orchestration).",
    )
    sub = p.add_subparsers(dest="group", required=True)

    # --- appliance (existing-style nested commands; behavior preserved) ---
    app = sub.add_parser("appliance", help="Appliance maintenance commands")
    app_sub = app.add_subparsers(dest="appliance_cmd", required=True)

    p_status = app_sub.add_parser("status", help="Show basic appliance load (uptime)")
    p_status.set_defaults(handler=cmd_appliance_status)

    p_info = app_sub.add_parser("info", help="Show kernel identity (uname -a)")
    p_info.set_defaults(handler=cmd_appliance_info)

    # --- lab (XDR Lab VM orchestration; delegates to xdr-lab-vm-manager.sh) ---
    lab = sub.add_parser("lab", help="XDR Lab VM orchestration (KVM)")
    lab_sub = lab.add_subparsers(dest="lab_cmd", required=True)

    p_deploy = lab_sub.add_parser(
        "deploy",
        help="Deploy one VM or all (calls xdr-lab-vm-manager.sh deploy)",
    )
    p_deploy.add_argument("target", help="VM name or 'all'")
    p_deploy.add_argument(
        "--nodownload",
        action="store_true",
        help="For sensor-vm: use cached deploy script / qcow2 only",
    )
    p_deploy.set_defaults(handler=cmd_lab_deploy)

    p_dl = lab_sub.add_parser(
        "download",
        help="Download VM image / sensor assets (calls ... download)",
    )
    p_dl.add_argument("target", help="VM name or 'all'")
    p_dl.set_defaults(handler=cmd_lab_download)

    p_start = lab_sub.add_parser("start", help="Start VM(s) (calls ... start)")
    p_start.add_argument("target", help="VM name or 'all'")
    p_start.set_defaults(handler=cmd_lab_start)

    p_stop = lab_sub.add_parser("stop", help="Stop VM(s) (calls ... stop)")
    p_stop.add_argument("target", help="VM name or 'all'")
    p_stop.set_defaults(handler=cmd_lab_stop)

    p_destroy = lab_sub.add_parser("destroy", help="Destroy VM(s) (calls ... destroy)")
    p_destroy.add_argument("target", help="VM name or 'all'")
    p_destroy.set_defaults(handler=cmd_lab_destroy)

    p_stat = lab_sub.add_parser("status", help="Show VM status (calls ... status)")
    p_stat.add_argument(
        "target",
        nargs="?",
        default="all",
        help="Optional VM name (default: all)",
    )
    p_stat.set_defaults(handler=cmd_lab_status)

    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    _configure_logging()
    argv_list = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()
    try:
        args = parser.parse_args(argv_list)
    except SystemExit as e:
        code = e.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return int(handler(args))
    except SystemExit as se:
        raise se
    except RuntimeError as exc:
        LOG.error("structured_log", extra={"event": "handler_runtime_error", "error": str(exc)})
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
