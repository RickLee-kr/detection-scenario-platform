#!/usr/bin/env python3
"""Diagnose CALDERA main config path and api_key_red vs key file (read-only)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    print(json.dumps({"error": f"PyYAML required: {exc}"}), file=sys.stderr)
    sys.exit(2)

from caldera_key_crypto import (
    API_KEY_FIELDS,
    is_hashed,
    load_config,
    read_key_file,
    verify_api_key,
)


def parse_environment_from_execstart(execstart: str) -> str:
    """Return CALDERA -E/--environment value (default: local; --insecure → default)."""
    if not execstart:
        return "default"
    if re.search(r"(?:^|\s)--insecure(?:\s|$)", execstart):
        return "default"
    m = re.search(r"(?:-E|--environment)(?:=|\s+)([A-Za-z0-9_-]+)", execstart)
    if m:
        return m.group(1)
    return "local"


def resolve_main_config(caldera_home: Path, execstart: str = "") -> Path:
    env = parse_environment_from_execstart(execstart)
    return caldera_home / "conf" / f"{env}.yml"


def read_unit_execstart(unit_path: Path) -> str:
    if not unit_path.is_file():
        return ""
    for line in unit_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("ExecStart="):
            return line.split("=", 1)[1].strip()
    return ""


def diag(args: argparse.Namespace) -> dict:
    home = Path(args.caldera_home).resolve()
    unit_path = Path(args.unit_path)
    execstart = args.execstart or read_unit_execstart(unit_path)
    main_config = Path(args.config) if args.config else resolve_main_config(home, execstart)
    key_file = Path(args.key_file)

    conf_dir = home / "conf"
    conf_files = sorted(p.name for p in conf_dir.glob("*.yml") if p.is_file()) if conf_dir.is_dir() else []

    overrides: list[dict[str, str]] = []
    for name in ("local.yml", "chain.yml"):
        p = conf_dir / name
        overrides.append({"name": name, "path": str(p), "exists": p.is_file()})

    main_exists = main_config.is_file()
    api_keys: dict[str, object] = {}
    key_verify: dict[str, object] = {
        "readable": False,
        "matches_api_key_red": False,
        "matches_api_key_blue": False,
        "verify_backend": "caldera_key_crypto",
    }

    data: dict = {}
    if main_exists:
        data = load_config(main_config)
        for field in API_KEY_FIELDS:
            val = data.get(field)
            if isinstance(val, str) and val:
                api_keys[field] = {
                    "hashed": is_hashed(val),
                    "prefix": val[:28] + "…" if len(val) > 28 else val,
                }

    plain_key = ""
    if key_file.is_file():
        try:
            plain_key = read_key_file(key_file)
            key_verify["readable"] = True
        except OSError as exc:
            key_verify["read_error"] = str(exc)

    if main_exists and plain_key and data:
        red = str(data.get("api_key_red") or "")
        blue = str(data.get("api_key_blue") or "")
        key_verify["matches_api_key_red"] = verify_api_key(red, plain_key)
        key_verify["matches_api_key_blue"] = verify_api_key(blue, plain_key)
    elif not key_verify.get("readable"):
        key_verify["matches_api_key_red"] = None
        key_verify["matches_api_key_blue"] = None

    return {
        "caldera_home": str(home),
        "working_directory_expected": str(home),
        "systemd_unit": str(unit_path),
        "execstart": execstart,
        "environment": parse_environment_from_execstart(execstart),
        "main_config_path": str(main_config),
        "main_config_exists": main_exists,
        "conf_yml_files": conf_files,
        "override_candidates": overrides,
        "api_keys_in_main": api_keys,
        "key_file": str(key_file),
        "key_file_exists": key_file.is_file(),
        "key_verify": key_verify,
        "caldera_loads": (
            f"{main_config.name} as BaseWorld 'main' config "
            f"(server.py -E {parse_environment_from_execstart(execstart)}; --insecure forces default.yml)"
        ),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="CALDERA config / API key diagnostics")
    p.add_argument("--caldera-home", type=Path, default=Path("/opt/caldera"))
    p.add_argument("--unit-path", type=Path, default=Path("/etc/systemd/system/caldera.service"))
    p.add_argument("--config", type=Path, default=None, help="Override main config path")
    p.add_argument("--key-file", type=Path, default=Path("/etc/xdr-lab/caldera-api-key"))
    p.add_argument("--execstart", default="", help="Override parsed ExecStart line")
    p.add_argument("--format", choices=("json", "shell"), default="json")
    p.add_argument(
        "--require-key-match",
        action="store_true",
        help="Exit 1 unless key file matches api_key_red (requires readable key file)",
    )
    args = p.parse_args()
    doc = diag(args)
    if args.format == "shell":
        for k, v in doc.items():
            if isinstance(v, (dict, list)):
                print(f"{k}={json.dumps(v, ensure_ascii=False)}")
            else:
                print(f"{k}={v}")
    else:
        print(json.dumps(doc, indent=2, sort_keys=True))

    if args.require_key_match:
        kv = doc.get("key_verify") or {}
        if kv.get("matches_api_key_red") is not True:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
