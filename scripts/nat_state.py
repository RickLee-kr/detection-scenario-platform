#!/usr/bin/env python3
"""Reverse-NAT validation helper for xdr-lab-vm-manager.sh.

READ-ONLY contract
==================
This module NEVER mutates iptables. It only invokes:

  * iptables -t nat  -S POSTROUTING
  * iptables -t nat  -S PREROUTING
  * iptables          -S FORWARD

…and projects the parsed reality into ${XDR_RUNTIME_STATE_DIR}/nat.json.

Authoritative mapping
=====================
The KVM Host Golden Image MUST already carry these rules. The validator
does NOT install, modify, or remove rules. The mapping is baked into
this module so that drift in lab-vms.json cannot silently break the
operator-facing port contract:

    sensor-vm       10.10.10.10  external tcp/1022 -> internal tcp/22
    victim-linux    10.10.10.20  external tcp/2022 -> internal tcp/22
    windows-victim  10.10.10.30  external tcp/3389 -> internal tcp/3389

Optional management (not iptables DNAT — see docs/web-console.md):
    windows-build / windows-victim via websockify (e.g. tcp/6081, tcp/6082)
    -> 127.0.0.1 QEMU VNC. Validated by validate-web-console.sh, not DNAT.

Full verify (without --iptables-only) may probe a legacy single listen port
and ${XDR_LAB_WEB_CONSOLE_DIR}/<vm>.json for observability only.

Subcommands
===========

  refresh   Probe iptables + listener, atomically write nat.json,
            exit 0 unconditionally (state is informational).
  verify    Same as refresh but exit 0 ONLY if every expected rule is
            present and no contradictory state is observed.
  status    Print the canonical nat.json record to stdout (no exit code
            verdict).

Forbidden patterns (constitution P-13):

  * No iptables -F / -X / -P / -A / -I / -D anywhere in this module.
  * No iptables-restore.
  * No mutation of the XDR_LAB_DNAT / XDR_LAB_FWD chains.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Authoritative mapping (Golden-Image contract — DO NOT mutate at runtime)
# ---------------------------------------------------------------------------

AUTHORITATIVE_LAB_SUBNET = "10.10.10.0/24"

AUTHORITATIVE_DNAT: list[dict[str, Any]] = [
    {
        "name": "sensor-vm-ssh",
        "vm": "sensor-vm",
        "internal_ip": "10.10.10.10",
        "internal_port": 22,
        "external_port": 1022,
        "proto": "tcp",
    },
    {
        "name": "victim-linux-ssh",
        "vm": "victim-linux",
        "internal_ip": "10.10.10.20",
        "internal_port": 22,
        "external_port": 2022,
        "proto": "tcp",
    },
    {
        "name": "windows-victim-rdp",
        "vm": "windows-victim",
        "internal_ip": "10.10.10.30",
        "internal_port": 3389,
        "external_port": 3389,
        "proto": "tcp",
    },
]

WEB_CONSOLE_EXTERNAL_PORT_DEFAULT = 6080
WEB_CONSOLE_VM_DEFAULT = "windows-victim"


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(cmd: list[str], *, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if not str(raw).strip():
        return default
    try:
        return int(str(raw).strip(), 10)
    except ValueError:
        return default


def detect_uplink_iface(lab_bridge: str = "br0") -> str | None:
    """Return the host egress NIC for lab MASQUERADE (-o), never hard-coded eth0."""
    env = os.environ.get("LAB_UPLINK_IFACE", "").strip()
    if env:
        return env

    vms_path = os.environ.get("XDR_LAB_VMS_JSON", "").strip()
    if not vms_path:
        xdr_root = os.environ.get("XDR_ROOT", "/opt/xdr-lab").strip() or "/opt/xdr-lab"
        vms_path = str(Path(xdr_root) / "config/lab-vms.json")
    if vms_path and Path(vms_path).is_file():
        try:
            data = json.loads(Path(vms_path).read_text(encoding="utf-8"))
            net = data.get("network") if isinstance(data, dict) else None
            if isinstance(net, dict):
                raw = str(net.get("uplink_interface") or "").strip()
                if raw and raw.lower() != "null":
                    return raw
        except (json.JSONDecodeError, OSError):
            pass

    for cmd in (
        ["ip", "-4", "route", "show", "default"],
        ["ip", "-4", "route", "get", "203.0.113.1"],
    ):
        p = _run(cmd, timeout=5.0)
        if p.returncode != 0:
            continue
        tokens = (p.stdout or "").split()
        for i, tok in enumerate(tokens):
            if tok == "dev" and i + 1 < len(tokens):
                dev = tokens[i + 1]
                if dev and dev != lab_bridge:
                    return dev
    return None


def primary_bind_ipv4() -> str | None:
    for dst in ("203.0.113.1", "192.0.2.1", "198.51.100.1"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(0.4)
                s.connect((dst, 80))
                ip = s.getsockname()[0]
                if ip and not str(ip).startswith("127."):
                    return str(ip)
        except OSError:
            continue
    return None


def tcp_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    if not host or port <= 0:
        return False
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# iptables read-only probes
# ---------------------------------------------------------------------------

class IptablesUnavailable(Exception):
    """iptables binary missing or rejected the read (e.g. EPERM)."""


def _iptables_S(table: str | None, chain: str) -> list[str]:
    """Return the lines of `iptables [-t TABLE] -S CHAIN`.

    Raises IptablesUnavailable on any error. Output is one rule per line,
    starting with "-A CHAIN ..." (or "-P CHAIN ..." for the policy line).
    """
    cmd = ["iptables"]
    if table:
        cmd += ["-t", table]
    cmd += ["-S", chain]
    p = _run(cmd, timeout=10.0)
    if p.returncode != 0:
        err = (p.stderr or "").strip().splitlines()
        tail = err[-1] if err else f"rc={p.returncode}"
        raise IptablesUnavailable(f"iptables {' '.join(cmd[1:])} failed: {tail}")
    return [ln.rstrip() for ln in (p.stdout or "").splitlines() if ln.strip()]


def _iptables_chain_or_empty(table: str | None, chain: str) -> list[str]:
    try:
        return _iptables_S(table, chain)
    except IptablesUnavailable:
        return []


def _collect_dnat_rule_lines(rules_prerouting: list[str]) -> list[str]:
    lines = list(rules_prerouting)
    lines.extend(_iptables_chain_or_empty("nat", "XDR_LAB_DNAT"))
    return lines


def _collect_forward_rule_lines(rules_forward: list[str]) -> list[str]:
    lines = list(rules_forward)
    lines.extend(_iptables_chain_or_empty(None, "XDR_LAB_FWD"))
    return lines


def _iptables_available() -> bool:
    try:
        # Cheapest read possible — list the built-in INPUT chain.
        _iptables_S(None, "INPUT")
        return True
    except IptablesUnavailable:
        return False


# ---------------------------------------------------------------------------
# Rule parsing (lenient — only matches on semantic fields, not flag order)
# ---------------------------------------------------------------------------

_ARG_TOKENS_REQUIRING_VALUE = {
    "-A", "-I", "-D", "-i", "-o", "-s", "-d", "-p", "-j", "-m",
    "--source", "--destination", "--dport", "--sport", "--to-destination",
    "--to-ports", "--in-interface", "--out-interface", "--ctstate",
}


def _tokenize_rule(line: str) -> list[str]:
    # iptables -S output is space-separated and never quotes; a naïve split
    # is sufficient for the rule shapes we expect.
    return line.split()


def _extract_dport(tokens: list[str]) -> int | None:
    # Look for "-m tcp --dport N" or "--dport N" anywhere.
    for i, t in enumerate(tokens):
        if t == "--dport" and i + 1 < len(tokens):
            try:
                return int(tokens[i + 1])
            except ValueError:
                return None
    return None


def _extract_proto(tokens: list[str]) -> str | None:
    for i, t in enumerate(tokens):
        if t in ("-p", "--protocol") and i + 1 < len(tokens):
            return tokens[i + 1].lower()
    return None


def _extract_to_destination(tokens: list[str]) -> tuple[str | None, int | None]:
    for i, t in enumerate(tokens):
        if t == "--to-destination" and i + 1 < len(tokens):
            spec = tokens[i + 1]
            # Accept "ip", "ip:port", or "ip:port-port" (range; we keep the
            # first port for the equality check).
            host, _, rest = spec.partition(":")
            port_str = rest.split("-", 1)[0] if rest else ""
            try:
                port_val = int(port_str) if port_str else None
            except ValueError:
                port_val = None
            return host or None, port_val
    return None, None


def _extract_jump(tokens: list[str]) -> str | None:
    for i, t in enumerate(tokens):
        if t in ("-j", "--jump") and i + 1 < len(tokens):
            return tokens[i + 1]
    return None


def _extract_source(tokens: list[str]) -> str | None:
    for i, t in enumerate(tokens):
        if t in ("-s", "--source") and i + 1 < len(tokens):
            return tokens[i + 1]
    return None


def _extract_destination(tokens: list[str]) -> str | None:
    for i, t in enumerate(tokens):
        if t in ("-d", "--destination") and i + 1 < len(tokens):
            return tokens[i + 1]
    return None


def _extract_out_interface(tokens: list[str]) -> str | None:
    for i, t in enumerate(tokens):
        if t in ("-o", "--out-interface") and i + 1 < len(tokens):
            return tokens[i + 1]
    return None


def _extract_in_interface(tokens: list[str]) -> str | None:
    for i, t in enumerate(tokens):
        if t in ("-i", "--in-interface") and i + 1 < len(tokens):
            return tokens[i + 1]
    return None


def _normalize_cidr(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    # iptables -S may print a /32 or /24 explicitly; treat bare IPs as /32.
    if "/" not in v:
        return f"{v}/32"
    return v


# ---------------------------------------------------------------------------
# State assembly
# ---------------------------------------------------------------------------

def inspect_masquerade(
    rules_postrouting: list[str],
    *,
    expected_uplink: str | None = None,
    lab_bridge: str = "br0",
) -> dict[str, Any]:
    matching: list[str] = []
    expected = AUTHORITATIVE_LAB_SUBNET
    for ln in rules_postrouting:
        toks = _tokenize_rule(ln)
        if not toks or toks[0] != "-A":
            continue
        if _extract_jump(toks) != "MASQUERADE":
            continue
        src = _normalize_cidr(_extract_source(toks))
        if src != expected:
            continue
        out_if = _extract_out_interface(toks)
        if out_if == lab_bridge:
            continue
        if expected_uplink:
            if out_if != expected_uplink:
                continue
        elif out_if is None:
            # No uplink detected — accept legacy unscoped lab MASQUERADE.
            pass
        matching.append(ln)
    return {
        "expected_source_cidr": expected,
        "expected_uplink_interface": expected_uplink,
        "present": bool(matching),
        "matching_rules": matching,
    }


def inspect_forward(rules_forward: list[str]) -> dict[str, Any]:
    matching: list[str] = []
    expected = AUTHORITATIVE_LAB_SUBNET
    all_lines = _collect_forward_rule_lines(rules_forward)
    for ln in all_lines:
        toks = _tokenize_rule(ln)
        if not toks or toks[0] != "-A":
            continue
        if _extract_jump(toks) != "ACCEPT":
            continue
        src = _normalize_cidr(_extract_source(toks))
        dst = _normalize_cidr(_extract_destination(toks))
        out_if = _extract_out_interface(toks)
        in_if = _extract_in_interface(toks)
        # Golden Image may scope by subnet or by lab bridge attachment.
        if (
            src == expected
            or dst == expected
            or out_if == "br0"
            or in_if == "br0"
        ):
            matching.append(ln)
    return {
        "expected_subnet": expected,
        "present": bool(matching),
        "matching_rules": matching,
    }


def inspect_dnat(rules_prerouting: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    all_lines = _collect_dnat_rule_lines(rules_prerouting)
    for mapping in AUTHORITATIVE_DNAT:
        proto = str(mapping["proto"]).lower()
        ext = int(mapping["external_port"])
        ip = str(mapping["internal_ip"])
        ip_port = int(mapping["internal_port"])
        matches: list[str] = []
        for ln in all_lines:
            toks = _tokenize_rule(ln)
            if not toks or toks[0] != "-A":
                continue
            if _extract_jump(toks) != "DNAT":
                continue
            if (_extract_proto(toks) or "") != proto:
                continue
            if _extract_dport(toks) != ext:
                continue
            host, hport = _extract_to_destination(toks)
            if host != ip:
                continue
            # Allow the kernel to print `--to-destination 10.10.10.10:22`
            # *or* the broader form without a port (rare); when a port is
            # printed, it MUST match the contract.
            if hport is not None and hport != ip_port:
                continue
            matches.append(ln)
        rec = dict(mapping)
        rec["expected_to_destination"] = f"{ip}:{ip_port}"
        rec["present"] = bool(matches)
        rec["matching_rules"] = matches
        out.append(rec)
    return out


def inspect_web_console(
    *,
    listen_port: int,
    manifest_dir: Path,
    vm: str,
) -> dict[str, Any]:
    listen_local = tcp_port_open("127.0.0.1", listen_port)
    ext_ip = primary_bind_ipv4()
    listen_external = bool(ext_ip and tcp_port_open(str(ext_ip), listen_port))

    manifest_path = manifest_dir / f"{vm}.json"
    manifest_present = manifest_path.is_file()
    manifest_pid: int | None = None
    manifest_listen: int | None = None
    manifest_target: int | None = None
    if manifest_present:
        try:
            rec = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(rec, dict):
                try:
                    manifest_pid = int(rec.get("websockify_pid"))
                except (TypeError, ValueError):
                    manifest_pid = None
                try:
                    manifest_listen = int(rec.get("listen_port"))
                except (TypeError, ValueError):
                    manifest_listen = None
                try:
                    manifest_target = int(rec.get("target_port"))
                except (TypeError, ValueError):
                    manifest_target = None
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "expected_external_port": listen_port,
        "expected_handler": "websockify+noVNC (local, not iptables)",
        "vm": vm,
        "listen_local": listen_local,
        "listen_external": listen_external,
        "external_ip": ext_ip,
        "manifest_path": str(manifest_path),
        "manifest_present": manifest_present,
        "manifest_listen_port": manifest_listen,
        "manifest_target_port": manifest_target,
        "manifest_pid": manifest_pid,
        # The contract is "port 6080 must be listening locally". External
        # reachability is informational (firewall rules upstream may scope
        # access); we report it but do not treat it as a hard failure.
        "present": listen_local,
    }


def build_state_record(
    *,
    web_console_port: int,
    web_console_dir: Path,
    web_console_vm: str,
    iptables_only: bool = False,
) -> dict[str, Any]:
    iptables_ok = _iptables_available()
    iptables_error: str | None = None

    post: list[str] = []
    pre: list[str] = []
    fwd: list[str] = []
    if iptables_ok:
        try:
            post = _iptables_S("nat", "POSTROUTING")
            pre = _iptables_S("nat", "PREROUTING")
            fwd = _iptables_S(None, "FORWARD")
        except IptablesUnavailable as exc:
            iptables_ok = False
            iptables_error = str(exc)
    else:
        iptables_error = "iptables read failed (binary missing or permission denied)"

    masq = inspect_masquerade(
        post,
        expected_uplink=detect_uplink_iface(
            lab_bridge=os.environ.get("LAB_BRIDGE", "br0").strip() or "br0"
        ),
        lab_bridge=os.environ.get("LAB_BRIDGE", "br0").strip() or "br0",
    )
    fwd_rec = inspect_forward(fwd)
    dnat_rec = inspect_dnat(pre)
    web_rec = inspect_web_console(
        listen_port=web_console_port,
        manifest_dir=web_console_dir,
        vm=web_console_vm,
    )

    missing: list[str] = []
    if iptables_ok:
        if not masq["present"]:
            missing.append("masquerade")
        if not fwd_rec["present"]:
            missing.append("forward_accept")
        for d in dnat_rec:
            if not d["present"]:
                missing.append(d["name"])
    else:
        missing.append("iptables_unreadable")
    if not web_rec["present"] and not iptables_only:
        missing.append(f"web_console_listen_{int(web_console_port)}")

    consistent = bool(
        iptables_ok
        and masq["present"]
        and fwd_rec["present"]
        and all(d["present"] for d in dnat_rec)
        and (iptables_only or web_rec["present"])
    )

    return {
        "ts": utc_now(),
        "consistent": consistent,
        "iptables_only": iptables_only,
        "iptables_readable": iptables_ok,
        "iptables_error": iptables_error,
        "authoritative_lab_subnet": AUTHORITATIVE_LAB_SUBNET,
        "masquerade": masq,
        "forward": fwd_rec,
        "dnat": dnat_rec,
        "web_console": web_rec,
        "missing": missing,
        "raw_postrouting": post,
        "raw_prerouting": pre,
        "raw_forward": fwd,
        "last_verified_time": utc_now(),
    }


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def _default_state_path() -> Path:
    env_path = os.environ.get("XDR_LAB_NAT_STATE_JSON", "").strip()
    if env_path:
        return Path(env_path)
    xdr_root = os.environ.get("XDR_ROOT", "/opt/xdr-lab").strip() or "/opt/xdr-lab"
    return Path(xdr_root) / "runtime/state/nat.json"


def _resolve_state_path(args: argparse.Namespace) -> Path:
    raw = str(getattr(args, "state_path", "") or "").strip()
    if raw:
        return Path(raw)
    return _default_state_path()


def _resolve_web_console_dir(args: argparse.Namespace) -> Path:
    raw = str(getattr(args, "web_console_dir", "") or "").strip()
    if raw:
        return Path(raw)
    env_dir = os.environ.get("XDR_LAB_WEB_CONSOLE_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    return _resolve_state_path(args).parent.parent / "web-console"


def _resolve_web_console_port(args: argparse.Namespace) -> int:
    if getattr(args, "web_console_port", None):
        return int(args.web_console_port)
    return env_int("XDR_LAB_WEB_CONSOLE_PORT", WEB_CONSOLE_EXTERNAL_PORT_DEFAULT)


def _resolve_web_console_vm(args: argparse.Namespace) -> str:
    vm = str(getattr(args, "web_console_vm", "") or "").strip()
    if vm:
        return vm
    return os.environ.get("XDR_LAB_WEB_CONSOLE_VM", WEB_CONSOLE_VM_DEFAULT) or WEB_CONSOLE_VM_DEFAULT


def cmd_refresh(args: argparse.Namespace) -> int:
    rec = build_state_record(
        web_console_port=_resolve_web_console_port(args),
        web_console_dir=_resolve_web_console_dir(args),
        web_console_vm=_resolve_web_console_vm(args),
        iptables_only=bool(getattr(args, "iptables_only", False)),
    )
    atomic_write_json(_resolve_state_path(args), rec)
    if args.print_json:
        sys.stdout.write(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    iptables_only = bool(getattr(args, "iptables_only", False))
    rec = build_state_record(
        web_console_port=_resolve_web_console_port(args),
        web_console_dir=_resolve_web_console_dir(args),
        web_console_vm=_resolve_web_console_vm(args),
        iptables_only=iptables_only,
    )
    atomic_write_json(_resolve_state_path(args), rec)
    if args.print_json:
        sys.stdout.write(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    return 0 if rec["consistent"] else 1


def cmd_status(args: argparse.Namespace) -> int:
    path = _resolve_state_path(args)
    if not path.is_file():
        # No state yet — synthesize one without writing so `status` stays
        # purely informational (caller picks whether to persist).
        rec = build_state_record(
            web_console_port=_resolve_web_console_port(args),
            web_console_dir=_resolve_web_console_dir(args),
            web_console_vm=_resolve_web_console_vm(args),
        )
        sys.stdout.write(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
        return 0
    sys.stdout.write(path.read_text(encoding="utf-8"))
    return 0


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------

def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--state-path",
        default="",
        help="Path to runtime/state/nat.json (default: env "
        "XDR_LAB_NAT_STATE_JSON or ${XDR_ROOT}/runtime/state/nat.json).",
    )
    p.add_argument(
        "--web-console-port",
        type=int,
        default=None,
        help="Override web-console listen port (default: env "
        "XDR_LAB_WEB_CONSOLE_PORT or 6080).",
    )
    p.add_argument(
        "--web-console-dir",
        default="",
        help="Override per-VM web-console manifest dir. Default: env "
        "XDR_LAB_WEB_CONSOLE_DIR or <state-path>/../web-console.",
    )
    p.add_argument(
        "--web-console-vm",
        default="",
        help="VM name whose web-console manifest to consult "
        "(default: windows-victim).",
    )
    p.add_argument("--print-json", action="store_true")
    p.add_argument(
        "--iptables-only",
        action="store_true",
        help="Verify only MASQUERADE/DNAT/FORWARD contract (skip web-console listener).",
    )


class GlobalTimeout(Exception):
    """Raised when XDR_LAB_NAT_STATE_GLOBAL_TIMEOUT_SECS elapses."""


def _global_timeout_handler(_signum: int, _frame: object) -> None:
    raise GlobalTimeout("nat_state.py global timeout")


def _arm_global_timeout() -> None:
    secs = env_int("XDR_LAB_NAT_STATE_GLOBAL_TIMEOUT_SECS", 90)
    if secs <= 0:
        return
    signal.signal(signal.SIGALRM, _global_timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, float(secs))


def _disarm_global_timeout() -> None:
    signal.setitimer(signal.ITIMER_REAL, 0.0)


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Read-only reverse-NAT validator for the XDR Lab "
        "Golden-Image contract."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("refresh", help="Refresh nat.json (exit 0).")
    _add_common(r)
    r.set_defaults(func=cmd_refresh)

    v = sub.add_parser("verify",
                       help="Refresh nat.json and exit non-zero if inconsistent.")
    _add_common(v)
    v.set_defaults(func=cmd_verify)

    s = sub.add_parser("status",
                       help="Print the current nat.json (or a fresh probe if "
                       "the file is absent).")
    _add_common(s)
    s.set_defaults(func=cmd_status)

    args = ap.parse_args(list(argv) if argv is not None else None)
    _arm_global_timeout()
    try:
        return int(args.func(args))
    except GlobalTimeout:
        print("nat_state.py: global timeout exceeded", file=sys.stderr)
        return 124
    finally:
        _disarm_global_timeout()


if __name__ == "__main__":
    raise SystemExit(main())
