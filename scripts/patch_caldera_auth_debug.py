#!/usr/bin/env python3
"""Install XDR Lab CALDERA auth debug hooks into CALDERA_HOME (idempotent)."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

MARKER = "# XDR_LAB_AUTH_DEBUG"
CONFIG_PRESERVE_MARKER = "# XDR_LAB_CONFIG_PRESERVE"

PATCHES: dict[str, list[tuple[str, str]]] = {
    "app/utility/config_util.py": [
        (
            """def verify_hash(hash_val, target):
    \"\"\"
    Returns True if the argon2 hash for the target matches hash_val, False otherwise.
    Returns False for None or non-string inputs.
    \"\"\"
    if not isinstance(hash_val, str) or not isinstance(target, str):
        return False
    ph = PasswordHasher()
    try:
        return ph.verify(hash_val, target)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False""",
            f"""def verify_hash(hash_val, target):
    \"\"\"
    Returns True if the argon2 hash for the target matches hash_val, False otherwise.
    Returns False for None or non-string inputs.
    \"\"\"
    {MARKER}
    from app.utility.xdr_auth_debug import auth_debug_enabled, log_verify_hash

    if not isinstance(hash_val, str) or not isinstance(target, str):
        if auth_debug_enabled():
            log_verify_hash(hash_val, target, False, context='type_error')
        return False
    ph = PasswordHasher()
    try:
        result = ph.verify(hash_val, target)
        log_verify_hash(hash_val, target, bool(result), context='verify')
        return result
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        log_verify_hash(hash_val, target, False, context='verify_exception')
        return False""",
        ),
    ],
    "app/utility/base_world.py": [
        (
            "        if apply_hash:",
            f"        {MARKER}\n"
            "        from app.utility.xdr_auth_debug import log_config_load\n"
            "        log_config_load(name, overwrite_path, config)\n"
            "        if apply_hash:",
        ),
    ],
    "app/service/auth_svc.py": [
        (
            """    def request_has_valid_api_key(self, request):
        request_api_key = request.headers.get(HEADER_API_KEY)
        if request_api_key is None:
            return False
        for i in [CONFIG_API_KEY_RED, CONFIG_API_KEY_BLUE]:
            hashed_api_key = self.get_config(i)
            if hashed_api_key is not None and verify_hash(hashed_api_key, request_api_key):
                return True
        return False""",
            f"""    {MARKER}
    def request_has_valid_api_key(self, request):
        from app.utility.xdr_auth_debug import log_api_key_check, log_key_header
        request_api_key = request.headers.get(HEADER_API_KEY)
        req_path = getattr(request, 'path', '') or ''
        log_key_header(request_api_key, req_path)
        if request_api_key is None:
            return False
        for i in [CONFIG_API_KEY_RED, CONFIG_API_KEY_BLUE]:
            hashed_api_key = self.get_config(i)
            if hashed_api_key is not None and verify_hash(hashed_api_key, request_api_key):
                log_api_key_check(
                    req_path,
                    i == CONFIG_API_KEY_RED,
                    i == CONFIG_API_KEY_BLUE,
                    red_hash=self.get_config(CONFIG_API_KEY_RED),
                    blue_hash=self.get_config(CONFIG_API_KEY_BLUE),
                )
                return True
        log_api_key_check(
            req_path,
            False,
            False,
            red_hash=self.get_config(CONFIG_API_KEY_RED),
            blue_hash=self.get_config(CONFIG_API_KEY_BLUE),
        )
        return False""",
        ),
        (
            "    async def check_permissions(self, group, request):\n        try:\n            if self.request_has_valid_api_key(request):\n                return True",
            "    async def check_permissions(self, group, request):\n"
            "        from app.utility.xdr_auth_debug import log_check_permissions\n"
            "        try:\n"
            "            if self.request_has_valid_api_key(request):\n"
            "                log_check_permissions(getattr(request, 'path', '') or '', True, False, 'api_key')\n"
            "                return True",
        ),
        (
            "            await check_permission(request, group)\n        except (HTTPUnauthorized, HTTPForbidden):\n            return await self.login_redirect(request, use_template=False)",
            "            await check_permission(request, group)\n"
            "            log_check_permissions(getattr(request, 'path', '') or '', False, True, 'session')\n"
            "        except (HTTPUnauthorized, HTTPForbidden):\n"
            "            log_check_permissions(getattr(request, 'path', '') or '', False, False, 'redirect_login')\n"
            "            return await self.login_redirect(request, use_template=False)",
        ),
        (
            "    async def helper(*args, **params):\n        if len(args) > 1 and type(args[1]) is web_request.Request:\n            await args[0].auth_svc.check_permissions('app', args[1])",
            "    async def helper(*args, **params):\n"
            "        if len(args) > 1 and type(args[1]) is web_request.Request:\n"
            "            from app.utility.xdr_auth_debug import log_check_authorization\n"
            "            req = args[1]\n"
            "            log_check_authorization(getattr(func, '__name__', '?'), getattr(req, 'path', '') or '')\n"
            "            await args[0].auth_svc.check_permissions('app', args[1])",
        ),
    ],
    "app/service/app_svc.py": [
        (
            """    async def _save_configurations(self, main_config_file='default'):
        for cfg_name, cfg_file in [('main', main_config_file), ('agents', 'agents'), ('payloads', 'payloads')]:
            with open('conf/%s.yml' % cfg_file, 'w') as config:
                config.write(yaml.dump(self.get_config(name=cfg_name)))""",
            f"""    async def _save_configurations(self, main_config_file='default'):
        {CONFIG_PRESERVE_MARKER}
        from pathlib import Path as _Path
        preserved_api_keys = {{}}
        main_path = _Path('conf') / f'{{main_config_file}}.yml'
        if main_path.is_file():
            try:
                with open(main_path, encoding='utf-8') as _disk_f:
                    _disk_cfg = yaml.load(_disk_f, Loader=yaml.FullLoader) or {{}}
                for _key in ('api_key_red', 'api_key_blue'):
                    _val = _disk_cfg.get(_key)
                    if isinstance(_val, str) and _val:
                        preserved_api_keys[_key] = _val
            except Exception:
                pass
        for cfg_name, cfg_file in [('main', main_config_file), ('agents', 'agents'), ('payloads', 'payloads')]:
            cfg_data = self.get_config(name=cfg_name)
            if cfg_name == 'main' and preserved_api_keys:
                for _key, _val in preserved_api_keys.items():
                    cfg_data[_key] = _val
            with open('conf/%s.yml' % cfg_file, 'w') as config:
                config.write(yaml.dump(cfg_data))""",
        ),
    ],
    "app/api/rest_api.py": [
        (
            """    @check_authorization
    async def rest_core_info(self, request):
        try:""",
            """    @check_authorization
    async def rest_core_info(self, request):
        from app.utility.xdr_auth_debug import log_rest_core_info
        log_rest_core_info('rest_core_info', request.match_info.get('index', ''), request.method)
        try:""",
        ),
    ],
}

# Idempotent upgrades for trees already containing MARKER (v1 patches).
UPGRADE_PATCHES: dict[str, list[tuple[str, str]]] = {
    "app/service/auth_svc.py": [
        (
            "            log_check_authorization(getattr(func, '__name__', '?'), getattr(req, 'path', '') or '')",
            "            log_check_authorization(getattr(func, '__name__', '?'), req)",
        ),
        (
            "        if len(args) > 1 and type(args[1]) is web_request.Request:",
            "        if len(args) > 1 and isinstance(args[1], web.Request):",
        ),
        (
            """    async def login_redirect(self, request, use_template=True):
        \"\"\"Redirect user to login page using the configured login handler. Will fall back to the
        default login handler if an unexpected exception is raised.

        :param request:
        :param use_template: Determines if the login handler should return an html template rather than raise
            an HTTP redirect, if applicable. Defaults to True.
        :type use_template: bool, optional
        \"\"\"
        try:""",
            """    async def login_redirect(self, request, use_template=True):
        \"\"\"Redirect user to login page using the configured login handler. Will fall back to the
        default login handler if an unexpected exception is raised.

        :param request:
        :param use_template: Determines if the login handler should return an html template rather than raise
            an HTTP redirect, if applicable. Defaults to True.
        :type use_template: bool, optional
        \"\"\"
        from app.utility.xdr_auth_debug import log_http_redirect
        log_http_redirect(
            'auth_svc.login_redirect',
            '/login',
            getattr(request, 'path', '') or '',
            f'use_template={use_template} handler={getattr(self._login_handler, "name", "?")}',
        )
        try:""",
        ),
    ],
    "app/service/login_handlers/default.py": [
        (
            "        else:\n            raise web.HTTPFound('/login')",
            "        else:\n"
            "            from app.utility.xdr_auth_debug import log_http_redirect\n"
            "            log_http_redirect(\n"
            "                'default_login_handler.handle_login_redirect',\n"
            "                '/login',\n"
            "                getattr(request, 'path', '') or '',\n"
            "                'use_template=False',\n"
            "            )\n"
            "            raise web.HTTPFound('/login')",
        ),
    ],
}


def apply_patch_file(
    path: Path,
    replacements: list[tuple[str, str]],
    *,
    skip_if_marker: bool = True,
    marker: str = MARKER,
) -> bool:
    text = path.read_text(encoding="utf-8")
    if skip_if_marker and marker in text:
        return False
    original = text
    for old, new in replacements:
        if old not in text:
            if skip_if_marker and marker in text:
                return False
            print(f"error: anchor not found in {path}: {old[:60]!r}…", file=sys.stderr)
            sys.exit(1)
        text = text.replace(old, new, 1)
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> int:
    p = argparse.ArgumentParser(description="Patch CALDERA for XDR auth debug logging")
    p.add_argument("--caldera-home", type=Path, default=Path("/opt/caldera"))
    p.add_argument("--patch-dir", type=Path, default=Path(__file__).resolve().parent.parent / "patches" / "caldera")
    p.add_argument("--upgrade", action="store_true", help="Apply v2 tracing upgrades to already-patched tree")
    args = p.parse_args()
    home = args.caldera_home.resolve()
    if not (home / "server.py").is_file():
        print(f"error: CALDERA not found at {home}", file=sys.stderr)
        return 2

    dest_debug = home / "app" / "utility" / "xdr_auth_debug.py"
    src_debug = args.patch_dir / "xdr_auth_debug.py"
    shutil.copy2(src_debug, dest_debug)
    print(f"installed {dest_debug}")

    changed = 0
    if args.upgrade:
        for rel, reps in UPGRADE_PATCHES.items():
            target = home / rel
            if apply_patch_file(target, reps, skip_if_marker=False):
                print(f"upgraded {target}")
                changed += 1
    else:
        for rel, reps in PATCHES.items():
            target = home / rel
            patch_marker = CONFIG_PRESERVE_MARKER if rel == "app/service/app_svc.py" else MARKER
            if apply_patch_file(target, reps, marker=patch_marker):
                print(f"patched {target}")
                changed += 1
            else:
                print(f"already patched {target}")

    print(f"done (files_changed={changed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
