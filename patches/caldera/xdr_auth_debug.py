"""XDR Lab CALDERA auth diagnostics (enable with XDR_CALDERA_AUTH_DEBUG=1)."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

_LOG = logging.getLogger("caldera.xdr.auth")
_MAIN_CONFIG_SOURCE: dict[str, str] = {}


def auth_debug_enabled() -> bool:
    return os.environ.get("XDR_CALDERA_AUTH_DEBUG", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _hash_prefix(val: object) -> str:
    if not isinstance(val, str) or not val:
        return "<empty>"
    if val.startswith("$argon2id$"):
        return val[:28] + "…"
    return "<plaintext:" + str(len(val)) + " chars>"


def log_config_load(name: str, source_path: str, config: dict[str, Any]) -> None:
    if not auth_debug_enabled():
        return
    path = source_path or "<memory>"
    if name == "main" and source_path:
        _MAIN_CONFIG_SOURCE["main"] = os.path.abspath(source_path)
    red = config.get("api_key_red")
    blue = config.get("api_key_blue")
    _LOG.info(
        "config_load name=%s source=%s api_key_red=%s api_key_blue=%s",
        name,
        path,
        _hash_prefix(red),
        _hash_prefix(blue),
    )


def runtime_main_config_source() -> str:
    return _MAIN_CONFIG_SOURCE.get("main", "<unknown>")


def log_verify_hash(hash_val: object, target: object, result: bool, context: str = "") -> None:
    if not auth_debug_enabled():
        return
    tlen = len(target) if isinstance(target, str) else 0
    _LOG.info(
        "verify_hash ctx=%s main_source=%s hash=%s target_len=%d result=%s",
        context or "default",
        runtime_main_config_source(),
        _hash_prefix(hash_val),
        tlen,
        result,
    )


def log_request_headers(request: Any, path: str = "") -> None:
    if not auth_debug_enabled():
        return
    try:
        names = sorted({k for k in request.headers.keys()})
    except Exception:
        names = []
    has_key = any(str(k).upper() == "KEY" for k in names)
    _LOG.info(
        "request_headers path=%s has_KEY=%s header_names=%s",
        path or "?",
        has_key,
        ",".join(names) if names else "<none>",
    )


def log_key_header(request_api_key: Optional[str], path: str = "") -> None:
    if not auth_debug_enabled():
        return
    if request_api_key is None:
        _LOG.info("KEY_header path=%s present=false", path or "?")
        return
    _LOG.info("KEY_header path=%s present=true len=%d", path or "?", len(request_api_key))


def log_api_key_check(
    request_path: str,
    matched_field: str,
    *,
    red_hash: object = None,
    blue_hash: object = None,
) -> None:
    if not auth_debug_enabled():
        return
    _LOG.info(
        "request_has_valid_api_key path=%s matched=%s main_source=%s runtime_red=%s runtime_blue=%s",
        request_path,
        matched_field or "none",
        runtime_main_config_source(),
        _hash_prefix(red_hash),
        _hash_prefix(blue_hash),
    )


def log_check_permissions(request_path: str, via_api_key: bool, via_session: bool, outcome: str) -> None:
    if not auth_debug_enabled():
        return
    _LOG.info(
        "check_permissions path=%s via_api_key=%s via_session=%s outcome=%s main_source=%s",
        request_path,
        via_api_key,
        via_session,
        outcome,
        runtime_main_config_source(),
    )


def log_check_authorization(handler: str, request: Any) -> None:
    if not auth_debug_enabled():
        return
    path = getattr(request, "path", "") or ""
    req_type = type(request).__name__
    _LOG.info(
        "check_authorization handler=%s path=%s request_type=%s auth_path=auth_svc.check_permissions",
        handler,
        path,
        req_type,
    )
    log_request_headers(request, path)


def log_http_redirect(source: str, location: str, path: str = "", extra: str = "") -> None:
    if not auth_debug_enabled():
        return
    _LOG.info(
        "http_redirect source=%s location=%s path=%s %s",
        source,
        location,
        path or "?",
        extra.strip(),
    )


def log_rest_core_info(handler: str, index: str, method: str) -> None:
    if not auth_debug_enabled():
        return
    _LOG.info(
        "rest_core_info handler=%s method=%s index=%s route=GET /api/{index}",
        handler,
        method,
        index,
    )
