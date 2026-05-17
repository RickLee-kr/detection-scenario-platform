#!/usr/bin/env python3
"""CALDERA api_key_red argon2 helpers — match app/utility/config_util.verify_hash."""

from __future__ import annotations

import hashlib
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit(f"PyYAML required: {exc}") from exc

HASH_PREFIX = "$argon2id$"
API_KEY_FIELDS = ("api_key_red", "api_key_blue")


def caldera_home() -> Path:
    return Path(os.environ.get("CALDERA_HOME", "/opt/caldera")).resolve()


def normalize_plaintext_key(value: str | bytes) -> str:
    """Match bootstrap read_key_file: strip ends, remove embedded \\r/\\n."""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = value
    return text.replace("\r", "").replace("\n", "").strip()


def read_key_file(path: Path) -> str:
    return normalize_plaintext_key(path.read_bytes())


def key_fingerprint(value: str) -> str:
    """Short SHA-256 prefix for debug logs (no secret material)."""
    norm = normalize_plaintext_key(value) if not is_hashed(value) else value.strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def log_key_verify_debug(plain: str, stored_hash: str, *, label: str) -> None:
    if not (os.environ.get("XDR_CALDERA_API_KEY_DEBUG") or "").strip():
        return
    msg = (
        f"debug: {label} plain_fp={key_fingerprint(plain)} "
        f"hash_fp={key_fingerprint(stored_hash)} "
        f"plain_len={len(normalize_plaintext_key(plain))} hash_len={len(stored_hash)}"
    )
    logger.debug(msg)
    print(msg, file=sys.stderr)


def is_hashed(val: object) -> bool:
    return isinstance(val, str) and val.startswith(HASH_PREFIX)


def _import_caldera_verify_hash():
    home = str(caldera_home())
    if home not in sys.path:
        sys.path.insert(0, home)
    from app.utility.config_util import verify_hash  # noqa: WPS433

    return verify_hash


def verify_api_key(stored: str, candidate: str) -> bool:
    if not stored or not candidate:
        return False
    plain = normalize_plaintext_key(candidate)
    if not is_hashed(stored):
        return stored.strip() == plain
    try:
        verify_hash = _import_caldera_verify_hash()
        return bool(verify_hash(stored, plain))
    except Exception:
        try:
            from argon2 import PasswordHasher
            from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
        except ImportError:
            return False
        ph = PasswordHasher()
        try:
            return bool(ph.verify(stored, plain))
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False


def hash_plaintext_key(plain: str) -> str:
    plain_norm = normalize_plaintext_key(plain)
    try:
        from argon2 import PasswordHasher
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(f"argon2-cffi required: {exc}") from exc
    return PasswordHasher().hash(plain_norm)


def load_config(path: Path) -> dict[str, Any]:
    """Load main config the same way CALDERA server.py does (yaml.FullLoader)."""
    text = path.read_text(encoding="utf-8")
    docs = list(yaml.load_all(text, Loader=yaml.FullLoader))
    if not docs or not isinstance(docs[0], dict):
        return {}
    return docs[0]


def hash_fields_single_quoted_in_text(text: str) -> bool:
    """True when every api_key_* argon2 line in YAML text uses a single-quoted scalar."""
    for field in API_KEY_FIELDS:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith(f"{field}:"):
                continue
            value = stripped.split(":", 1)[1].strip()
            if value.startswith(HASH_PREFIX) and not (value.startswith("'") and value.endswith("'")):
                return False
    return True


def dump_config(path: Path, data: dict[str, Any]) -> None:
    """Write YAML; force single-quoted argon2 hashes so '+' in digest is never mangled."""
    for field in API_KEY_FIELDS:
        val = data.get(field)
        if isinstance(val, str) and is_hashed(val):
            data[field] = val  # ensure str, not bytes

    def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.nodes.Node:
        if is_hashed(value):
            return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="'")
        return dumper.represent_scalar("tag:yaml.org,2002:str", value)

    class _CalderaDumper(yaml.SafeDumper):
        pass

    _CalderaDumper.add_representer(str, _represent_str)
    text = yaml.dump(
        data,
        Dumper=_CalderaDumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    if not hash_fields_single_quoted_in_text(text):
        lines: list[str] = []
        for line in text.splitlines():
            replaced = line
            for field in API_KEY_FIELDS:
                prefix = f"{field}:"
                if line.strip().startswith(prefix):
                    val = data.get(field)
                    if isinstance(val, str) and is_hashed(val):
                        indent = line[: len(line) - len(line.lstrip())]
                        escaped = val.replace("'", "''")
                        replaced = f"{indent}{field}: '{escaped}'"
            lines.append(replaced)
        text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    path.write_text(text, encoding="utf-8")


def verify_api_key_red_on_disk(config_path: Path, plain: str) -> bool:
    """Re-read config from disk and verify api_key_red matches plaintext (post-sync gate)."""
    stored = str(load_config(config_path).get("api_key_red") or "")
    if not stored:
        return False
    return verify_api_key(stored, plain)
