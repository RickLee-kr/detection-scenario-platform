#!/usr/bin/env python3
"""OVS mirror state probe + traffic validation helper for xdr-lab-vm-manager.sh.

Authoritative responsibilities (read-only by default):
  * Discover the libvirt-managed vnet interface of the sensor VM on a given
    OVS bridge (no hard-coded vnetN — interface numbers shift across reboots).
  * Inspect ovs-vsctl reality (bridge presence, daemon health, mirror entry,
    output-port linkage) and reconcile it against the desired identity
    (bridge, mirror_name, sensor_vm).
  * Materialize ${XDR_RUNTIME_STATE_DIR}/mirror.json atomically.
  * Drive the traffic-mirroring validation flow over SSH (sensor tcpdump +
    host-side probe) without ever modifying OVS state on failure.

This module performs NO destructive ovs-vsctl actions. The shell layer
(xdr-lab-vm-manager.sh::apply_ovs_mirror) owns mutations and calls this
helper for inspection and JSON state refresh.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Time / IO primitives
# ---------------------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(cmd: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
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


def _load_prev(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# OVS / virsh primitives (read-only)
# ---------------------------------------------------------------------------

def ovs_running() -> bool:
    """ovs-vsctl show returns rc=0 iff ovsdb-server + ovs-vswitchd are usable."""
    if not _which("ovs-vsctl"):
        return False
    return _run(["ovs-vsctl", "show"], timeout=10).returncode == 0


def ovs_bridge_exists(bridge: str) -> bool:
    if not _which("ovs-vsctl"):
        return False
    return _run(["ovs-vsctl", "br-exists", bridge], timeout=10).returncode == 0


def ovs_list_ports(bridge: str) -> list[str]:
    p = _run(["ovs-vsctl", "list-ports", bridge], timeout=10)
    if p.returncode != 0:
        return []
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]


def ovs_mirror_uuid(name: str) -> str:
    """Return the OVS _uuid of the named mirror, or '' if absent."""
    p = _run(
        ["ovs-vsctl", "--columns=_uuid", "--bare", "find", "mirror", f"name={name}"],
        timeout=10,
    )
    if p.returncode != 0:
        return ""
    line = (p.stdout or "").strip().splitlines()
    return line[0].strip() if line else ""


def ovs_mirror_output_port_uuid(mirror_uuid: str) -> str:
    if not mirror_uuid:
        return ""
    p = _run(
        ["ovs-vsctl", "--columns=output_port", "--bare", "list", "mirror", mirror_uuid],
        timeout=10,
    )
    if p.returncode != 0:
        return ""
    return (p.stdout or "").strip()


def ovs_port_name_by_uuid(port_uuid: str) -> str:
    if not port_uuid:
        return ""
    p = _run(["ovs-vsctl", "--columns=name", "--bare", "list", "port", port_uuid], timeout=10)
    if p.returncode != 0:
        return ""
    return (p.stdout or "").strip()


def ovs_bridge_mirrors(bridge: str) -> list[str]:
    """Return the list of mirror UUIDs attached to the bridge."""
    p = _run(
        ["ovs-vsctl", "--columns=mirrors", "--bare", "list", "bridge", bridge],
        timeout=10,
    )
    if p.returncode != 0:
        return []
    raw = (p.stdout or "").strip()
    if not raw or raw == "[]":
        return []
    # ovs-vsctl bare format: "uuid1\nuuid2" or "uuid1 uuid2".
    return [tok.strip() for tok in re.split(r"[\s,]+", raw) if tok.strip()]


def virsh_domiflist(vm: str) -> list[dict[str, str]]:
    """Parse `virsh domiflist <vm>` into row dicts.

    Output columns are: Interface | Type | Source | Model | MAC.
    """
    p = _run(["virsh", "domiflist", vm], timeout=15)
    if p.returncode != 0:
        return []
    rows: list[dict[str, str]] = []
    for line in (p.stdout or "").splitlines():
        s = line.strip()
        if not s or s.startswith("---") or s.lower().startswith("interface"):
            continue
        parts = s.split()
        if len(parts) < 5:
            continue
        rows.append(
            {
                "interface": parts[0],
                "type": parts[1],
                "source": parts[2],
                "model": parts[3],
                "mac": parts[4],
            }
        )
    return rows


def virsh_domstate(vm: str) -> str:
    p = _run(["virsh", "domstate", vm], timeout=10)
    if p.returncode != 0:
        return ""
    out = (p.stdout or "").strip().splitlines()
    return out[-1].strip() if out else ""


def _which(cmd: str) -> bool:
    return subprocess.run(["sh", "-lc", f"command -v {shlex.quote(cmd)}"],
                          capture_output=True, text=True, check=False).returncode == 0


# ---------------------------------------------------------------------------
# Sensor interface auto-discovery
# ---------------------------------------------------------------------------

def discover_sensor_iface(vm: str, bridge: str) -> str:
    """Return the vnetX interface of `vm` attached to `bridge` on the host OVS.

    Strategy:
      1. virsh domiflist <vm> — yields rows that expose libvirt's notion of the
         backing host interface (column "Interface") and the source bridge.
      2. Cross-check ovs-vsctl list-ports <bridge> — only return rows whose
         interface actually shows up on the live OVS bridge (covers the case
         where libvirt thinks it attached but the port hasn't surfaced yet).
      3. Prefer rows whose Source equals <bridge>. Fall back to bridge-side
         lookup by MAC if Source doesn't match (e.g. libvirt network alias).

    Empty string means "not discoverable right now"; callers must NEVER apply
    a mirror in that case.
    """
    rows = virsh_domiflist(vm)
    if not rows:
        return ""

    live_ports = set(ovs_list_ports(bridge))

    # Pass 1: exact source==bridge match where iface exists on the bridge.
    for row in rows:
        if row["source"] == bridge and row["interface"] in live_ports:
            return row["interface"]

    # Pass 2: any libvirt iface present on the bridge (covers ovs-net source).
    for row in rows:
        if row["interface"] in live_ports:
            return row["interface"]

    return ""


# ---------------------------------------------------------------------------
# Mirror state inspection & idempotency
# ---------------------------------------------------------------------------

def inspect_mirror_state(
    *,
    bridge: str,
    mirror_name: str,
    sensor_vm: str,
) -> dict[str, Any]:
    """Build the canonical mirror state record. Pure observation, no mutation."""
    ovs_ok = ovs_running()
    bridge_ok = ovs_bridge_exists(bridge) if ovs_ok else False
    sensor_iface = discover_sensor_iface(sensor_vm, bridge) if bridge_ok else ""

    mirror_uuid = ovs_mirror_uuid(mirror_name) if ovs_ok else ""
    mirror_exists = bool(mirror_uuid)

    # Mirror must be attached to *this* bridge (a stray mirror with same name
    # on another bridge is not "our" mirror).
    attached_to_bridge = False
    if mirror_uuid and bridge_ok:
        attached_to_bridge = mirror_uuid in ovs_bridge_mirrors(bridge)

    output_port_uuid = ovs_mirror_output_port_uuid(mirror_uuid)
    output_port_name = ovs_port_name_by_uuid(output_port_uuid) if output_port_uuid else ""
    output_port_exists = bool(output_port_name)

    output_port_matches_sensor = (
        bool(output_port_name)
        and bool(sensor_iface)
        and output_port_name == sensor_iface
    )

    consistent = bool(
        ovs_ok
        and bridge_ok
        and mirror_exists
        and attached_to_bridge
        and output_port_exists
        and output_port_matches_sensor
    )

    return {
        "ovs_running": ovs_ok,
        "bridge": bridge,
        "bridge_exists": bridge_ok,
        "mirror_name": mirror_name,
        "mirror_exists": mirror_exists,
        "mirror_uuid": mirror_uuid or None,
        "mirror_attached_to_bridge": attached_to_bridge,
        "sensor_vm": sensor_vm,
        "sensor_interface": sensor_iface or None,
        "sensor_vm_state": virsh_domstate(sensor_vm) or None,
        "output_port_name": output_port_name or None,
        "output_port_exists": output_port_exists,
        "output_port_matches_sensor": output_port_matches_sensor,
        "consistent": consistent,
    }


def build_state_record(
    *,
    bridge: str,
    mirror_name: str,
    sensor_vm: str,
    state_path: Path,
    touch_applied: bool,
) -> dict[str, Any]:
    """Merge a fresh inspection with the previous record, preserving history."""
    prev = _load_prev(state_path)
    obs = inspect_mirror_state(
        bridge=bridge,
        mirror_name=mirror_name,
        sensor_vm=sensor_vm,
    )

    now = utc_now()
    last_applied = prev.get("last_applied_time")
    if touch_applied and obs["consistent"]:
        last_applied = now
    if not isinstance(last_applied, str):
        last_applied = None

    return {
        "bridge": obs["bridge"],
        "mirror_name": obs["mirror_name"],
        "sensor_vm": obs["sensor_vm"],
        "sensor_interface": obs["sensor_interface"],
        "sensor_vm_state": obs["sensor_vm_state"],
        "ovs_running": obs["ovs_running"],
        "bridge_exists": obs["bridge_exists"],
        "mirror_exists": obs["mirror_exists"],
        "mirror_uuid": obs["mirror_uuid"],
        "mirror_attached_to_bridge": obs["mirror_attached_to_bridge"],
        "output_port_name": obs["output_port_name"],
        "output_port_exists": obs["output_port_exists"],
        "output_port_matches_sensor": obs["output_port_matches_sensor"],
        "consistent": obs["consistent"],
        "last_applied_time": last_applied,
        "last_verified_time": now,
    }


# ---------------------------------------------------------------------------
# SSH-driven traffic validation
# ---------------------------------------------------------------------------

_SSH_OPTS = (
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "ConnectTimeout=8",
)


def _ssh_invoke(
    host: str,
    user: str,
    remote: str,
    *,
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    cmd = ["ssh", *_SSH_OPTS, f"{user}@{host}", "sh", "-lc", remote]
    return _run(cmd, timeout=timeout)


def validate_traffic(
    *,
    sensor_ip: str,
    sensor_user: str,
    sensor_iface: str,
    probe_target: str,
    probe_source: str,
    packet_count: int,
    tcpdump_timeout: int,
) -> dict[str, Any]:
    """Run tcpdump on the sensor while a probe is fired from the host.

    Strict no-op on failure: this routine never alters OVS or libvirt state.
    Returns a structured outcome dict (always JSON-serializable).
    """
    out: dict[str, Any] = {
        "attempted": True,
        "sensor_ip": sensor_ip,
        "sensor_iface": sensor_iface,
        "probe_target": probe_target,
        "probe_source": probe_source,
        "packet_count_requested": packet_count,
        "tcpdump_started": False,
        "tcpdump_exit_code": None,
        "tcpdump_lines": 0,
        "tcpdump_excerpt": "",
        "probe_exit_code": None,
        "success": False,
        "reason": "",
        "timestamp": utc_now(),
    }

    if not sensor_ip or not sensor_user or not sensor_iface:
        out["reason"] = "missing_parameters"
        return out

    # Reachability precondition — never proceed against an unreachable sensor.
    reach = _ssh_invoke(sensor_ip, sensor_user, "true", timeout=12.0)
    if reach.returncode != 0:
        out["reason"] = "sensor_ssh_unreachable"
        return out

    # tcpdump command: bounded by packet count *and* a wall-clock timeout so
    # we never hang waiting for traffic that the mirror is failing to deliver.
    tdump_remote = (
        f"sudo -n timeout {int(tcpdump_timeout)} tcpdump "
        f"-nn -i {shlex.quote(sensor_iface)} -c {int(packet_count)} "
        f"'icmp and host {shlex.quote(probe_target)}' 2>/dev/null"
    )
    # Start tcpdump in the background — we want the probe to fire while it's
    # listening. We capture stdout via a heredoc-driven script.
    bg_script = (
        "set +e\n"
        "outf=$(mktemp)\n"
        f"({tdump_remote}) >\"$outf\" 2>/dev/null &\n"
        "pid=$!\n"
        "echo PID=$pid\n"
        "echo OUTF=$outf\n"
    )
    started = _ssh_invoke(sensor_ip, sensor_user, bg_script, timeout=20.0)
    if started.returncode != 0:
        out["reason"] = "tcpdump_launch_failed"
        return out

    pid = ""
    outf = ""
    for ln in (started.stdout or "").splitlines():
        if ln.startswith("PID="):
            pid = ln.split("=", 1)[1].strip()
        elif ln.startswith("OUTF="):
            outf = ln.split("=", 1)[1].strip()
    if not pid or not outf:
        out["reason"] = "tcpdump_launch_parse_failed"
        return out
    out["tcpdump_started"] = True

    # Fire the probe locally (host -> probe_target). We run ping with a
    # bounded count; whether it succeeds is secondary — the sensor must see
    # mirrored traffic for the lab to be operational. The probe is *only*
    # informational; failure here doesn't destroy state.
    probe = _run(
        ["ping", "-c", str(int(packet_count) + 2), "-W", "2", probe_target],
        timeout=tcpdump_timeout + 5,
    )
    out["probe_exit_code"] = probe.returncode

    # Wait for tcpdump to finish (it self-bounds via -c / timeout).
    wait_script = (
        f"wait {shlex.quote(pid)} 2>/dev/null; rc=$?; "
        f"echo RC=$rc; cat {shlex.quote(outf)}; rm -f {shlex.quote(outf)}"
    )
    finished = _ssh_invoke(sensor_ip, sensor_user, wait_script,
                           timeout=tcpdump_timeout + 15.0)
    body = finished.stdout or ""
    rc_line = next((ln for ln in body.splitlines() if ln.startswith("RC=")), "")
    try:
        out["tcpdump_exit_code"] = int(rc_line.split("=", 1)[1]) if rc_line else None
    except ValueError:
        out["tcpdump_exit_code"] = None
    tail = "\n".join(ln for ln in body.splitlines() if not ln.startswith("RC="))
    out["tcpdump_lines"] = sum(1 for ln in tail.splitlines() if ln.strip())
    out["tcpdump_excerpt"] = "\n".join(tail.splitlines()[:5])

    out["success"] = out["tcpdump_lines"] > 0
    if not out["success"]:
        out["reason"] = "no_mirrored_packets_observed"
    return out


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_discover_iface(args: argparse.Namespace) -> int:
    iface = discover_sensor_iface(args.vm, args.bridge)
    if iface:
        sys.stdout.write(iface + "\n")
        return 0
    return 1


def cmd_inspect(args: argparse.Namespace) -> int:
    obs = inspect_mirror_state(
        bridge=args.bridge,
        mirror_name=args.mirror_name,
        sensor_vm=args.sensor_vm,
    )
    sys.stdout.write(json.dumps(obs, ensure_ascii=False) + "\n")
    return 0 if obs["consistent"] else 1


def cmd_refresh(args: argparse.Namespace) -> int:
    state_path = Path(args.state_path)
    rec = build_state_record(
        bridge=args.bridge,
        mirror_name=args.mirror_name,
        sensor_vm=args.sensor_vm,
        state_path=state_path,
        touch_applied=bool(args.touch_applied),
    )
    atomic_write_json(state_path, rec)
    if args.print_json:
        sys.stdout.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return 0 if rec["consistent"] else 1


def cmd_verify(args: argparse.Namespace) -> int:
    """Refresh state and return non-zero unless the mirror is consistent.

    The CLI exit code is the operator-visible verdict; the state JSON is
    refreshed regardless so downstream tooling can read the diagnosis.
    """
    return cmd_refresh(args)


def cmd_validate_traffic(args: argparse.Namespace) -> int:
    result = validate_traffic(
        sensor_ip=args.sensor_ip,
        sensor_user=args.sensor_user,
        sensor_iface=args.sensor_iface,
        probe_target=args.probe_target,
        probe_source=args.probe_source or "host",
        packet_count=args.packet_count,
        tcpdump_timeout=args.tcpdump_timeout,
    )
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0 if result["success"] else 1


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------

def _add_identity_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--bridge", required=True)
    p.add_argument("--mirror-name", required=True)
    p.add_argument("--sensor-vm", required=True)


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover-iface", help="Print sensor VM's vnetX on bridge")
    d.add_argument("--vm", required=True)
    d.add_argument("--bridge", required=True)
    d.set_defaults(func=cmd_discover_iface)

    i = sub.add_parser("inspect", help="Print current OVS mirror observation as JSON")
    _add_identity_args(i)
    i.set_defaults(func=cmd_inspect)

    r = sub.add_parser("refresh", help="Refresh ${state}/mirror.json from OVS reality")
    _add_identity_args(r)
    r.add_argument("--state-path", required=True)
    r.add_argument("--touch-applied", action="store_true",
                   help="Bump last_applied_time when state is consistent")
    r.add_argument("--print-json", action="store_true")
    r.set_defaults(func=cmd_refresh)

    v = sub.add_parser("verify", help="Refresh state and exit non-zero if inconsistent")
    _add_identity_args(v)
    v.add_argument("--state-path", required=True)
    v.add_argument("--touch-applied", action="store_true")
    v.add_argument("--print-json", action="store_true")
    v.set_defaults(func=cmd_verify)

    t = sub.add_parser("validate-traffic",
                       help="Run sensor tcpdump + host probe (no destructive actions)")
    t.add_argument("--sensor-ip", required=True)
    t.add_argument("--sensor-user", required=True)
    t.add_argument("--sensor-iface", required=True)
    t.add_argument("--probe-target", required=True)
    t.add_argument("--probe-source", default="host")
    t.add_argument("--packet-count", type=int, default=5)
    t.add_argument("--tcpdump-timeout", type=int, default=20)
    t.set_defaults(func=cmd_validate_traffic)

    args = ap.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
