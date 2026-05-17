"""
Appliance CLI — orchestration layer (flat module).

KVM / virsh / qemu-img / sensor deploy logic lives in
/opt/xdr-lab/scripts/xdr-lab-vm-manager.sh (not here).
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import sys
import time
from functools import wraps
from pathlib import Path
from typing import FrozenSet, List, Optional, Sequence, Tuple

LOG = logging.getLogger("aella_cli")

# Runtime install target. Default is /opt/xdr-lab (set by cli-installer.sh);
# override via XDR_BASE / XDR_LAB_MANAGER for development against the repository checkout.
_XDR_BASE = Path(os.environ.get("XDR_BASE", "/opt/xdr-lab"))
_CLI_MODULE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _CLI_MODULE_DIR.parent


def _resolve_lab_manager() -> Path:
    if os.environ.get("XDR_LAB_MANAGER"):
        return Path(os.environ["XDR_LAB_MANAGER"])
    dev_mgr = _REPO_ROOT / "scripts" / "xdr-lab-vm-manager.sh"
    if dev_mgr.is_file():
        return dev_mgr
    return _XDR_BASE / "scripts" / "xdr-lab-vm-manager.sh"


def _resolve_lab_config() -> Path:
    if os.environ.get("XDR_LAB_CONFIG"):
        return Path(os.environ["XDR_LAB_CONFIG"])
    dev_cfg = _REPO_ROOT / "config" / "lab-vms.json"
    if dev_cfg.is_file():
        return dev_cfg
    return _XDR_BASE / "config" / "lab-vms.json"


LAB_MANAGER = _resolve_lab_manager()
LAB_CONFIG = _resolve_lab_config()

LAB_KNOWN_VMS: FrozenSet[str] = frozenset(
    {"sensor-vm", "windows-victim", "victim-linux", "test-vm1"}
)

ROOT_COMMAND_HELP = """\
aella_cli — Stellar appliance CLI

Commands:
  appliance <subcommand>   Appliance maintenance (see: aella_cli appliance help)
  lab <subcommand>         XDR Lab control plane (VM / NAT / OVS / consoles; see: aella_cli lab help)

Global options:
  -h, --help                Show this message (also: aella_cli help)

Examples:
  aella_cli appliance status
  aella_cli lab status
  aella_cli lab deploy sensor-vm --dry-run
  aella_cli lab validate --dry-run
  aella_cli lab mirror verify
"""

APPLIANCE_COMMAND_HELP = """\
Usage: aella_cli appliance <subcommand>

Subcommands:
  status     Show basic appliance load (uptime)
  info       Show kernel identity (uname -a)
"""

lab_command_help = """\
Usage: aella_cli lab <subcommand> [args] [--dry-run]

Core VM lifecycle:
  deploy <vm|all> [--nodownload] [--dry-run]
  download [<vm|all|image_name>] [--force] [--dry-run]   (manifest bulk: lab download with no args)
  images status [--dry-run]
  start <vm|all> [--dry-run]
  stop <vm|all> [--dry-run]
  destroy <vm|all> [--dry-run]
  status [vm] [--dry-run]   (default vm: all)

Validation (delegates to xdr-lab-vm-manager.sh validate):
  validate [vm|all] [--dry-run]   (default: all — virsh / ping / type-specific checks)

OVS mirror (delegates to xdr-lab-vm-manager.sh mirror):
  mirror apply [sensor-vm] [--dry-run]
  mirror verify [sensor-vm] [--dry-run]
  mirror traffic [sensor-vm] [--dry-run]   (end-to-end mirror path + probe; engine)

NAT observability (read-only verify in engine):
  nat status [--dry-run]
  nat verify [--dry-run]

Windows browser / VNC console hints:
  web-console start [vm] [--dry-run]   (default vm: windows-victim)
  web-console stop [vm] [--dry-run]
  web-console status [vm] [--dry-run]
  web-console verify [vm] [--dry-run]   (websockify / VNC wiring check)
  windows-console [vm] [--dry-run]

Operator summary & teardown:
  access [--dry-run]                   # reverse-NAT / lab access summary from lab-vms.json
  cleanup [--dry-run]                  # stop + destroy all VMs (engine: cleanup all)

Snapshots (sensor-vm, victim-linux, windows-victim; engine + snapshots.json):
  snapshot create [<vm>] [<name>] [--dry-run]   # omit <vm> → batch all targets
  snapshot revert [<vm>] <name> [--dry-run]
  snapshot list [<vm>] [--dry-run]
  snapshot delete [<vm>] <name> [--dry-run]

MITRE CALDERA (BAS / adversary emulation; state: runtime/state/scenario.json, caldera.json):
  scenario list [--dry-run]
  scenario bootstrap validate [--json] [--dry-run]
  scenario atomic validate [--json] [--dry-run]
  scenario pack validate [--json] [--dry-run]
  scenario run <NAME> [--snapshot-before] [--dry-run]   # NAME: scenario_id from `scenario list`
  scenario stop [--dry-run]
  scenario status [--human] [--dry-run]
  scenario telemetry <NAME|last|verify> [--json] [--dry-run]
  scenario agent status|deploy|remove [--dry-run]

Runtime visibility (read-only; delegates to caldera_orchestration.py runtime):
  runtime summary [--json] [--dry-run]
  runtime inspect [--json] [--dry-run]
  runtime jsonl tail [--lines N] [--filter REGEX] [--json] [--dry-run]
  runtime operation [--json] [--dry-run]
  runtime mirror [--json] [--dry-run]
  runtime snapshots [--json] [--dry-run]
  runtime evidence bundle [--out DIR] [--dry-run]
  runtime evidence export-jsonl [--out FILE] [--lines N] [--filter REGEX] [--dry-run]
  runtime validate repeat|stale|cleanup|consistency [--json] [--dry-run]
  runtime preview [scenario_id] [--snapshot-before] [--json] [--dry-run]

  help                                 Show this message

VM names include: sensor-vm, windows-victim, victim-linux, test-vm1 (or 'all' where supported).

--dry-run prints the manager command line without executing it.
--nodownload applies to deploy (skip manifest sync + legacy artifact downloads where applicable).
Manifest-driven golden images are opt-in: enabled in config/images-manifest.json or XDR_LAB_USE_IMAGE_MANIFEST=1.
"""


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
    """Structured logging wrapper for command handlers."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        LOG.info(
            "structured_log",
            extra={"event": "command_enter", "command": func.__name__},
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
    """Execute argv without a shell. Returns (returncode, stdout, stderr)."""
    argv_list = list(argv)
    LOG.info(
        "structured_log",
        extra={"event": "shell_cmd_exec", "argv": argv_list},
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


def _require_lab_manager(*, dry_run: bool) -> None:
    if dry_run:
        return
    if not LAB_MANAGER.is_file():
        LOG.error(
            "structured_log",
            extra={"event": "lab_manager_missing", "path": str(LAB_MANAGER)},
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


def _strip_flags(tokens: List[str], flags: Sequence[str]) -> Tuple[List[str], dict]:
    """Remove known flags from tokens; return (rest, flags_seen)."""
    seen = {f: False for f in flags}
    out: List[str] = []
    for t in tokens:
        if t in flags:
            seen[t] = True
        else:
            out.append(t)
    return out, seen


def _lab_manager_argv(action: str, target: str, extra: Optional[List[str]] = None) -> List[str]:
    cmd: List[str] = [str(LAB_MANAGER), action, target]
    if extra:
        cmd.extend(extra)
    return cmd


def _lab_script_argv(parts: Sequence[str]) -> List[str]:
    return [str(LAB_MANAGER), *list(parts)]


def _lab_failure_notice(argv: List[str], rc: int) -> None:
    if rc == 0:
        return
    script = os.path.basename(argv[0]) if argv else "xdr-lab-vm-manager.sh"
    sys.stderr.write(
        f"Error: lab command failed (exit {rc}). "
        f"Review stderr above or check {script} logs (vm-manager.log).\n"
    )


def _lab_invoke_script(argv_tail: Sequence[str], *, dry_run: bool) -> int:
    argv = _lab_script_argv(argv_tail)
    if dry_run:
        line = " ".join(shlex.quote(x) for x in argv)
        sys.stdout.write(f"DRY-RUN: {line}\n")
        return 0
    _require_lab_manager(dry_run=False)
    rc, out, err = shell_cmd_exec(argv)
    rc = _emit_streams(rc, out, err)
    _lab_failure_notice(argv, rc)
    return rc


def _lab_invoke_script_caldera_dry(argv_tail: Sequence[str], *, dry_run: bool) -> int:
    """Run vm-manager scenario branch; with --dry-run set XDR_LAB_DRY_RUN=1 (still executes engine)."""
    argv = _lab_script_argv(argv_tail)
    line = " ".join(shlex.quote(x) for x in argv)
    if dry_run:
        sys.stdout.write(f"DRY-RUN (CALDERA operation mutations disabled): {line}\n")
        sys.stdout.flush()
    _require_lab_manager(dry_run=False)
    env = os.environ.copy()
    if dry_run:
        env["XDR_LAB_DRY_RUN"] = "1"
    else:
        env.pop("XDR_LAB_DRY_RUN", None)
    rc, out, err = shell_cmd_exec(argv, env=env)
    rc = _emit_streams(rc, out, err)
    _lab_failure_notice(argv, rc)
    return rc


def _lab_invoke_manager(
    action: str,
    target: str,
    *,
    extra: Optional[List[str]] = None,
    dry_run: bool,
) -> int:
    argv = _lab_manager_argv(action, target, extra)
    if dry_run:
        line = " ".join(shlex.quote(x) for x in argv)
        sys.stdout.write(f"DRY-RUN: {line}\n")
        return 0
    _require_lab_manager(dry_run=False)
    rc, out, err = shell_cmd_exec(argv)
    rc = _emit_streams(rc, out, err)
    _lab_failure_notice(argv, rc)
    return rc


@log_command
def lab_deploy_callback(argv: List[str], *, dry_run: bool) -> int:
    tokens, seen = _strip_flags(list(argv), ("--nodownload", "--dry-run"))
    dry_run = dry_run or seen["--dry-run"]
    if not tokens:
        print("Usage: aella_cli lab deploy <vm|all> [--nodownload] [--dry-run]", file=sys.stderr)
        return 2
    target = tokens[0]
    if len(tokens) > 1:
        print(f"Unexpected arguments: {' '.join(tokens[1:])}", file=sys.stderr)
        return 2
    _validate_lab_vm(target, allow_all=True)
    extra = ["--nodownload"] if seen["--nodownload"] else None
    return _lab_invoke_manager("deploy", target, extra=extra, dry_run=dry_run)


@log_command
def lab_download_callback(argv: List[str], *, dry_run: bool) -> int:
    tokens, seen = _strip_flags(list(argv), ("--dry-run", "--force"))
    dry_run = dry_run or seen["--dry-run"]
    extra: List[str] = []
    if seen["--force"]:
        extra.append("--force")
    if not tokens:
        return _lab_invoke_script(["download", *extra], dry_run=dry_run)
    target = tokens[0]
    if len(tokens) > 1:
        print(f"Unexpected arguments: {' '.join(tokens[1:])}", file=sys.stderr)
        return 2
    if target == "all":
        _validate_lab_vm(target, allow_all=True)
    elif target in _lab_vm_names_effective():
        _validate_lab_vm(target, allow_all=False)
    return _lab_invoke_script(["download", *extra, target], dry_run=dry_run)


@log_command
def lab_images_callback(argv: List[str], *, dry_run: bool) -> int:
    tokens, seen = _strip_flags(list(argv), ("--dry-run",))
    dry_run = dry_run or seen["--dry-run"]
    if not tokens or tokens[0] != "status":
        print("Usage: aella_cli lab images status [--dry-run]", file=sys.stderr)
        return 2
    if len(tokens) > 1:
        print(f"Unexpected arguments: {' '.join(tokens[1:])}", file=sys.stderr)
        return 2
    return _lab_invoke_script(["images", "status"], dry_run=dry_run)


@log_command
def lab_start_callback(argv: List[str], *, dry_run: bool) -> int:
    tokens, seen = _strip_flags(list(argv), ("--dry-run",))
    dry_run = dry_run or seen["--dry-run"]
    if not tokens:
        print("Usage: aella_cli lab start <vm|all> [--dry-run]", file=sys.stderr)
        return 2
    target = tokens[0]
    if len(tokens) > 1:
        print(f"Unexpected arguments: {' '.join(tokens[1:])}", file=sys.stderr)
        return 2
    _validate_lab_vm(target, allow_all=True)
    return _lab_invoke_manager("start", target, dry_run=dry_run)


@log_command
def lab_stop_callback(argv: List[str], *, dry_run: bool) -> int:
    tokens, seen = _strip_flags(list(argv), ("--dry-run",))
    dry_run = dry_run or seen["--dry-run"]
    if not tokens:
        print("Usage: aella_cli lab stop <vm|all> [--dry-run]", file=sys.stderr)
        return 2
    target = tokens[0]
    if len(tokens) > 1:
        print(f"Unexpected arguments: {' '.join(tokens[1:])}", file=sys.stderr)
        return 2
    _validate_lab_vm(target, allow_all=True)
    return _lab_invoke_manager("stop", target, dry_run=dry_run)


@log_command
def lab_destroy_callback(argv: List[str], *, dry_run: bool) -> int:
    tokens, seen = _strip_flags(list(argv), ("--dry-run",))
    dry_run = dry_run or seen["--dry-run"]
    if not tokens:
        print("Usage: aella_cli lab destroy <vm|all> [--dry-run]", file=sys.stderr)
        return 2
    target = tokens[0]
    if len(tokens) > 1:
        print(f"Unexpected arguments: {' '.join(tokens[1:])}", file=sys.stderr)
        return 2
    _validate_lab_vm(target, allow_all=True)
    return _lab_invoke_manager("destroy", target, dry_run=dry_run)


@log_command
def lab_status_callback(argv: List[str], *, dry_run: bool) -> int:
    tokens, seen = _strip_flags(list(argv), ("--dry-run",))
    dry_run = dry_run or seen["--dry-run"]
    target = "all"
    if tokens:
        target = tokens[0]
        if len(tokens) > 1:
            print(f"Unexpected arguments: {' '.join(tokens[1:])}", file=sys.stderr)
            return 2
    if target != "all":
        _validate_lab_vm(target, allow_all=False)
    return _lab_invoke_manager("status", target, dry_run=dry_run)


@log_command
def lab_validate_callback(argv: List[str], *, dry_run: bool) -> int:
    tokens, seen = _strip_flags(list(argv), ("--dry-run",))
    dry_run = dry_run or seen["--dry-run"]
    target = "all"
    if tokens:
        target = tokens[0]
        if len(tokens) > 1:
            print(f"Unexpected arguments: {' '.join(tokens[1:])}", file=sys.stderr)
            return 2
    if target != "all":
        _validate_lab_vm(target, allow_all=False)
    return _lab_invoke_manager("validate", target, dry_run=dry_run)


@log_command
def lab_mirror_callback(argv: List[str], *, dry_run: bool) -> int:
    tokens, seen = _strip_flags(list(argv), ("--dry-run",))
    dry_run = dry_run or seen["--dry-run"]
    if not tokens:
        print(
            "Usage: aella_cli lab mirror apply [sensor-vm] [--dry-run]\n"
            "       aella_cli lab mirror verify [sensor-vm] [--dry-run]\n"
            "       aella_cli lab mirror traffic [sensor-vm] [--dry-run]",
            file=sys.stderr,
        )
        return 2
    sub = tokens[0]
    mirror_sub = sub
    if sub == "traffic":
        mirror_sub = "validate-traffic"
    if sub not in ("apply", "verify", "traffic"):
        print(f"Unknown lab mirror subcommand: {sub!r}", file=sys.stderr)
        return 2
    rest = tokens[1:]
    if len(rest) > 1:
        print(f"Unexpected arguments: {' '.join(rest[1:])}", file=sys.stderr)
        return 2
    tail: List[str] = ["mirror", mirror_sub]
    if rest:
        _validate_lab_vm(rest[0], allow_all=False)
        tail.append(rest[0])
    return _lab_invoke_script(tail, dry_run=dry_run)


@log_command
def lab_nat_callback(argv: List[str], *, dry_run: bool) -> int:
    tokens, seen = _strip_flags(list(argv), ("--dry-run",))
    dry_run = dry_run or seen["--dry-run"]
    if not tokens or tokens[0] not in ("status", "verify"):
        print(
            "Usage: aella_cli lab nat status [--dry-run]\n       aella_cli lab nat verify [--dry-run]",
            file=sys.stderr,
        )
        return 2
    if len(tokens) > 1:
        print(f"Unexpected arguments: {' '.join(tokens[1:])}", file=sys.stderr)
        return 2
    return _lab_invoke_script(["nat", tokens[0]], dry_run=dry_run)


@log_command
def lab_web_console_callback(argv: List[str], *, dry_run: bool) -> int:
    tokens, seen = _strip_flags(list(argv), ("--dry-run",))
    dry_run = dry_run or seen["--dry-run"]
    if not tokens:
        print(
            "Usage: aella_cli lab web-console start|stop|status|verify [vm] [--dry-run]",
            file=sys.stderr,
        )
        return 2
    sub = tokens[0]
    if sub not in ("start", "stop", "status", "verify"):
        print(f"Unknown lab web-console subcommand: {sub!r}", file=sys.stderr)
        return 2
    vm = "windows-victim"
    if len(tokens) > 1:
        vm = tokens[1]
    if len(tokens) > 2:
        print(f"Unexpected arguments: {' '.join(tokens[2:])}", file=sys.stderr)
        return 2
    _validate_lab_vm(vm, allow_all=False)
    return _lab_invoke_script(["web-console", sub, vm], dry_run=dry_run)


@log_command
def lab_windows_console_callback(argv: List[str], *, dry_run: bool) -> int:
    tokens, seen = _strip_flags(list(argv), ("--dry-run",))
    dry_run = dry_run or seen["--dry-run"]
    vm = "windows-victim"
    if tokens:
        vm = tokens[0]
    if len(tokens) > 1:
        print(f"Unexpected arguments: {' '.join(tokens[1:])}", file=sys.stderr)
        return 2
    _validate_lab_vm(vm, allow_all=False)
    return _lab_invoke_script(["windows-console", vm], dry_run=dry_run)


@log_command
def lab_access_callback(argv: List[str], *, dry_run: bool) -> int:
    tokens, seen = _strip_flags(list(argv), ("--dry-run",))
    dry_run = dry_run or seen["--dry-run"]
    if tokens:
        print(f"Unexpected arguments: {' '.join(tokens)}", file=sys.stderr)
        return 2
    return _lab_invoke_script(["access"], dry_run=dry_run)


@log_command
def lab_cleanup_callback(argv: List[str], *, dry_run: bool) -> int:
    tokens, seen = _strip_flags(list(argv), ("--dry-run",))
    dry_run = dry_run or seen["--dry-run"]
    if tokens:
        print(f"Unexpected arguments: {' '.join(tokens)}", file=sys.stderr)
        return 2
    return _lab_invoke_script(["cleanup", "all"], dry_run=dry_run)


@log_command
def lab_snapshot_callback(argv: List[str], *, dry_run: bool) -> int:
    tokens, seen = _strip_flags(list(argv), ("--dry-run",))
    dry_run = dry_run or seen["--dry-run"]
    if not tokens:
        print(
            "Usage: aella_cli lab snapshot create [<vm>] [<name>] [--dry-run]\n"
            "       aella_cli lab snapshot revert [<vm>] <name> [--dry-run]\n"
            "       aella_cli lab snapshot list [<vm>] [--dry-run]\n"
            "       aella_cli lab snapshot delete [<vm>] <name> [--dry-run]",
            file=sys.stderr,
        )
        return 2
    sub = tokens[0]
    rest = tokens[1:]
    if sub not in ("create", "revert", "list", "delete"):
        print(f"Unknown lab snapshot subcommand: {sub!r}", file=sys.stderr)
        return 2
    tail: List[str] = ["snapshot", sub]
    if sub == "create":
        if len(rest) > 2:
            print(f"Unexpected arguments: {' '.join(rest[2:])}", file=sys.stderr)
            return 2
        tail.extend(rest)
    elif sub == "revert":
        if len(rest) < 1 or len(rest) > 2:
            print(
                "Usage: aella_cli lab snapshot revert [<vm>] <name> [--dry-run]",
                file=sys.stderr,
            )
            return 2
        tail.extend(rest)
    elif sub == "list":
        if len(rest) > 1:
            print(f"Unexpected arguments: {' '.join(rest[1:])}", file=sys.stderr)
            return 2
        if rest:
            tail.append(rest[0])
    else:  # delete
        if len(rest) < 1 or len(rest) > 2:
            print(
                "Usage: aella_cli lab snapshot delete [<vm>] <name> [--dry-run]",
                file=sys.stderr,
            )
            return 2
        tail.extend(rest)
    return _lab_invoke_script(tail, dry_run=dry_run)


@log_command
def lab_scenario_callback(argv: List[str], *, dry_run: bool) -> int:
    tokens, seen = _strip_flags(list(argv), ("--dry-run",))
    dry_run = dry_run or seen["--dry-run"]
    if not tokens:
        print(
            "Usage: aella_cli lab scenario list [--dry-run]\n"
            "       aella_cli lab scenario bootstrap validate [--json] [--dry-run]\n"
            "       aella_cli lab scenario atomic validate [--json] [--dry-run]\n"
            "       aella_cli lab scenario pack validate [--json] [--dry-run]\n"
            "       aella_cli lab scenario run <NAME> [--snapshot-before] [--dry-run]  "
            "(NAME is the scenario_id from `scenario list`)\n"
            "       aella_cli lab scenario stop [--dry-run]\n"
            "       aella_cli lab scenario status [--human] [--dry-run]\n"
            "       aella_cli lab scenario telemetry <NAME|last|verify> [--json] [--dry-run]\n"
            "       aella_cli lab scenario agent status [--json] [--dry-run]\n"
            "       aella_cli lab scenario agent deploy [--dry-run]\n"
            "       aella_cli lab scenario agent remove [--dry-run]",
            file=sys.stderr,
        )
        return 2
    head, rest = tokens[0], tokens[1:]
    if head == "list":
        if rest:
            print(f"Unexpected arguments: {' '.join(rest)}", file=sys.stderr)
            return 2
        return _lab_invoke_script_caldera_dry(["scenario", "list"], dry_run=dry_run)
    if head == "bootstrap":
        if not rest or rest[0] != "validate":
            print(
                "Usage: aella_cli lab scenario bootstrap validate [--json] [--dry-run]",
                file=sys.stderr,
            )
            return 2
        tail = rest[1:]
        json_only = False
        for t in tail:
            if t == "--json":
                json_only = True
            elif t == "--dry-run":
                pass
            else:
                print(f"Unexpected argument: {t!r}", file=sys.stderr)
                return 2
        cmd = ["scenario", "bootstrap", "validate"]
        if json_only:
            cmd.append("--json")
        return _lab_invoke_script_caldera_dry(cmd, dry_run=dry_run)
    if head == "atomic":
        if not rest or rest[0] != "validate":
            print(
                "Usage: aella_cli lab scenario atomic validate [--json] [--dry-run]",
                file=sys.stderr,
            )
            return 2
        tail = rest[1:]
        json_only = False
        for t in tail:
            if t == "--json":
                json_only = True
            elif t == "--dry-run":
                pass
            else:
                print(f"Unexpected argument: {t!r}", file=sys.stderr)
                return 2
        cmd = ["scenario", "atomic", "validate"]
        if json_only:
            cmd.append("--json")
        return _lab_invoke_script_caldera_dry(cmd, dry_run=dry_run)
    if head == "pack":
        if not rest or rest[0] != "validate":
            print(
                "Usage: aella_cli lab scenario pack validate [--json] [--dry-run]",
                file=sys.stderr,
            )
            return 2
        tail = rest[1:]
        json_only = False
        for t in tail:
            if t == "--json":
                json_only = True
            elif t == "--dry-run":
                pass
            else:
                print(f"Unexpected argument: {t!r}", file=sys.stderr)
                return 2
        cmd = ["scenario", "pack", "validate"]
        if json_only:
            cmd.append("--json")
        return _lab_invoke_script_caldera_dry(cmd, dry_run=dry_run)
    if head == "status":
        human = False
        for t in rest:
            if t == "--human":
                human = True
            else:
                print(f"Unexpected argument: {t!r}", file=sys.stderr)
                return 2
        cmd = ["scenario", "status"]
        if human:
            cmd.append("--human")
        return _lab_invoke_script_caldera_dry(cmd, dry_run=dry_run)
    if head == "stop":
        if rest:
            print(f"Unexpected arguments: {' '.join(rest)}", file=sys.stderr)
            return 2
        return _lab_invoke_script_caldera_dry(["scenario", "stop"], dry_run=dry_run)
    if head == "telemetry":
        if not rest:
            print(
                "Usage: aella_cli lab scenario telemetry <NAME|last|verify> [--json] [--dry-run]",
                file=sys.stderr,
            )
            return 2
        name = rest[0]
        tail = rest[1:]
        json_only = False
        for t in tail:
            if t == "--json":
                json_only = True
            elif t == "--dry-run":
                pass
            else:
                print(f"Unexpected argument: {t!r}", file=sys.stderr)
                return 2
        cmd = ["scenario", "telemetry", name]
        if json_only:
            cmd.append("--json")
        return _lab_invoke_script_caldera_dry(cmd, dry_run=dry_run)
    if head == "run":
        if not rest:
            print(
                "Usage: aella_cli lab scenario run <NAME> [--snapshot-before] [--dry-run]  "
                "(NAME is the scenario_id from `lab scenario list` — pack or caldera-lab.json)",
                file=sys.stderr,
            )
            return 2
        name = rest[0]
        tail = rest[1:]
        snap = False
        for t in tail:
            if t == "--snapshot-before":
                snap = True
            elif t == "--dry-run":
                pass
            else:
                print(f"Unexpected argument: {t!r}", file=sys.stderr)
                return 2
        cmd = ["scenario", "run", name]
        if snap:
            cmd.append("--snapshot-before")
        return _lab_invoke_script_caldera_dry(cmd, dry_run=dry_run)
    if head == "agent":
        if not rest:
            print(
                "Usage: aella_cli lab scenario agent status [--json] [--dry-run]\n"
                "       aella_cli lab scenario agent deploy [--dry-run]\n"
                "       aella_cli lab scenario agent remove [--dry-run]",
                file=sys.stderr,
            )
            return 2
        sub = rest[0]
        tail = rest[1:]
        tail_flags, seen_agent = _strip_flags(list(tail), ("--dry-run",))
        dry_agent = dry_run or seen_agent["--dry-run"]
        if sub not in ("status", "deploy", "remove"):
            print(f"Unknown lab scenario agent subcommand: {sub!r}", file=sys.stderr)
            return 2
        if sub == "status":
            if tail_flags not in ([], ["--json"]):
                print(f"Unexpected arguments: {' '.join(tail_flags)}", file=sys.stderr)
                return 2
            cmd = ["scenario", "agent", "status", *tail_flags]
            return _lab_invoke_script_caldera_dry(cmd, dry_run=dry_agent)
        if sub == "deploy":
            if tail_flags not in ([], ["--dry-run"]):
                print(f"Unexpected arguments: {' '.join(tail_flags)}", file=sys.stderr)
                return 2
            cmd = ["scenario", "agent", "deploy"]
            if dry_agent:
                cmd.append("--dry-run")
            return _lab_invoke_script_caldera_dry(cmd, dry_run=dry_agent)
        if sub == "remove":
            if tail_flags:
                print(f"Unexpected arguments: {' '.join(tail_flags)}", file=sys.stderr)
                return 2
            return _lab_invoke_script_caldera_dry(["scenario", "agent", "remove"], dry_run=dry_agent)
    print(f"Unknown lab scenario subcommand: {head!r}", file=sys.stderr)
    return 2


@log_command
def lab_runtime_callback(argv: List[str], *, dry_run: bool) -> int:
    tokens, seen = _strip_flags(list(argv), ("--dry-run",))
    dry_run = dry_run or seen["--dry-run"]
    if not tokens:
        print(
            "Usage: aella_cli lab runtime summary|inspect|jsonl|operation|mirror|snapshots|"
            "evidence|validate|preview ...",
            file=sys.stderr,
        )
        return 2
    head, rest = tokens[0], tokens[1:]
    tail: List[str] = ["runtime", head, *rest]
    if head == "jsonl":
        if not rest or rest[0] != "tail":
            print(
                "Usage: aella_cli lab runtime jsonl tail [--lines N] [--filter REGEX] [--json] [--dry-run]",
                file=sys.stderr,
            )
            return 2
    elif head == "evidence":
        if not rest or rest[0] not in ("bundle", "export-jsonl"):
            print(
                "Usage: aella_cli lab runtime evidence bundle [--out DIR] [--dry-run]\n"
                "       aella_cli lab runtime evidence export-jsonl [--out FILE] [--lines N] [--dry-run]",
                file=sys.stderr,
            )
            return 2
    elif head == "validate":
        if not rest or rest[0] not in ("repeat", "stale", "cleanup", "consistency"):
            print(
                "Usage: aella_cli lab runtime validate repeat|stale|cleanup|consistency [--json] [--dry-run]",
                file=sys.stderr,
            )
            return 2
    elif head == "preview":
        pass
    elif head not in ("summary", "inspect", "operation", "mirror", "snapshots"):
        print(f"Unknown lab runtime subcommand: {head!r}", file=sys.stderr)
        return 2
    return _lab_invoke_script_caldera_dry(tail, dry_run=dry_run)


def do_lab(argv: List[str]) -> int:
    """
    Lab namespace dispatcher. argv is tokens after 'lab' (e.g. ['deploy','x',...]).
    """
    tokens, seen = _strip_flags(list(argv), ("--dry-run",))
    dry_run = seen["--dry-run"]
    if not tokens:
        sys.stdout.write(lab_command_help)
        return 2
    head, rest = tokens[0], tokens[1:]
    if head in ("-h", "--help", "help"):
        sys.stdout.write(lab_command_help)
        return 0

    lab_multi = {
        "mirror": lab_mirror_callback,
        "nat": lab_nat_callback,
        "web-console": lab_web_console_callback,
        "windows-console": lab_windows_console_callback,
        "access": lab_access_callback,
        "cleanup": lab_cleanup_callback,
        "snapshot": lab_snapshot_callback,
        "scenario": lab_scenario_callback,
        "runtime": lab_runtime_callback,
        "images": lab_images_callback,
    }
    fn_multi = lab_multi.get(head)
    if fn_multi is not None:
        return int(fn_multi(rest, dry_run=dry_run))

    dispatch = {
        "deploy": lab_deploy_callback,
        "download": lab_download_callback,
        "start": lab_start_callback,
        "stop": lab_stop_callback,
        "destroy": lab_destroy_callback,
        "status": lab_status_callback,
        "validate": lab_validate_callback,
    }
    fn = dispatch.get(head)
    if fn is None:
        print(f"Unknown lab subcommand: {head!r}", file=sys.stderr)
        sys.stdout.write(lab_command_help)
        return 2
    return int(fn(rest, dry_run=dry_run))


def lab_command_callback(argv: List[str]) -> int:
    """Root router entry for the `lab` command namespace."""
    return do_lab(argv)


@log_command
def cmd_appliance_status() -> int:
    rc, out, err = shell_cmd_exec(["uptime"])
    return _emit_streams(rc, out, err)


@log_command
def cmd_appliance_info() -> int:
    rc, out, err = shell_cmd_exec(["uname", "-a"])
    return _emit_streams(rc, out, err)


def appliance_command_callback(argv: List[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        sys.stdout.write(APPLIANCE_COMMAND_HELP)
        return 0 if argv else 2
    sub = argv[0]
    if sub == "status":
        if len(argv) > 1:
            print(f"Unexpected arguments: {' '.join(argv[1:])}", file=sys.stderr)
            return 2
        return cmd_appliance_status()
    if sub == "info":
        if len(argv) > 1:
            print(f"Unexpected arguments: {' '.join(argv[1:])}", file=sys.stderr)
            return 2
        return cmd_appliance_info()
    print(f"Unknown appliance subcommand: {sub!r}", file=sys.stderr)
    sys.stdout.write(APPLIANCE_COMMAND_HELP)
    return 2


def appliance_command_help() -> str:
    return APPLIANCE_COMMAND_HELP


def main(argv: Optional[Sequence[str]] = None) -> int:
    _configure_logging()
    argv_list = list(sys.argv[1:] if argv is None else argv)

    if not argv_list:
        sys.stdout.write(ROOT_COMMAND_HELP)
        return 2
    if argv_list[0] in ("-h", "--help", "help"):
        sys.stdout.write(ROOT_COMMAND_HELP)
        return 0

    head, *rest = argv_list
    try:
        if head == "appliance":
            return int(appliance_command_callback(rest))
        if head == "lab":
            return int(lab_command_callback(rest))
        print(f"Unknown command: {head!r}", file=sys.stderr)
        sys.stdout.write(ROOT_COMMAND_HELP)
        return 2
    except SystemExit as se:
        code = se.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 1
    except RuntimeError as exc:
        LOG.error(
            "structured_log",
            extra={"event": "handler_runtime_error", "error": str(exc)},
        )
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
