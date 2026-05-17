#!/usr/bin/env python3
"""CLI-safe CALDERA API key resolution (no sudo, no unreadable /etc reads).

Operators without root read /etc/xdr-lab/caldera-api-key via:
  ${XDR_ROOT}/runtime/caldera-api-key  (group-readable copy; synced by installer / ensure-caldera-api-key)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent


def normalize_plaintext_key(value: str | bytes) -> str:
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = value
    return text.replace("\r", "").replace("\n", "").strip()

DEFAULT_ETC_KEY_FILE = Path("/etc/xdr-lab/caldera-api-key")
RUNTIME_KEY_NAME = "caldera-api-key"


def default_xdr_root() -> Path:
    return Path(os.environ.get("XDR_ROOT") or os.environ.get("XDR_BASE") or "/opt/xdr-lab")


def runtime_api_key_path(xdr_root: Path | None = None) -> Path:
    return (xdr_root or default_xdr_root()).resolve() / "runtime" / RUNTIME_KEY_NAME


def caldera_api_key_file_path(cfg: dict) -> Path:
    key_file = str(cfg.get("api_key_file") or "").strip()
    if key_file:
        return Path(key_file)
    return DEFAULT_ETC_KEY_FILE


def read_key_file_if_readable(path: Path) -> str | None:
    try:
        if not path.exists():
            return None
        if not path.is_file():
            return None
        st = path.stat()
        if st.st_size <= 0:
            return None
        with path.open("rb") as f:
            return normalize_plaintext_key(f.read())
    except PermissionError:
        return None
    except OSError:
        return None


def load_caldera_lab_config(xdr_root: Path | None = None) -> dict:
    root = (xdr_root or default_xdr_root()).resolve()
    candidates = [
        root / "config" / "caldera-lab.json",
        Path(os.environ.get("XDR_LAB_CALDERA_CONFIG", "")),
        _SCRIPT_DIR.parent / "config" / "caldera-lab.json",
    ]
    for p in candidates:
        if p and p.is_file():
            with p.open(encoding="utf-8") as f:
                doc = json.load(f)
            return doc if isinstance(doc, dict) else {}
    return {}


def resolve_api_key(
    cfg: dict | None = None,
    *,
    xdr_root: Path | None = None,
    warn_stale_env: bool = True,
) -> str:
    """Resolve API key for operator CLI paths (never uses sudo)."""
    root = (xdr_root or default_xdr_root()).resolve()
    cfg = cfg if cfg is not None else load_caldera_lab_config(root)
    primary = caldera_api_key_file_path(cfg)
    runtime = runtime_api_key_path(root)

    file_key = read_key_file_if_readable(primary)
    if not file_key and primary != runtime:
        file_key = read_key_file_if_readable(runtime)
    if not file_key and primary != DEFAULT_ETC_KEY_FILE:
        file_key = read_key_file_if_readable(DEFAULT_ETC_KEY_FILE)
    if not file_key and runtime != runtime_api_key_path(Path("/opt/xdr-lab")):
        file_key = read_key_file_if_readable(runtime_api_key_path(Path("/opt/xdr-lab")))

    env_key = os.environ.get("XDR_CALDERA_API_KEY", "").strip()
    if file_key:
        if warn_stale_env and env_key and env_key != file_key:
            print(
                f"[warn] XDR_CALDERA_API_KEY differs from readable key file — using file "
                f"(unset stale env: export -n XDR_CALDERA_API_KEY)",
                file=sys.stderr,
            )
        return file_key
    if env_key:
        return env_key
    env_name = str(cfg.get("api_key_env") or "XDR_CALDERA_API_KEY").strip()
    alt = os.environ.get(env_name, "").strip()
    return alt


def sync_runtime_api_key_copy(
    *,
    xdr_root: Path | None = None,
    source: Path | None = None,
    group: str = "xdr-lab",
) -> bool:
    """Copy canonical key file to ${XDR_ROOT}/runtime/caldera-api-key (root/installer only)."""
    root = (xdr_root or default_xdr_root()).resolve()
    src = source or DEFAULT_ETC_KEY_FILE
    if not src.is_file():
        return False
    try:
        plain = normalize_plaintext_key(src.read_bytes())
    except OSError:
        return False
    if not plain:
        return False
    dest = runtime_api_key_path(root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(plain, encoding="utf-8")
    try:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            import grp

            gid = grp.getgrnam(group).gr_gid
            os.chown(dest, 0, gid)
            dest.chmod(0o640)
            if src == DEFAULT_ETC_KEY_FILE and src.is_file():
                os.chown(src, 0, gid)
                src.chmod(0o640)
                src.parent.chmod(0o750)
    except (OSError, KeyError):
        dest.chmod(0o640)
    return True


def main() -> int:
    p = argparse.ArgumentParser(description="Resolve or sync CALDERA API key for XDR Lab CLI")
    p.add_argument("--xdr-root", type=Path, default=None)
    p.add_argument("--config", type=Path, default=None, help="caldera-lab.json (optional)")
    p.add_argument(
        "--sync-runtime",
        action="store_true",
        help="Copy /etc/xdr-lab/caldera-api-key to runtime (requires root/readable source)",
    )
    p.add_argument("--source", type=Path, default=DEFAULT_ETC_KEY_FILE)
    p.add_argument("--group", default="xdr-lab")
    args = p.parse_args()
    root = args.xdr_root or default_xdr_root()
    if args.sync_runtime:
        ok = sync_runtime_api_key_copy(xdr_root=root, source=args.source, group=args.group)
        return 0 if ok else 1
    cfg: dict = {}
    if args.config and args.config.is_file():
        with args.config.open(encoding="utf-8") as f:
            cfg = json.load(f)
    elif not cfg:
        cfg = load_caldera_lab_config(root)
    key = resolve_api_key(cfg, xdr_root=root, warn_stale_env=False)
    if not key:
        return 1
    sys.stdout.write(key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
