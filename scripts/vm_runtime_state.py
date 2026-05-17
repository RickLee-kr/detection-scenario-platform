#!/usr/bin/env python3
"""Runtime VM state probe + idempotent JSON merge for xdr-lab-vm-manager.sh.

Reads lab-vms.json and libvirt reality; writes ${XDR_RUNTIME_STATE_DIR}/<vm>.json.
Designed for repeated invocation (deploy/status/validate).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _virsh(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["virsh", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def domain_exists(vm: str) -> bool:
    return _virsh("dominfo", vm).returncode == 0


def domstate(vm: str) -> str:
    p = _virsh("domstate", vm)
    if p.returncode != 0:
        return ""
    return (p.stdout or "").strip().splitlines()[-1].strip() if p.stdout else ""


def collect_domifaddr_ipv4(vm: str) -> list[str]:
    ips: list[str] = []
    for src in ("lease", "agent"):
        p = _virsh("domifaddr", vm, "--source", src)
        if p.returncode != 0 or not p.stdout:
            continue
        for m in re.finditer(r"\b(\d{1,3}(?:\.\d{1,3}){3})/\d+\b", p.stdout):
            ips.append(m.group(1))
    return ips


def snapshot_count(vm: str) -> int:
    if not domain_exists(vm):
        return 0
    p = _virsh("snapshot-list", "--domain", vm, "--name")
    if p.returncode != 0 or not p.stdout:
        return 0
    lines = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
    return len(lines)


def ssh_batch_true(host: str, user: str) -> bool:
    if not host or not user:
        return False
    return (
        subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "ConnectTimeout=8",
                f"{user}@{host}",
                "true",
            ],
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )


def tcp_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    if not host or port <= 0:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def load_json_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


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


def pid_running(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if not str(raw).strip():
        return default
    try:
        return int(str(raw).strip(), 10)
    except ValueError:
        return default


def windows_emergency_vnc_state(
    *,
    vm_running: bool,
    vnc_disp: str | None,
    vnc_port: int | None,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    last_verified = manifest.get("last_verified")
    if not isinstance(last_verified, str):
        last_verified = None

    ext_default = env_int("XDR_LAB_VNC_EXTERNAL_PORT", 15900)
    ext_from_manifest: int | None = None
    try:
        if manifest.get("external_port") is not None and str(manifest.get("external_port")).strip():
            ext_from_manifest = int(manifest["external_port"])
    except (TypeError, ValueError):
        ext_from_manifest = None
    ext_port = ext_from_manifest if ext_from_manifest is not None else ext_default

    pid: int | None = None
    try:
        if manifest.get("socat_pid") is not None and str(manifest.get("socat_pid")).strip():
            pid = int(manifest["socat_pid"])
    except (TypeError, ValueError):
        pid = None

    mf_internal: int | None = None
    try:
        if manifest.get("internal_port") is not None and str(manifest.get("internal_port")).strip():
            mf_internal = int(manifest["internal_port"])
    except (TypeError, ValueError):
        mf_internal = None

    internal_match = (
        mf_internal is not None and vnc_port is not None and mf_internal == vnc_port
    )
    vnc_proxy_running = bool(
        manifest
        and pid_running(pid)
        and internal_match
        and manifest.get("external_port") is not None
    )

    bind_mode_raw = manifest.get("vnc_bind_mode")
    if isinstance(bind_mode_raw, str) and bind_mode_raw.strip():
        bind_mode: str | None = bind_mode_raw.strip()
    elif manifest:
        bind_mode = "localhost-proxy"
    else:
        bind_mode = None

    vnc_disp_ok = bool(vnc_disp and str(vnc_disp).strip())

    internal_tcp = bool(vnc_port and tcp_port_open("127.0.0.1", int(vnc_port)))
    ext_ip = primary_bind_ipv4()
    ext_tcp = bool(
        vnc_proxy_running
        and ext_ip is not None
        and tcp_port_open(str(ext_ip), int(ext_port))
    )

    emergency_console_available = bool(
        vm_running
        and vnc_disp_ok
        and vnc_port is not None
        and internal_tcp
        and vnc_proxy_running
        and ext_tcp
    )

    return {
        "emergency_console_available": emergency_console_available,
        "vnc_external_port": int(ext_port),
        "vnc_bind_mode": bind_mode,
        "vnc_proxy_running": vnc_proxy_running,
        "emergency_console_last_verified": last_verified,
    }


def novnc_assets_present() -> bool:
    for root in ("/usr/share/novnc", "/usr/share/javascript/novnc"):
        if (Path(root) / "vnc.html").is_file():
            return True
    return False


def windows_web_console_state(
    *,
    vm_running: bool,
    vnc_disp: str | None,
    vnc_port: int | None,
    manifest: dict[str, Any],
    web_console_listen_port: int,
) -> dict[str, Any]:
    """noVNC static assets + websockify process; QEMU VNC remains 127.0.0.1-only."""

    novnc_running = novnc_assets_present()

    pid: int | None = None
    try:
        if manifest.get("websockify_pid") is not None and str(
            manifest.get("websockify_pid")
        ).strip():
            pid = int(manifest["websockify_pid"])
    except (TypeError, ValueError):
        pid = None

    mf_target: int | None = None
    try:
        if manifest.get("target_port") is not None and str(
            manifest.get("target_port")
        ).strip():
            mf_target = int(manifest["target_port"])
    except (TypeError, ValueError):
        mf_target = None

    internal_match = (
        mf_target is not None and vnc_port is not None and mf_target == vnc_port
    )
    websockify_running = bool(
        manifest
        and pid_running(pid)
        and internal_match
        and manifest.get("listen_port") is not None
    )

    vnc_disp_ok = bool(vnc_disp and str(vnc_disp).strip())
    internal_tcp = bool(vnc_port and tcp_port_open("127.0.0.1", int(vnc_port)))
    listen_tcp = tcp_port_open("127.0.0.1", int(web_console_listen_port))
    ext_ip = primary_bind_ipv4()
    ext_tcp = bool(
        ext_ip is not None
        and tcp_port_open(str(ext_ip), int(web_console_listen_port))
    )

    web_console_url: str | None = None
    if ext_ip and websockify_running and novnc_running:
        web_console_url = f"http://{ext_ip}:{web_console_listen_port}/"

    web_console_available = bool(
        vm_running
        and vnc_disp_ok
        and vnc_port is not None
        and internal_tcp
        and websockify_running
        and novnc_running
        and listen_tcp
        and (ext_tcp if ext_ip else True)
    )

    return {
        "web_console_available": web_console_available,
        "web_console_url": web_console_url,
        "web_console_port": int(web_console_listen_port),
        "novnc_running": novnc_running,
        "websockify_running": websockify_running,
    }


def virsh_dumpxml(vm: str) -> str:
    p = _virsh("dumpxml", vm)
    if p.returncode != 0 or not p.stdout:
        return ""
    return p.stdout


def uefi_nvram_from_xml(xml_text: str) -> tuple[bool, str | None]:
    if not xml_text.strip():
        return False, None
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return False, None
    os_el = root.find("os")
    if os_el is None:
        return False, None
    loader = os_el.find("loader")
    nvram_el = os_el.find("nvram")
    nvram_path = None
    if nvram_el is not None and nvram_el.text:
        nvram_path = nvram_el.text.strip()
    uefi = False
    if loader is not None:
        typ = (loader.get("type") or "").lower()
        if typ == "pflash":
            uefi = True
        rd = loader.text or ""
        low = rd.lower()
        if "ovmf" in low or "edk2" in low or "tiano" in low:
            uefi = True
    fw = (root.get("firmware") or "").lower()
    if fw == "efi":
        uefi = True
    return uefi, nvram_path


def vnc_info(vm: str) -> tuple[str | None, int | None]:
    p = _virsh("vncdisplay", vm)
    if p.returncode != 0:
        return None, None
    blob = "\n".join(part for part in (p.stdout or "", p.stderr or "") if part)
    lines = [ln.strip() for ln in blob.splitlines() if ln.strip()]
    if not lines:
        return None, None
    # virsh may append blank lines; use last non-empty line.
    raw = lines[-1]
    # Examples: ":0", "127.0.0.1:0", "localhost:1"
    if ":" in raw:
        disp = raw.rsplit(":", 1)[-1]
    else:
        disp = raw.lstrip(":")
    try:
        n = int(disp)
    except ValueError:
        return raw, None
    return raw, 5900 + n


def ssh_batch_cmd(host: str, user: str, remote: str) -> bool:
    if not host or not user:
        return False
    return (
        subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "ConnectTimeout=8",
                f"{user}@{host}",
                "sh",
                "-lc",
                remote,
            ],
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )


def load_cfg(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def expected_ip_for_vm(cfg: dict[str, Any], vm: str, linux_materialized: str) -> str:
    vms = cfg.get("vms", {})
    entry = vms.get(vm, {})
    if vm == "victim-linux":
        return linux_materialized
    return str(entry.get("internal_ip", ""))


def deployment_type_for(vm: str, vtype: str) -> str:
    if vm == "victim-linux":
        return "cloud-image"
    if vtype == "windows":
        return "golden-qcow2"
    return "golden-qcow2"


def image_source_for(
    cfg: dict[str, Any],
    vm: str,
    linux_base_rel: str,
    *,
    windows_images_dir: str,
) -> str:
    vms = cfg.get("vms", {})
    entry = vms.get(vm, {})
    url = entry.get("image_url", "")
    if vm == "victim-linux":
        return linux_base_rel
    if str(entry.get("type", "")) == "windows":
        fname = str(entry.get("disk_filename", "") or Path(str(url)).name)
        if fname:
            return str(Path(windows_images_dir) / fname)
        return str(url)
    return str(url)


def mirror_applied_preserve(prev: dict[str, Any]) -> bool:
    v = prev.get("mirror_applied")
    if isinstance(v, bool):
        return v
    return False


def derive_mirror_applied(
    *,
    vm: str,
    state_dir: Path,
    prev: dict[str, Any],
) -> bool:
    """Cross-state derivation: sensor-vm.mirror_applied follows mirror.json.

    Source of truth: ${state_dir}/mirror.json (managed by ovs_mirror_state.py).
    Rule: mirror_applied is True iff the mirror record explicitly identifies
    this VM as its sensor and OVS reality is consistent. Any other VM is
    irrelevant to mirror_applied (always preserves prior value).
    """
    if vm != "sensor-vm":
        return mirror_applied_preserve(prev)
    mirror_path = state_dir / "mirror.json"
    if not mirror_path.is_file():
        return mirror_applied_preserve(prev)
    try:
        rec = json.loads(mirror_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return mirror_applied_preserve(prev)
    if rec.get("sensor_vm") != vm:
        return mirror_applied_preserve(prev)
    return bool(rec.get("consistent", False))


def last_deploy_preserve(prev: dict[str, Any], touch_deploy: bool) -> str | None:
    if touch_deploy:
        return utc_now()
    old = prev.get("last_deploy_time")
    if isinstance(old, str) and old:
        return old
    return None


def pick_ssh_user(
    vm: str,
    vtype: str,
    linux_ssh_user: str,
    entry: dict[str, Any],
) -> str | None:
    if vtype == "windows":
        u = entry.get("ssh_user") or os.environ.get("XDR_LAB_WINDOWS_SSH_USER", "")
        u = str(u).strip()
        return u or None
    if vm == "victim-linux":
        return linux_ssh_user
    if vtype in ("linux", "sensor"):
        return "ubuntu"
    return None


def build_state(
    *,
    cfg: dict[str, Any],
    vm: str,
    state_dir: Path,
    touch_deploy: bool,
    linux_materialized_ip: str,
    linux_ssh_user: str,
    linux_cloud_base_path: str,
    windows_images_dir: str,
    vnc_proxy_dir: Path,
    web_console_dir: Path,
) -> dict[str, Any]:
    vms = cfg.get("vms", {})
    entry = vms.get(vm, {})
    vtype = str(entry.get("type", ""))
    prev: dict[str, Any] = {}
    path = state_dir / f"{vm}.json"
    if path.is_file():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prev = {}

    exists = domain_exists(vm)
    state = domstate(vm) if exists else ""
    running = state == "running"
    exp_ip = expected_ip_for_vm(cfg, vm, linux_materialized_ip)
    addrs = collect_domifaddr_ipv4(vm) if exists else []
    actual_ip = addrs[0] if addrs else ""

    ssh_user = pick_ssh_user(vm, vtype, linux_ssh_user, entry)
    ssh_ok = False
    probe_host = actual_ip or exp_ip
    if running and ssh_user and probe_host:
        ssh_ok = ssh_batch_true(probe_host, ssh_user)

    snap_n = snapshot_count(vm) if exists else 0
    d_type = deployment_type_for(vm, vtype)
    img_src = image_source_for(
        cfg, vm, linux_cloud_base_path, windows_images_dir=windows_images_dir
    )

    out: dict[str, Any] = {
        "vm_name": vm,
        "expected_ip": exp_ip,
        "actual_ip": actual_ip or None,
        "libvirt_domain_exists": exists,
        "vm_running": running,
        "ssh_reachable": ssh_ok,
        "last_deploy_time": last_deploy_preserve(prev, touch_deploy),
        "last_validation_time": utc_now(),
        "mirror_applied": derive_mirror_applied(vm=vm, state_dir=state_dir, prev=prev),
        "snapshot_count": snap_n,
        "image_source": img_src,
        "deployment_type": d_type,
    }

    if vtype == "windows":
        xml_txt = virsh_dumpxml(vm) if exists else ""
        uefi_on, nvram_path = uefi_nvram_from_xml(xml_txt)
        if not nvram_path and isinstance(prev.get("nvram_path"), str):
            nvram_path = prev["nvram_path"]
        vnc_disp, vnc_port = vnc_info(vm) if exists else (None, None)

        rdp_ok = False
        winrm_ok = False
        if running and probe_host:
            rdp_ok = tcp_port_open(probe_host, 3389, timeout=2.0)
            winrm_ok = tcp_port_open(probe_host, 5985, timeout=1.5) or tcp_port_open(
                probe_host, 5986, timeout=1.5
            )

        out.update(
            {
                "rdp_reachable": rdp_ok,
                "winrm_reachable": winrm_ok,
                "uefi_enabled": uefi_on,
                "nvram_path": nvram_path,
                "vnc_display": vnc_disp,
                "vnc_port": vnc_port,
                "vnc_internal_display": vnc_disp,
                "vnc_internal_port": vnc_port,
            }
        )
        proxy_manifest = load_json_dict(vnc_proxy_dir / f"{vm}.json")
        out.update(
            windows_emergency_vnc_state(
                vm_running=running,
                vnc_disp=vnc_disp,
                vnc_port=vnc_port,
                manifest=proxy_manifest,
            )
        )
        web_manifest = load_json_dict(web_console_dir / f"{vm}.json")
        wc_listen = env_int("XDR_LAB_WEB_CONSOLE_PORT", 6080)
        out.update(
            windows_web_console_state(
                vm_running=running,
                vnc_disp=vnc_disp,
                vnc_port=vnc_port,
                manifest=web_manifest,
                web_console_listen_port=wc_listen,
            )
        )

    return out


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=False, ensure_ascii=False) + "\n"
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def cmd_refresh(args: argparse.Namespace) -> int:
    cfg = load_cfg(Path(args.cfg))
    st_dir = Path(args.state_dir)
    raw_proxy = str(getattr(args, "vnc_proxy_dir", "") or "").strip()
    proxy_dir = Path(raw_proxy) if raw_proxy else st_dir.parent / "vnc-proxy"
    raw_wc = str(getattr(args, "web_console_dir", "") or "").strip()
    web_dir = Path(raw_wc) if raw_wc else st_dir.parent / "web-console"
    data = build_state(
        cfg=cfg,
        vm=args.vm,
        state_dir=st_dir,
        touch_deploy=bool(args.touch_deploy),
        linux_materialized_ip=args.linux_materialized_ip,
        linux_ssh_user=args.linux_ssh_user,
        linux_cloud_base_path=args.linux_cloud_base,
        windows_images_dir=args.windows_images_dir,
        vnc_proxy_dir=proxy_dir,
        web_console_dir=web_dir,
    )
    atomic_write_json(st_dir / f"{args.vm}.json", data)
    if args.print_json:
        print(json.dumps(data, ensure_ascii=False))
    return 0


def cmd_cloud_init(args: argparse.Namespace) -> int:
    """Return 0 if boot-finished exists or SSH unreachable (no-op success)."""
    if not ssh_batch_cmd(args.ip, args.user, "test -f /var/lib/cloud/instance/boot-finished"):
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("refresh")
    r.add_argument("--vm", required=True)
    r.add_argument("--cfg", required=True)
    r.add_argument("--state-dir", required=True)
    r.add_argument("--touch-deploy", action="store_true")
    r.add_argument("--linux-materialized-ip", required=True)
    r.add_argument("--linux-ssh-user", required=True)
    r.add_argument("--linux-cloud-base", required=True)
    r.add_argument(
        "--windows-images-dir",
        default=os.environ.get("XDR_LAB_WINDOWS_IMAGES_DIR", ""),
        help="Canonical Windows golden cache dir (images/windows).",
    )
    r.add_argument(
        "--vnc-proxy-dir",
        default=os.environ.get("XDR_LAB_VNC_PROXY_DIR", ""),
        help="Directory holding per-VM VNC proxy manifests (<vm>.json). "
        "Default: <state-dir>/../vnc-proxy",
    )
    r.add_argument(
        "--web-console-dir",
        default=os.environ.get("XDR_LAB_WEB_CONSOLE_DIR", ""),
        help="Directory holding per-VM websockify manifests (<vm>.json). "
        "Default: <state-dir>/../web-console",
    )
    r.add_argument("--print-json", action="store_true")
    r.set_defaults(func=cmd_refresh)

    c = sub.add_parser("cloud-init-done")
    c.add_argument("--ip", required=True)
    c.add_argument("--user", required=True)
    c.set_defaults(func=cmd_cloud_init)

    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
