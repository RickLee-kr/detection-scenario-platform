#!/usr/bin/env python3
"""Aggregate lab snapshot catalog for xdr-lab-vm-manager.sh (snapshots.json).

Reads libvirt snapshot names per VM; merges operator last_batch + bounded history.
UEFI/pflash domains use external disk-only snapshots (internal qcow2 snapshots are
unsupported). Linux/BIOS domains keep libvirt internal snapshots.

Invoked only from xdr-lab-vm-manager.sh — not from appliance_cli.py.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
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


def virsh_dumpxml(vm: str) -> str:
    p = _virsh("dumpxml", vm)
    if p.returncode != 0 or not p.stdout:
        return ""
    return p.stdout


def domain_uses_pflash(vm: str) -> bool:
    xml_text = virsh_dumpxml(vm)
    if not xml_text.strip():
        return False
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return False
    os_el = root.find("os")
    if os_el is None:
        return False
    loader = os_el.find("loader")
    if loader is not None:
        typ = (loader.get("type") or "").lower()
        if typ == "pflash":
            return True
        rd = loader.text or ""
        low = rd.lower()
        if "ovmf" in low or "edk2" in low or "tiano" in low:
            return True
    fw = (root.get("firmware") or "").lower()
    if fw == "efi":
        return True
    return False


def snapshot_policy_for(vm: str) -> str:
    if domain_exists(vm) and domain_uses_pflash(vm):
        return "external_disk"
    return "internal"


def snapshot_location(vm: str, snap_name: str) -> str | None:
    p = _virsh("snapshot-info", vm, snap_name)
    if p.returncode != 0:
        return None
    for ln in p.stdout.splitlines():
        if ln.lower().startswith("location:"):
            return ln.split(":", 1)[1].strip().lower()
    return None


def snapshot_names_for(vm: str) -> list[str]:
    if not domain_exists(vm):
        return []
    p = _virsh("snapshot-list", "--domain", vm, "--name")
    if p.returncode != 0 or not p.stdout:
        return []
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]


def primary_disk_target_path(vm: str) -> tuple[str | None, str | None]:
    """Return (target_dev, source_path) for the first file-backed disk device."""
    p = _virsh("domblklist", vm, "--details")
    if p.returncode != 0:
        return None, None
    for ln in p.stdout.splitlines():
        parts = ln.split()
        if len(parts) < 4:
            continue
        typ, dev, target, src = parts[0], parts[1], parts[2], parts[3]
        if typ == "file" and dev == "disk" and src and src != "-":
            return target, src
    return None, None


def default_overlay_path(runtime_dir: Path, vm: str, snap_name: str) -> Path:
    return runtime_dir / vm / f"root.{snap_name}"


def default_base_disk(runtime_dir: Path, vm: str) -> Path:
    return runtime_dir / vm / "root.qcow2"


def nvram_backup_path(runtime_dir: Path, vm: str, snap_name: str) -> Path:
    return runtime_dir / vm / "snapshots" / snap_name / "OVMF_VARS.fd"


def load_json_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def _qemu_backing_file(path: Path) -> str | None:
    p = subprocess.run(
        ["qemu-img", "info", "--output=json", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if p.returncode != 0:
        return None
    try:
        data = json.loads(p.stdout)
    except json.JSONDecodeError:
        return None
    bf = data.get("backing-filename") or data.get("full-backing-filename")
    return str(bf).strip() if bf else None


def _merge_manifest(
    prev_per_vm: dict[str, Any],
    vm: str,
    snap_name: str,
    runtime_dir: Path,
    *,
    record_create: bool = False,
    drop_name: str | None = None,
) -> dict[str, Any]:
    row = prev_per_vm.get(vm)
    manifest: dict[str, Any] = {}
    if isinstance(row, dict) and isinstance(row.get("manifest"), dict):
        manifest = dict(row["manifest"])
    if drop_name and drop_name in manifest:
        del manifest[drop_name]
    if record_create and snap_name:
        target, active = primary_disk_target_path(vm)
        base = default_base_disk(runtime_dir, vm)
        overlay = default_overlay_path(runtime_dir, vm, snap_name)
        if active and Path(active).is_file():
            bf = _qemu_backing_file(Path(active))
            if bf:
                base = Path(bf)
            overlay = Path(active)
        nvram_bak = nvram_backup_path(runtime_dir, vm, snap_name)
        manifest[snap_name] = {
            "mode": "external_disk",
            "created_utc": utc_now(),
            "disk_target": target,
            "disk_active": str(overlay),
            "disk_base": str(base),
            "disk_overlay": str(overlay),
            "nvram_backup": str(nvram_bak) if nvram_bak.is_file() else None,
        }
    return manifest


def _enrich_per_vm_row(
    vm: str,
    row: dict[str, Any],
    prev_per_vm: dict[str, Any],
    runtime_dir: Path | None,
) -> dict[str, Any]:
    policy = snapshot_policy_for(vm) if row.get("domain_defined") else "internal"
    row["snapshot_policy"] = policy
    row["pflash"] = policy == "external_disk"
    prev = prev_per_vm.get(vm) if isinstance(prev_per_vm.get(vm), dict) else {}
    manifest = prev.get("manifest") if isinstance(prev.get("manifest"), dict) else {}
    if runtime_dir is not None and policy == "external_disk":
        manifest = _merge_manifest({"manifest": manifest}, vm, "", runtime_dir)
    row["manifest"] = manifest
    details: list[dict[str, Any]] = []
    for name in row.get("snapshots") or []:
        loc = snapshot_location(vm, name) if row.get("domain_defined") else None
        ent: dict[str, Any] = {"name": name, "location": loc or "unknown"}
        if isinstance(manifest.get(name), dict):
            ent["manifest"] = manifest[name]
        details.append(ent)
    if details:
        row["snapshot_details"] = details
    return row


def probe_vms(
    vms: list[str],
    *,
    prev: dict[str, Any] | None = None,
    runtime_dir: Path | None = None,
) -> dict[str, Any]:
    prev_per_vm = prev.get("per_vm") if isinstance(prev, dict) else {}
    if not isinstance(prev_per_vm, dict):
        prev_per_vm = {}
    per_vm: dict[str, Any] = {}
    for vm in vms:
        defined = domain_exists(vm)
        names = snapshot_names_for(vm) if defined else []
        row: dict[str, Any] = {
            "domain_defined": defined,
            "snapshot_count": len(names),
            "snapshots": names,
        }
        per_vm[vm] = _enrich_per_vm_row(vm, row, prev_per_vm, runtime_dir)
    return per_vm


def _set_disk_source_path(xml_text: str, target: str, new_path: str) -> str:
    root = ET.fromstring(xml_text)
    devices = root.find("devices")
    if devices is None:
        raise ValueError("no devices in domain xml")
    updated = False
    for disk in devices.findall("disk"):
        if disk.get("device") != "disk":
            continue
        tgt = disk.find("target")
        if tgt is None or (tgt.get("dev") or "") != target:
            continue
        src = disk.find("source")
        if src is None:
            src = ET.SubElement(disk, "source")
        src.set("file", new_path)
        for bs in list(disk.findall("backingStore")):
            disk.remove(bs)
        updated = True
        break
    if not updated:
        raise ValueError(f"disk target {target!r} not found in domain xml")
    return ET.tostring(root, encoding="unicode")


def _domain_destroy(vm: str) -> None:
    p = _virsh("domstate", vm)
    if p.returncode != 0:
        return
    state = (p.stdout or "").strip().lower()
    if state in ("shut off", "shutoff", "nostate"):
        return
    _virsh("destroy", vm)


def _orphan_overlay_path(runtime_dir: Path, vm: str, snap_name: str) -> Path:
    return default_overlay_path(runtime_dir, vm, snap_name)


def _remove_orphan_overlay(
    runtime_dir: Path, vm: str, snap_name: str, known_names: list[str]
) -> tuple[bool, str]:
    """Drop leftover root.<snap> qcow2 when libvirt has no matching snapshot metadata."""
    if snap_name in known_names:
        return True, ""
    overlay = _orphan_overlay_path(runtime_dir, vm, snap_name)
    if not overlay.is_file():
        return True, ""
    try:
        overlay.unlink()
    except OSError as exc:
        hint = " (use sudo — runtime is root-owned)" if getattr(exc, "errno", None) == 13 else ""
        return False, f"orphan_overlay_remove_failed:{overlay}:{exc}{hint}"
    return True, "removed_orphan_overlay"


def external_create(
    vm: str,
    snap_name: str,
    runtime_dir: Path,
) -> tuple[bool, str]:
    if not domain_exists(vm):
        return False, "domain_not_defined"
    names = snapshot_names_for(vm)
    if snap_name in names:
        return False, f"snapshot_already_exists:{snap_name}"
    ok, msg = _remove_orphan_overlay(runtime_dir, vm, snap_name, names)
    if not ok:
        return False, msg
    p = _virsh(
        "snapshot-create-as",
        vm,
        snap_name,
        "--disk-only",
        "--description",
        "xdr-lab external disk snapshot",
    )
    if p.returncode != 0:
        err = (p.stderr or p.stdout or "virsh_snapshot_create_failed").strip()
        return False, err
    after = snapshot_names_for(vm)
    if snap_name not in after:
        return False, "snapshot_created_but_not_listed"
    loc = snapshot_location(vm, snap_name)
    if loc and loc != "external":
        return False, f"snapshot_unexpected_location:{loc}"
    return True, msg


def external_revert(
    vm: str,
    snap_name: str,
    runtime_dir: Path,
) -> tuple[bool, str]:
    if not domain_exists(vm):
        return False, "domain_not_defined"
    base_path = default_base_disk(runtime_dir, vm)
    overlay_path = default_overlay_path(runtime_dir, vm, snap_name)
    target, active = primary_disk_target_path(vm)
    nvram_bak: Path | None = nvram_backup_path(runtime_dir, vm, snap_name)

    _domain_destroy(vm)
    target, active = primary_disk_target_path(vm)
    if active:
        bf = _qemu_backing_file(Path(active))
        if bf:
            base_path = Path(bf)
        overlay_path = Path(active)

    if target is None:
        return False, "disk_target_not_found"

    # Point domain at frozen base; discard post-snapshot overlay.
    try:
        xml = virsh_dumpxml(vm)
        new_xml = _set_disk_source_path(xml, target, str(base_path))
        tmp = Path(f"/tmp/xdr-snap-revert-{vm}-{uuid.uuid4().hex}.xml")
        tmp.write_text(new_xml, encoding="utf-8")
        p = _virsh("define", str(tmp))
        tmp.unlink(missing_ok=True)
        if p.returncode != 0:
            return False, (p.stderr or p.stdout or "define_failed").strip()
    except (ET.ParseError, ValueError) as exc:
        return False, str(exc)

    p = _virsh("snapshot-delete", vm, snap_name, "--metadata")
    if p.returncode != 0 and "not found" not in (p.stderr or "").lower():
        return False, (p.stderr or p.stdout or "snapshot_delete_metadata_failed").strip()

    if overlay_path.is_file() and overlay_path != base_path:
        try:
            overlay_path.unlink()
        except OSError as exc:
            return False, f"overlay_unlink_failed:{exc}"

    if nvram_bak is not None and nvram_bak.is_file():
        nvram_live = runtime_dir / vm / "nvram" / "OVMF_VARS.fd"
        if nvram_live.parent.is_dir():
            shutil.copy2(nvram_bak, nvram_live)

    return True, ""


def external_delete(
    vm: str,
    snap_name: str,
    runtime_dir: Path,
) -> tuple[bool, str]:
    """Merge active overlay into base, drop snapshot metadata, remove overlay file."""
    if not domain_exists(vm):
        return False, "domain_not_defined"
    target, active = primary_disk_target_path(vm)
    if target is None or not active:
        return False, "disk_target_not_found"

    overlay = Path(active)
    base = default_base_disk(runtime_dir, vm)
    bf = _qemu_backing_file(overlay)
    if bf:
        base = Path(bf)

    _domain_destroy(vm)

    # Offline blockcommit: merge overlay into base when chain is base <- overlay.
    p = _virsh(
        "blockcommit",
        vm,
        target,
        "--active",
        "--shallow",
        "--pivot",
        "--base",
        str(base),
    )
    if p.returncode != 0:
        # Fallback: same manual path as revert (discard snapshot, keep base only).
        ok, msg = external_revert(vm, snap_name, runtime_dir)
        if ok:
            return True, "reverted_instead_of_merge"
        return False, (p.stderr or p.stdout or msg or "blockcommit_failed").strip()

    p = _virsh("snapshot-delete", vm, snap_name, "--metadata")
    if p.returncode != 0 and "not found" not in (p.stderr or "").lower():
        return False, (p.stderr or p.stdout or "snapshot_delete_metadata_failed").strip()

    expected_overlay = default_overlay_path(runtime_dir, vm, snap_name)
    for candidate in (overlay, expected_overlay):
        if candidate.is_file() and candidate.resolve() != base.resolve():
            try:
                candidate.unlink()
            except OSError:
                pass

    snap_nvram_dir = runtime_dir / vm / "snapshots" / snap_name
    if snap_nvram_dir.is_dir():
        shutil.rmtree(snap_nvram_dir, ignore_errors=True)

    # Ensure domain XML has no stale backingStore.
    try:
        xml = virsh_dumpxml(vm)
        new_xml = _set_disk_source_path(xml, target, str(base))
        tmp = Path(f"/tmp/xdr-snap-del-{vm}-{uuid.uuid4().hex}.xml")
        tmp.write_text(new_xml, encoding="utf-8")
        _virsh("define", str(tmp))
        tmp.unlink(missing_ok=True)
    except (ET.ParseError, ValueError):
        pass

    return True, ""


def cmd_vm_policy(args: argparse.Namespace) -> int:
    print(snapshot_policy_for(str(args.vm)))
    return 0


def cmd_external_create(args: argparse.Namespace) -> int:
    ok, msg = external_create(
        str(args.vm),
        str(args.snapshot_name),
        Path(args.runtime_dir),
    )
    if not ok:
        print(msg, file=sys.stderr)
        return 1
    if msg:
        print(msg, file=sys.stderr)
    return 0


def cmd_external_revert(args: argparse.Namespace) -> int:
    ok, msg = external_revert(
        str(args.vm),
        str(args.snapshot_name),
        Path(args.runtime_dir),
    )
    if not ok:
        print(msg, file=sys.stderr)
        return 1
    return 0


def cmd_external_delete(args: argparse.Namespace) -> int:
    ok, msg = external_delete(
        str(args.vm),
        str(args.snapshot_name),
        Path(args.runtime_dir),
    )
    if not ok:
        print(msg, file=sys.stderr)
        return 1
    return 0


def cmd_write(args: argparse.Namespace) -> int:
    path = Path(args.snapshots_path)
    runtime_dir = Path(str(args.runtime_dir or os.environ.get("XDR_RUNTIME_DIR", "/opt/xdr-lab/runtime")))
    vms = [x.strip() for x in str(args.vms).split(",") if x.strip()]
    prev = load_json_dict(path)
    prev_per_vm = prev.get("per_vm") if isinstance(prev.get("per_vm"), dict) else {}

    probed = probe_vms(vms, prev=prev, runtime_dir=runtime_dir)
    per_vm: dict[str, Any] = dict(prev_per_vm) if isinstance(prev_per_vm, dict) else {}
    per_vm.update(probed)

    env_targets = os.environ.get("XDR_LAB_SNAPSHOT_VM_LIST", "")
    if env_targets.strip():
        all_targets = [x.strip() for x in env_targets.split() if x.strip()]
    elif isinstance(prev.get("targets"), list):
        all_targets = [str(x) for x in prev["targets"]]
    else:
        all_targets = list(vms)

    vm_results_path = str(getattr(args, "vm_results", "") or "").strip()
    snap_name = str(args.snapshot_name or "").strip()
    op = str(args.operation or "refresh")

    if vm_results_path and op == "create" and snap_name and not bool(args.dry_run):
        try:
            vm_results = json.loads(Path(vm_results_path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            vm_results = {}
        if isinstance(vm_results, dict):
            for vm, res in vm_results.items():
                if not isinstance(res, dict) or not res.get("ok"):
                    continue
                if res.get("snapshot_mode") != "external_disk":
                    continue
                row = per_vm.get(vm, {})
                manifest = _merge_manifest(
                    {"manifest": row.get("manifest") or {}},
                    vm,
                    snap_name,
                    runtime_dir,
                    record_create=True,
                )
                row["manifest"] = manifest
                per_vm[vm] = row

    history: list[Any] = []
    raw_hist = prev.get("history")
    if isinstance(raw_hist, list):
        history = list(raw_hist)

    last_batch: dict[str, Any] | None = None
    if vm_results_path:
        try:
            vm_results = json.loads(Path(vm_results_path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"snapshot_state: invalid --vm-results: {exc}", file=sys.stderr)
            return 2
        if not isinstance(vm_results, dict):
            print("snapshot_state: --vm-results must be a JSON object", file=sys.stderr)
            return 2

        last_batch = {
            "operation": op,
            "snapshot_name": snap_name or None,
            "started_utc": str(args.started_utc or "").strip() or None,
            "finished_utc": str(args.finished_utc or "").strip() or None,
            "dry_run": bool(args.dry_run),
            "overall_rc": int(args.overall_rc),
            "vms": vm_results,
        }

        all_ok = all(
            isinstance(v, dict) and bool(v.get("ok")) for v in vm_results.values()
        )
        if op == "create" and snap_name and all_ok and not bool(args.dry_run):
            entry = {
                "operation": "create",
                "snapshot_name": snap_name,
                "created_utc": str(args.finished_utc or utc_now()),
                "vms": vm_results,
            }
            history.append(entry)
            max_hist = int(os.environ.get("XDR_LAB_SNAPSHOT_HISTORY_MAX", "50"))
            if len(history) > max_hist:
                history = history[-max_hist:]

        if op in ("revert", "delete") and snap_name and not bool(args.dry_run):
            for vm, res in vm_results.items():
                if not isinstance(res, dict) or not res.get("ok"):
                    continue
                if res.get("snapshot_mode") != "external_disk":
                    continue
                row = per_vm.get(vm, {})
                manifest = _merge_manifest(
                    {"manifest": row.get("manifest") or {}},
                    vm,
                    "",
                    runtime_dir,
                    drop_name=snap_name,
                )
                row["manifest"] = manifest
                per_vm[vm] = row
    else:
        old_lb = prev.get("last_batch")
        if op == "list":
            last_batch = {
                "operation": "list",
                "snapshot_name": None,
                "started_utc": str(args.started_utc or "").strip() or None,
                "finished_utc": str(args.finished_utc or "").strip() or None,
                "dry_run": bool(args.dry_run),
                "overall_rc": int(args.overall_rc),
                "vms": {},
            }
        elif isinstance(old_lb, dict):
            last_batch = old_lb

    out: dict[str, Any] = {
        "schema_version": 2,
        "updated_utc": utc_now(),
        "targets": all_targets,
        "per_vm": per_vm,
    }
    if last_batch is not None:
        out["last_batch"] = last_batch
    if history:
        out["history"] = history

    atomic_write_json(path, out)
    return 0


def cmd_print_batch_summary(args: argparse.Namespace) -> int:
    op = str(args.operation or "batch").strip()
    snap_name = str(args.snapshot_name or "").strip()
    overall = int(args.overall_rc)
    path = Path(args.vm_results)
    try:
        vm_results = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"snapshot: invalid vm-results: {exc}", file=sys.stderr)
        return 2
    if not isinstance(vm_results, dict):
        print("snapshot: vm-results must be a JSON object", file=sys.stderr)
        return 2
    label = snap_name or "(default)"
    print(f"snapshot {op}: name={label} overall={'ok' if overall == 0 else 'FAILED'}", file=sys.stderr)
    for vm in sorted(vm_results.keys()):
        res = vm_results.get(vm)
        if not isinstance(res, dict):
            print(f"  {vm}: invalid result record", file=sys.stderr)
            overall = 1
            continue
        ok = bool(res.get("ok"))
        mode = str(res.get("snapshot_mode", "")).strip()
        msg = str(res.get("message", "")).strip()
        mode_tag = f" mode={mode}" if mode else ""
        if ok:
            print(f"  {vm}: OK{mode_tag}", file=sys.stderr)
        else:
            print(f"  {vm}: FAILED{mode_tag} — {msg or 'unknown error'}", file=sys.stderr)
            overall = 1
    return 0 if overall == 0 else 1


def cmd_merge_lines(args: argparse.Namespace) -> int:
    """Merge JSONL lines {\"vm\":..., \"ok\":..., \"message\":...} into one object."""
    obj: dict[str, Any] = {}
    inp = Path(args.input_path)
    for ln in inp.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        j = json.loads(ln)
        vm = str(j.get("vm", "")).strip()
        if not vm:
            continue
        rec: dict[str, Any] = {
            "ok": bool(j.get("ok")),
            "message": str(j.get("message", "")),
        }
        mode = str(j.get("snapshot_mode", "")).strip()
        if mode:
            rec["snapshot_mode"] = mode
        obj[vm] = rec
    Path(args.output_path).write_text(
        json.dumps(obj, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return 0


def cmd_print_table(args: argparse.Namespace) -> int:
    path = Path(args.snapshots_path)
    runtime_dir = Path(str(args.runtime_dir or os.environ.get("XDR_RUNTIME_DIR", "/opt/xdr-lab/runtime")))
    vms = [x.strip() for x in str(args.vms).split(",") if x.strip()]
    prev = load_json_dict(path)
    per_vm = probe_vms(vms, prev=prev, runtime_dir=runtime_dir)
    print("XDR Lab — libvirt snapshots (orchestration targets)")
    print("  internal = qcow2 domain snapshot | external_disk = UEFI/pflash --disk-only")
    print("")
    for vm in vms:
        row = per_vm.get(vm, {})
        defined = row.get("domain_defined", False)
        names = row.get("snapshots") or []
        cnt = row.get("snapshot_count", 0)
        policy = row.get("snapshot_policy", "internal")
        st = "defined" if defined else "missing"
        print(f"  {vm}  ({st}, count={cnt}, policy={policy})")
        if names:
            for n in names:
                loc = snapshot_location(vm, n) if defined else None
                tag = f" [{loc}]" if loc else ""
                print(f"    - {n}{tag}")
        else:
            print("    (none)")
        print("")
    if path.is_file():
        print(f"State file: {path}")
    else:
        print("(snapshots.json not written yet — run a snapshot command)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Lab snapshot aggregate state.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pol = sub.add_parser("vm-policy", help="Print internal or external_disk for a VM.")
    pol.add_argument("--vm", required=True)
    pol.set_defaults(func=cmd_vm_policy)

    ec = sub.add_parser("external-create", help="Create UEFI external disk-only snapshot.")
    ec.add_argument("--vm", required=True)
    ec.add_argument("--snapshot-name", required=True)
    ec.add_argument("--runtime-dir", required=True)
    ec.set_defaults(func=cmd_external_create)

    er = sub.add_parser("external-revert", help="Revert UEFI external disk snapshot.")
    er.add_argument("--vm", required=True)
    er.add_argument("--snapshot-name", required=True)
    er.add_argument("--runtime-dir", required=True)
    er.set_defaults(func=cmd_external_revert)

    ed = sub.add_parser("external-delete", help="Delete UEFI external disk snapshot.")
    ed.add_argument("--vm", required=True)
    ed.add_argument("--snapshot-name", required=True)
    ed.add_argument("--runtime-dir", required=True)
    ed.set_defaults(func=cmd_external_delete)

    w = sub.add_parser("write", help="Refresh per_vm from virsh; optional last_batch merge.")
    w.add_argument("--snapshots-path", required=True)
    w.add_argument("--vms", required=True, help="Comma-separated VM names.")
    w.add_argument("--runtime-dir", default="")
    w.add_argument("--operation", default="refresh")
    w.add_argument("--snapshot-name", default="")
    w.add_argument("--started-utc", default="")
    w.add_argument("--finished-utc", default="")
    w.add_argument("--dry-run", action="store_true")
    w.add_argument("--overall-rc", type=int, default=0)
    w.add_argument(
        "--vm-results",
        default="",
        help="JSON object path: {vm: {ok: bool, message: str}}",
    )
    w.set_defaults(func=cmd_write)

    p = sub.add_parser("print-table", help="Stdout table from live virsh (no file write).")
    p.add_argument("--snapshots-path", default="")
    p.add_argument("--runtime-dir", default="")
    p.add_argument("--vms", required=True)
    p.set_defaults(func=cmd_print_table)

    bs = sub.add_parser("print-batch-summary", help="Human-readable per-VM batch result.")
    bs.add_argument("--operation", required=True)
    bs.add_argument("--snapshot-name", default="")
    bs.add_argument("--overall-rc", type=int, default=0)
    bs.add_argument("--vm-results", required=True)
    bs.set_defaults(func=cmd_print_batch_summary)

    m = sub.add_parser("merge-lines", help="Build vm-results JSON from JSONL lines.")
    m.add_argument("--input", dest="input_path", required=True)
    m.add_argument("--output", dest="output_path", required=True)
    m.set_defaults(func=cmd_merge_lines)

    ns = ap.parse_args()
    return int(ns.func(ns))


if __name__ == "__main__":
    raise SystemExit(main())
