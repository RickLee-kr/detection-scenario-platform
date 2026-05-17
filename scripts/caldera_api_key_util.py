#!/usr/bin/env python3
"""CALDERA API key file ↔ conf/default.yml sync for XDR Lab (argon2-hashed api_key_red)."""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from caldera_key_crypto import (
    dump_config,
    hash_fields_single_quoted_in_text,
    hash_plaintext_key,
    is_hashed,
    key_fingerprint,
    load_config,
    log_key_verify_debug,
    normalize_plaintext_key,
    read_key_file,
    verify_api_key,
    verify_api_key_red_on_disk,
)


def read_yaml(path: Path) -> dict:
    return load_config(path)


def write_yaml(path: Path, data: dict) -> None:
    backup = path.with_name(
        f"{path.name}.pre-xdr-lab-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    shutil.copy2(path, backup)
    dump_config(path, data)


def _stop_caldera_before_config_write() -> None:
    """Prevent app_svc teardown from clobbering freshly synced api_key_* on disk."""
    if (os.environ.get("XDR_CALDERA_SKIP_STOP") or "").strip() == "1":
        return
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        subprocess.run(
            ["systemctl", "stop", "caldera.service"],
            check=False,
            capture_output=True,
            timeout=120,
        )
        for _ in range(30):
            proc = subprocess.run(
                ["systemctl", "is-active", "caldera.service"],
                capture_output=True,
                text=True,
            )
            if proc.stdout.strip() != "active":
                break
            time.sleep(1)
        return
    subprocess.run(
        ["pkill", "-f", r"/opt/caldera/.venv/bin/python3 /opt/caldera/server.py"],
        check=False,
        capture_output=True,
    )
    time.sleep(2)


def _write_key_file(key_file: Path, plain: str) -> None:
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(plain, encoding="utf-8")
    try:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            import grp

            gid = grp.getgrnam("xdr-lab").gr_gid
            os.chown(key_file, 0, gid)
            key_file.chmod(0o640)
            key_file.parent.chmod(0o750)
    except (OSError, KeyError, NameError):
        try:
            key_file.chmod(0o600)
        except OSError:
            pass
    try:
        from caldera_api_key_resolve import sync_runtime_api_key_copy

        sync_runtime_api_key_copy(source=key_file)
    except Exception:
        pass


def _require_key_matches_on_disk(
    cfg_path: Path,
    key_file: Path,
    *,
    label: str,
) -> str:
    """Re-read key file + YAML from disk; abort if api_key_red does not verify."""
    plain = read_key_file(key_file)
    if not plain:
        print(f"error: empty key file after {label} (path={key_file})", file=sys.stderr)
        raise SystemExit(1)
    stored = str(load_config(cfg_path).get("api_key_red") or "")
    log_key_verify_debug(plain, stored, label=label)
    if not verify_api_key_red_on_disk(cfg_path, plain):
        print(
            f"error: key_matches_api_key_red=False after {label} "
            f"(key_file={key_file}, config={cfg_path}, "
            f"plain_fp={key_fingerprint(plain)}, hash_fp={key_fingerprint(stored)})",
            file=sys.stderr,
        )
        raise SystemExit(1)
    text = cfg_path.read_text(encoding="utf-8")
    if not hash_fields_single_quoted_in_text(text):
        print(
            f"error: api_key hash not single-quoted in {cfg_path} "
            f"(argon2 '+' may be corrupted on reload)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return plain


def _persist_api_key_red(
    cfg_path: Path,
    key_file: Path,
    cfg: dict,
    plain: str,
    *,
    had_stored: bool,
) -> str:
    """Write key file, hash from disk plain, update YAML; verify before returning action."""
    plain_norm = normalize_plaintext_key(plain)
    if not plain_norm:
        print("error: empty API key", file=sys.stderr)
        raise SystemExit(2)
    _stop_caldera_before_config_write()
    try:
        _write_key_file(key_file, plain_norm)
    except OSError as exc:
        print(f"error: cannot write key file {key_file}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    plain_from_disk = read_key_file(key_file)
    if plain_from_disk != plain_norm:
        print(
            f"error: key file round-trip mismatch (path={key_file}, "
            f"expected_fp={key_fingerprint(plain_norm)}, "
            f"read_fp={key_fingerprint(plain_from_disk)})",
            file=sys.stderr,
        )
        raise SystemExit(1)
    cfg["api_key_red"] = hash_plaintext_key(plain_from_disk)
    try:
        write_yaml(cfg_path, cfg)
    except OSError as exc:
        print(f"error: cannot write config {cfg_path}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    _require_key_matches_on_disk(cfg_path, key_file, label="sync")
    return "rotated" if had_stored else "created"


def generate_plaintext_key() -> str:
    return secrets.token_urlsafe(32)


def cmd_verify(args: argparse.Namespace) -> int:
    cfg = read_yaml(args.config)
    if args.plaintext:
        plain = read_key_file(args.plaintext) if args.plaintext.is_file() else normalize_plaintext_key(
            args.plaintext.read_text(encoding="utf-8")
        )
    else:
        plain = ""
    if not plain:
        print("error: empty plaintext key", file=sys.stderr)
        return 1
    stored = str(cfg.get("api_key_red") or "")
    ok = verify_api_key(stored, plain)
    print("ok" if ok else "mismatch")
    return 0 if ok else 1


def cmd_sync(args: argparse.Namespace) -> int:
    cfg_path: Path = args.config
    key_file: Path = args.key_file
    cfg = read_yaml(cfg_path)
    stored = str(cfg.get("api_key_red") or "")

    if args.generate:
        plain = generate_plaintext_key()
    elif args.plaintext:
        plain = (
            read_key_file(args.plaintext)
            if args.plaintext.is_file()
            else normalize_plaintext_key(args.plaintext.read_text(encoding="utf-8"))
        )
    elif key_file.is_file():
        plain = read_key_file(key_file)
    elif stored and not is_hashed(stored):
        plain = normalize_plaintext_key(stored)
    else:
        print(
            "error: cannot recover plaintext API key from hashed default.yml — use --generate",
            file=sys.stderr,
        )
        return 2

    if not plain:
        print("error: empty API key", file=sys.stderr)
        return 2

    plain_norm = normalize_plaintext_key(plain)

    if stored and verify_api_key(stored, plain_norm):
        if not key_file.is_file() or read_key_file(key_file) != plain_norm:
            try:
                _write_key_file(key_file, plain_norm)
            except OSError as exc:
                print(f"error: cannot write key file {key_file}: {exc}", file=sys.stderr)
                return 1
        if not verify_api_key_red_on_disk(cfg_path, plain_norm):
            action = _persist_api_key_red(cfg_path, key_file, cfg, plain_norm, had_stored=True)
            print(action)
            return 0
        _require_key_matches_on_disk(cfg_path, key_file, label="sync")
        print("synced")
        return 0

    action = _persist_api_key_red(cfg_path, key_file, cfg, plain_norm, had_stored=bool(stored))
    print(action)
    return 0


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, default=Path("/opt/caldera/conf/default.yml"))
    common.add_argument("--key-file", type=Path, default=Path("/etc/xdr-lab/caldera-api-key"))

    p = argparse.ArgumentParser(description="Sync CALDERA api_key_red with /etc/xdr-lab/caldera-api-key")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_verify = sub.add_parser("verify", parents=[common], help="Verify plaintext matches config api_key_red")
    sp_verify.add_argument("--plaintext", type=Path, required=True)
    sp_verify.set_defaults(func=cmd_verify)

    sp_sync = sub.add_parser("sync", parents=[common], help="Write key file and update config hash when needed")
    sp_sync.add_argument("--generate", action="store_true", help="Generate a new API key")
    sp_sync.add_argument("--plaintext", type=Path, help="Use this plaintext key")
    sp_sync.set_defaults(func=cmd_sync)

    args = p.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
