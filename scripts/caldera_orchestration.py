#!/usr/bin/env python3
"""MITRE CALDERA orchestration for XDR Lab (BAS / adversary emulation).

Delegates attack emulation to CALDERA *operations* via the official /api/rest
contract (PUT create_operation, POST update_operation). Does not implement
standalone shell-script attacks.

State:
  ${XDR_RUNTIME_STATE_DIR}/scenario.json   — operator scenario view
  ${XDR_RUNTIME_STATE_DIR}/caldera.json    — server reachability + deployment hints

Env:
  XDR_BASE / XDR_ROOT          — lab root (default /opt/xdr-lab)
  XDR_LAB_DRY_RUN=1            — no CALDERA HTTP mutations; snapshot-before logs only (dry_run_skipped + pre-recorded name)
  XDR_CALDERA_API_KEY          — ignored when it differs from api_key_file (default /etc/xdr-lab/caldera-api-key)
  XDR_CALDERA_SESSION_COOKIE   — optional UI session cookie (CALDERA REST uses KEY header, not Bearer)
  XDR_LAB_SCENARIO_PACK_STRICT=1 — scenario list fails if any pack file under scenarios/ is invalid JSON/YAML
  scenario pack validate — static pack checks (fields, lab-vms, parse) before run; see docs/caldera-integration.md §4.5
  scenario bootstrap validate — CALDERA HTTP, API key, plugins/atomic, ART paths, repo bootstrap scripts; see docs §5.1b
  scenario atomic validate — guest ART paths and exec readiness on victim-linux / windows-victim over SSH; see docs §5.1c
  scenario telemetry <id|last> — operator checklist from expected_telemetry + last_history; see docs/caldera-integration.md
  scenario telemetry verify — reserved extension point (no auto-verdict); see docs/caldera-integration.md («Future: lab scenario telemetry verify»)
  scenario run — emits JSONL scenario_preflight_* + scenario_run_ready + scenario_live_run_* (live only; see docs)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shlex
import ssl
import subprocess
import sys
import tempfile
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urljoin, urlparse

# CALDERA 5.x: app/service/auth_svc.py HEADER_API_KEY (not Authorization/Bearer).
CALDERA_API_AUTH_HEADER = "KEY"

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
try:
    from vm_runtime_state import (
        collect_domifaddr_ipv4,
        domstate,
        domain_exists,
        expected_ip_for_vm,
        pick_ssh_user,
        primary_bind_ipv4,
        ssh_batch_cmd,
        tcp_port_open,
    )
except ImportError:  # pragma: no cover — packaged layout should always include sibling module
    collect_domifaddr_ipv4 = None  # type: ignore[misc, assignment]
    domstate = None  # type: ignore[misc, assignment]
    domain_exists = None  # type: ignore[misc, assignment]
    expected_ip_for_vm = None  # type: ignore[misc, assignment]
    pick_ssh_user = None  # type: ignore[misc, assignment]
    primary_bind_ipv4 = None  # type: ignore[misc, assignment]
    ssh_batch_cmd = None  # type: ignore[misc, assignment]
    tcp_port_open = None  # type: ignore[misc, assignment]

# ---------------------------------------------------------------------------
# Time / IO
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso_utc(ts: Any) -> datetime | None:
    """Parse scenario.json ISO timestamps (…Z suffix). Returns None if unparsable."""
    s = str(ts or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def operation_duration_seconds_between(started_at: Any, stopped_at: Any) -> float | None:
    a = _parse_iso_utc(started_at)
    b = _parse_iso_utc(stopped_at)
    if a is None or b is None:
        return None
    return max(0.0, (b - a).total_seconds())


def format_ts_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def coerce_timestamp_string_to_z(val: str) -> str | None:
    """Normalize a parseable ISO-8601 timestamp string to UTC …Z (additive formatting)."""
    s = str(val or "").strip()
    if not s:
        return None
    dt = _parse_iso_utc(s)
    if dt is None:
        return None
    return format_ts_z(dt)


_TIMEISH_JSON_KEYS = frozenset(
    {
        "ts",
        "utc",
        "timestamp",
        "last_probe_utc",
        "last_verified_time",
        "updated_utc",
        "created_utc",
        "started_utc",
        "finished_utc",
    }
)


def _dict_key_suggests_timestamp(key: str) -> bool:
    lk = str(key).lower()
    if lk in _TIMEISH_JSON_KEYS:
        return True
    return lk.endswith("_utc") or lk.endswith("_at")


def normalize_timestamp_values_inplace(obj: Any) -> None:
    """Recursively coerce timestamp-like string fields to UTC Z (runtime JSON artifacts only)."""
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if isinstance(v, str) and _dict_key_suggests_timestamp(k):
                z = coerce_timestamp_string_to_z(v)
                if z is not None:
                    obj[k] = z
            else:
                normalize_timestamp_values_inplace(v)
    elif isinstance(obj, list):
        for item in obj:
            normalize_timestamp_values_inplace(item)


def _jsonl_normalize_field_value(key: str, val: Any) -> Any:
    if isinstance(val, str) and _dict_key_suggests_timestamp(key):
        z = coerce_timestamp_string_to_z(val)
        return z if z is not None else val
    return val


def jsonl_event_summary(event: str, fields: Mapping[str, Any]) -> str | None:
    """One-line English operator summary for JSONL (optional; additive)."""
    f = dict(fields)

    def _s(k: str) -> str:
        v = f.get(k)
        return str(v).strip() if v is not None else ""

    scen = _s("scenario") or _s("scenario_name")
    run = _s("run_id")
    head = f"{scen}: " if scen else ""
    run_tag = f"run_id={run[:8]}..." if len(run) > 8 else (f"run_id={run}" if run else "")
    tail = f" ({run_tag})" if run_tag else ""

    if event == "scenario_preflight_started":
        return f"{head}Preflight started{tail}.".strip()
    if event == "scenario_preflight_completed":
        return (
            f"{head}Preflight finished: warnings={f.get('warning_count')}, "
            f"blocking={f.get('blocking_count')}, live_gate_failures={f.get('live_gate_failure_count')}, "
            f"bootstrap_ok={f.get('bootstrap_ok')}{tail}"
        )
    if event == "scenario_preflight_warning":
        return f"{head}Preflight warning [{_s('code')}]: {_s('message')[:160]}"
    if event == "scenario_preflight_failed":
        return f"{head}Preflight blocked (reason={_s('reason')}){tail}"
    if event in ("scenario_operation_failed", "scenario_live_run_failed"):
        return f"{head}Run failed: phase={_s('phase') or '-'} error={_s('error') or _s('reason')}{tail}"
    if event == "scenario_run_ready":
        return f"{head}Preflight gates cleared; ready to submit CALDERA operation{tail}"
    if event == "scenario_live_run_started":
        return f"{head}Live run started on appliance (CALDERA operation submit follows){tail}"
    if event == "scenario_live_run_submitted":
        oid = _s("caldera_operation_id")
        oshort = f"{oid[:12]}..." if len(oid) > 12 else (oid or "?")
        return f"{head}CALDERA operation submitted id={oshort}{tail}"
    if event == "scenario_live_run_completed":
        return f"{head}Live run stop/finish recorded (see operation_duration_seconds){tail}"
    if event == "scenario_post_run_review_recommended":
        return f"{head}Post-run: manual telemetry + CALDERA UI review recommended{tail}"
    if event == "scenario_operation_started":
        return f"{head}Scenario operation phase started (dry_run={f.get('dry_run')}){tail}"
    if event == "scenario_operation_completed":
        return f"{head}Scenario operation phase completed: note={_s('note')}{tail}"
    if event == "snapshot_before_requested":
        return f"{head}Pre-run snapshot requested: {_s('snapshot_name')}{tail}"
    if event == "snapshot_before_created":
        return f"{head}Pre-run snapshot created: {_s('snapshot_name')}{tail}"
    if event == "snapshot_before_failed":
        return f"{head}Pre-run snapshot failed: {_s('snapshot_name')} reason={_s('reason') or 'rc'}{tail}"
    if event == "caldera_server_started":
        return f"CALDERA became reachable at {_s('base_url') or 'base_url'}"
    if event == "caldera_agent_connected":
        return f"Sandcat matched lab role {_s('vm')}"
    if event == "caldera_agents_fetch_failed":
        err = _s("error")
        if err == "api_key_missing":
            return (
                "GET /api/agents: CALDERA API key missing "
                "(run: sudo bootstrap/ensure-caldera-api-key.sh — docs §3)"
            )
        if err == "api_key_invalid":
            hdr = _s("auth_header") or CALDERA_API_AUTH_HEADER
            return (
                f"GET /api/agents: CALDERA rejected {hdr} header "
                f"(http_code={f.get('http_code')} location={f.get('location') or '-'}) "
                "(re-sync: sudo bootstrap/ensure-caldera-api-key.sh; unset stale XDR_CALDERA_API_KEY)"
            )
        if err == "auth_required":
            return (
                "GET /api/agents requires CALDERA authentication "
                "(configure API key — docs/caldera-integration.md §3)"
            )
        hdr = _s("auth_header") or CALDERA_API_AUTH_HEADER
        return (
            f"GET /api/agents failed: header={hdr} http_code={f.get('http_code')} "
            f"location={f.get('location') or '-'} error={err or '-'}"
        )
    if event == "caldera_agent_deploy_preflight_failed":
        return f"Agent deploy preflight failed: {_s('reason')}"
    if event == "caldera_bootstrap_validate_finished":
        return f"Bootstrap validate finished: ok={f.get('ok')} base_url={_s('base_url')}"
    if event == "scenario_telemetry_verify_placeholder":
        return (
            f"Telemetry verify placeholder (dry_run={f.get('dry_run')}); "
            "no automated verdict — use `scenario telemetry last`."
        )
    if event.startswith("scenario_live_run_"):
        return f"{head}{event}{tail}"
    if event.startswith("caldera_agent_"):
        return f"{event}: vm={_s('vm') or '-'} status={_s('status') or '-'}"
    return None


def attach_last_history_timing(last_hist: dict[str, Any]) -> None:
    """Additive-only: sets operation_duration_seconds when started_at/stopped_at parse."""
    sec = operation_duration_seconds_between(last_hist.get("started_at"), last_hist.get("stopped_at"))
    if sec is not None:
        last_hist["operation_duration_seconds"] = round(sec, 3)


# Canonical lab L2 contract (display-only for operator hints; config remains authoritative).
_LAB_VM_IP_HINTS: dict[str, str] = {
    "sensor-vm": "10.10.10.10",
    "victim-linux": "10.10.10.20",
    "windows-victim": "10.10.10.30",
}


def dry_run() -> bool:
    return os.environ.get("XDR_LAB_DRY_RUN", "").strip() in ("1", "true", "yes", "on")


_JSONL_LOG_WARNED = False


def _jsonl_tmp_fallback_path(primary: Path) -> Path:
    import getpass

    return Path("/tmp") / f"xdr-lab-logs-{getpass.getuser()}" / primary.name


def log_jsonl(
    log_path: Path | None,
    event: str,
    *,
    summary: str | None = None,
    **fields: Any,
) -> None:
    """Append one JSONL record: stable key order (ts, event, optional summary, then sorted fields).

    Additive-only: existing event names unchanged; optional ``summary`` is emitted when non-empty.
    File append failures emit a one-time WARN and fall back to /tmp then stderr (orchestration continues).
    """
    global _JSONL_LOG_WARNED
    norm: dict[str, Any] = {}
    for k, v in fields.items():
        norm[str(k)] = _jsonl_normalize_field_value(str(k), v)
    summ = (summary or "").strip() or jsonl_event_summary(event, norm)
    rec: dict[str, Any] = {"ts": utc_now(), "event": event}
    if summ:
        rec["summary"] = summ
    for k in sorted(norm.keys()):
        rec[k] = norm[k]
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    if dry_run():
        print(line, end="", file=sys.stderr)
        return
    if not log_path:
        print(line, end="", file=sys.stderr)
        return

    targets: list[Path] = [log_path, _jsonl_tmp_fallback_path(log_path)]
    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as f:
                f.write(line)
            if target != log_path and not _JSONL_LOG_WARNED:
                print(
                    f"WARN: jsonl log not writable: {log_path}; fallback={target}",
                    file=sys.stderr,
                )
                _JSONL_LOG_WARNED = True
            return
        except OSError:
            continue

    if not _JSONL_LOG_WARNED:
        print(f"WARN: jsonl log not writable: {log_path}; fallback=stderr", file=sys.stderr)
        _JSONL_LOG_WARNED = True
    print(line, end="", file=sys.stderr)


_STATE_JSON_WARNED = False


def save_json_atomic(path: Path, data: Mapping[str, Any]) -> None:
    global _STATE_JSON_WARNED
    if dry_run():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = json.loads(json.dumps(dict(data), ensure_ascii=False))
    normalize_timestamp_values_inplace(doc)
    text = json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    try:
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent), text=True)
    except OSError as e:
        if dry_run() and not _STATE_JSON_WARNED:
            print(f"WARN: state file not writable: {path} ({e}); dry-run continues", file=sys.stderr)
            _STATE_JSON_WARNED = True
        elif not _STATE_JSON_WARNED:
            print(f"WARN: state file not writable: {path} ({e})", file=sys.stderr)
            _STATE_JSON_WARNED = True
        if dry_run():
            return
        raise
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        if dry_run():
            if not _STATE_JSON_WARNED:
                print(f"WARN: state file write failed: {path}; dry-run continues", file=sys.stderr)
                _STATE_JSON_WARNED = True
            return
        raise


def load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


# ---------------------------------------------------------------------------
# CALDERA HTTP (urllib; no extra deps)
# ---------------------------------------------------------------------------


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Do not follow redirects — CALDERA unauthenticated /api/* often 302 → /login."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


_CALDERA_HTTP_OPENER: urllib.request.OpenerDirector | None = None


def _caldera_http_opener() -> urllib.request.OpenerDirector:
    global _CALDERA_HTTP_OPENER
    if _CALDERA_HTTP_OPENER is None:
        _CALDERA_HTTP_OPENER = urllib.request.build_opener(_NoRedirectHandler())
    return _CALDERA_HTTP_OPENER


def _header_value(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    val = headers.get(name) if hasattr(headers, "get") else None
    if val is None and hasattr(headers, "get_all"):
        vals = headers.get_all(name) or headers.get_all(name.lower())
        if vals:
            val = vals[-1]
    if val is None:
        return None
    return str(val).strip() or None


def _path_suggests_login(url_or_path: str | None) -> bool:
    if not url_or_path:
        return False
    try:
        path = urlparse(url_or_path).path or url_or_path
    except ValueError:
        path = url_or_path
    return "/login" in str(path).lower()


def _looks_like_login_html(raw: str, content_type: str | None) -> bool:
    ct = (content_type or "").lower()
    if "application/json" in ct:
        return False
    body = raw.lower()[:8000]
    if "<html" not in body and "<!doctype html" not in body:
        return False
    return any(tok in body for tok in ("login", "password", "sign in", "sign-in", "/login"))


def classify_caldera_http_error(
    code: int,
    raw: str,
    *,
    location: str | None,
    content_type: str | None,
    final_url: str | None,
    api_key: str,
    parse_error: str | None = None,
) -> str | None:
    """Map HTTP response to a stable operator error code (or None on success)."""
    if code in (401, 403):
        return "auth_required"
    if code in (301, 302, 303, 307, 308) and (
        _path_suggests_login(location) or _path_suggests_login(final_url)
    ):
        return "auth_required"
    if code == 200 and parse_error == "json_decode_error":
        if _path_suggests_login(final_url) or _looks_like_login_html(raw, content_type):
            return "auth_required"
        if not str(api_key or "").strip():
            return "auth_required"
    if parse_error:
        return parse_error
    if code >= 400:
        return f"http_{code}:{raw[:800]}"
    return None


@dataclass
class CalderaClient:
    base_url: str
    api_key: str
    session_cookie: str = ""
    timeout_sec: float = 12.0
    last_location: str | None = field(default=None, init=False, repr=False)
    last_content_type: str | None = field(default=None, init=False, repr=False)
    last_auth_header: str | None = field(default=None, init=False, repr=False)

    def _ctx(self) -> ssl.SSLContext | None:
        u = urlparse(self.base_url)
        if u.scheme == "https":
            ctx = ssl.create_default_context()
            return ctx
        return None

    def _auth_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers[CALDERA_API_AUTH_HEADER] = self.api_key
            self.last_auth_header = CALDERA_API_AUTH_HEADER
        else:
            self.last_auth_header = None
        if self.session_cookie:
            headers["Cookie"] = self.session_cookie
        return headers

    def request_json(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        log_path: Path | None = None,
    ) -> tuple[int, Any | None, str | None]:
        data_bytes = None
        headers = self._auth_headers()
        if body is not None:
            data_bytes = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        ctx = self._ctx()
        if ctx is not None:
            handlers: list[Any] = [_NoRedirectHandler(), urllib.request.HTTPSHandler(context=ctx)]
            opener = urllib.request.build_opener(*handlers)
        else:
            opener = _caldera_http_opener()
        try:
            resp = opener.open(req, timeout=self.timeout_sec)
            try:
                raw = resp.read().decode("utf-8", errors="replace")
                code = int(resp.status)
                location = _header_value(resp.headers, "Location")
                content_type = _header_value(resp.headers, "Content-Type")
                self.last_location = location
                self.last_content_type = content_type
                final_url = resp.geturl()
                if not raw.strip():
                    err = classify_caldera_http_error(
                        code,
                        raw,
                        location=location,
                        content_type=content_type,
                        final_url=final_url,
                        api_key=self.api_key,
                    )
                    return code, None, err
                try:
                    parsed = json.loads(raw)
                    err = classify_caldera_http_error(
                        code,
                        raw,
                        location=location,
                        content_type=content_type,
                        final_url=final_url,
                        api_key=self.api_key,
                    )
                    if err:
                        return code, None, err
                    return code, parsed, None
                except json.JSONDecodeError:
                    err = classify_caldera_http_error(
                        code,
                        raw,
                        location=location,
                        content_type=content_type,
                        final_url=final_url,
                        api_key=self.api_key,
                        parse_error="json_decode_error",
                    )
                    return code, raw, err
            finally:
                resp.close()
        except urllib.error.HTTPError as e:
            try:
                raw = e.read().decode("utf-8", errors="replace")
            except OSError:
                raw = ""
            location = _header_value(e.headers, "Location")
            content_type = _header_value(e.headers, "Content-Type")
            self.last_location = location
            self.last_content_type = content_type
            final_url = e.geturl() if hasattr(e, "geturl") else url
            err = classify_caldera_http_error(
                int(e.code),
                raw,
                location=location,
                content_type=content_type,
                final_url=final_url,
                api_key=self.api_key,
            )
            if not err:
                err = f"http_{e.code}:{raw[:800]}"
            return int(e.code), None, err
        except urllib.error.URLError as e:
            err = f"url_error:{e.reason!s}"
            return 0, None, err

    def rest_put(self, payload: dict[str, Any], log_path: Path | None) -> tuple[int, Any | None, str | None]:
        url = urljoin(self.base_url.rstrip("/") + "/", "api/rest")
        return self.request_json("PUT", url, body=payload, log_path=log_path)

    def rest_post(self, payload: dict[str, Any], log_path: Path | None) -> tuple[int, Any | None, str | None]:
        url = urljoin(self.base_url.rstrip("/") + "/", "api/rest")
        return self.request_json("POST", url, body=payload, log_path=log_path)

    def get_index(self, index: str, log_path: Path | None) -> tuple[int, Any | None, str | None]:
        url = urljoin(self.base_url.rstrip("/") + "/", f"api/{index}")
        return self.request_json("GET", url, body=None, log_path=log_path)


DEFAULT_CALDERA_API_KEY_FILE = Path("/etc/xdr-lab/caldera-api-key")


def caldera_api_key_file_path(cfg: dict[str, Any]) -> Path:
    key_file = str(cfg.get("api_key_file") or "").strip()
    if key_file:
        return Path(key_file)
    return DEFAULT_CALDERA_API_KEY_FILE


def read_caldera_key_file(path: Path) -> str:
    if str(_SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPT_DIR))
    from caldera_api_key_resolve import read_key_file_if_readable

    return read_key_file_if_readable(path) or ""


def log_caldera_auth_journal(*, max_lines: int = 20) -> None:
    """Recent caldera.xdr.auth lines from journalctl (when auth debug patch is enabled)."""
    try:
        proc = subprocess.run(
            ["journalctl", "-u", "caldera.service", "-n", "100", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    hits = [ln for ln in (proc.stdout or "").splitlines() if "caldera.xdr.auth" in ln]
    if not hits:
        return
    print("[caldera.xdr.auth — recent journal]", file=sys.stderr)
    for ln in hits[-max_lines:]:
        print(f"  {ln}", file=sys.stderr)


def resolve_api_key(
    cfg: dict[str, Any],
    *,
    xdr_root: Path | None = None,
    warn_stale_env: bool = True,
) -> str:
    """Readable api_key_file or runtime copy; never reads unreadable /etc without sudo."""
    if str(_SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPT_DIR))
    from caldera_api_key_resolve import resolve_api_key as _resolve_cli_key

    root = xdr_root
    if root is None:
        try:
            root = Path(cfg.get("_xdr_root") or os.environ.get("XDR_ROOT") or os.environ.get("XDR_BASE") or "/opt/xdr-lab")
        except Exception:
            root = Path("/opt/xdr-lab")
    return _resolve_cli_key(cfg, xdr_root=root, warn_stale_env=warn_stale_env)


def resolve_session_cookie(cfg: dict[str, Any]) -> str:
    """Optional UI session cookie (KEY header is the primary REST auth)."""
    if os.environ.get("XDR_CALDERA_SESSION_COOKIE"):
        return os.environ["XDR_CALDERA_SESSION_COOKIE"].strip()
    cookie_file = str(cfg.get("session_cookie_file") or "").strip()
    if cookie_file:
        p = Path(cookie_file)
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
    env_name = str(cfg.get("session_cookie_env") or "XDR_CALDERA_SESSION_COOKIE").strip()
    return os.environ.get(env_name, "").strip()


def make_caldera_client(cfg: dict[str, Any], *, timeout_sec: float = 12.0) -> CalderaClient:
    base_url = str(cfg.get("base_url") or "http://127.0.0.1:8888")
    return CalderaClient(
        base_url,
        resolve_api_key(cfg),
        session_cookie=resolve_session_cookie(cfg),
        timeout_sec=timeout_sec,
    )


def load_lab_config(xdr_root: Path) -> dict[str, Any]:
    p = xdr_root / "config" / "caldera-lab.json"
    base = load_json(
        p,
        {
            "schema_version": 1,
            "base_url": "http://127.0.0.1:8888",
            "api_key_env": "XDR_CALDERA_API_KEY",
            "api_key_file": "/etc/xdr-lab/caldera-api-key",
            "default_planner": "atomic",
            "default_group": "red",
            "deployment": {},
            "scenarios": {},
            "agent_vm_map": {},
            "scenario_pack_dirs": [],
        },
    )
    if not isinstance(base, dict):
        return {}
    return base


# ---------------------------------------------------------------------------
# Scenario packs (scenarios/*.json|yaml + optional config/scenarios/)
# ---------------------------------------------------------------------------


@dataclass
class ResolvedScenario:
    """Single runnable scenario: pack-backed and/or caldera-lab.json legacy."""

    scenario_id: str
    display_name: str
    description: str
    target_vms: list[str]
    adversary_id: str | None
    group: str
    planner: str
    expected_telemetry: Any
    safety_notes: str
    cleanup_notes: str
    source: str
    path: Path | None = None


def scenario_pack_strict() -> bool:
    return os.environ.get("XDR_LAB_SCENARIO_PACK_STRICT", "").strip() in ("1", "true", "yes", "on")


def scenario_pack_roots(xdr_root: Path, cfg: dict[str, Any]) -> list[Path]:
    roots: list[Path] = [xdr_root / "scenarios", xdr_root / "config" / "scenarios"]
    extra = cfg.get("scenario_pack_dirs") or cfg.get("scenario_packs_dirs")
    if isinstance(extra, list):
        for item in extra:
            s = str(item).strip()
            if s:
                roots.append(Path(s).expanduser())
    return roots


def _parse_structured_pack_file(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    suf = path.suffix.lower()
    if suf in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as e:  # pragma: no cover — optional dependency
            raise ValueError(
                f"PyYAML is required to read YAML packs: {path} ({e})"
            ) from e
        doc = yaml.safe_load(raw)
    else:
        doc = json.loads(raw)
    if not isinstance(doc, dict):
        raise ValueError("pack root must be a JSON object (map)")
    return doc


def _coerce_telemetry(raw: Any) -> Any:
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if raw is None:
        return []
    return str(raw)


def pack_doc_to_resolved(doc: dict[str, Any], path: Path, xdr_root: Path, cfg: dict[str, Any]) -> ResolvedScenario:
    sid = str(doc.get("scenario_id") or "").strip()
    if not sid or sid.startswith("_"):
        raise ValueError("scenario_id is empty or starts with '_'")
    cal = doc.get("caldera")
    if not isinstance(cal, dict):
        raise ValueError("caldera block is required (object)")
    adv_raw = cal.get("adversary_id")
    if adv_raw in (None, "", []):
        adv: str | None = None
    else:
        adv = str(adv_raw).strip() or None
    grp = str(cal.get("group") or cfg.get("default_group") or "red").strip() or "red"
    pln = str(cal.get("planner") or cfg.get("default_planner") or "atomic").strip() or "atomic"
    tv_raw = doc.get("target_vms")
    if not isinstance(tv_raw, list):
        raise ValueError("target_vms must be an array of strings")
    tvs = [str(x).strip() for x in tv_raw if str(x).strip()]
    disp = str(doc.get("display_name") or sid).strip() or sid
    desc = str(doc.get("description") or "").strip()
    safe = str(doc.get("safety_notes") or "").strip()
    clean = str(doc.get("cleanup_notes") or "").strip()
    tel = _coerce_telemetry(doc.get("expected_telemetry"))
    try:
        rel = path.resolve().relative_to(xdr_root.resolve())
        src = f"pack:{rel}"
    except ValueError:
        src = f"pack:{path}"
    return ResolvedScenario(
        scenario_id=sid,
        display_name=disp,
        description=desc,
        target_vms=tvs,
        adversary_id=adv,
        group=grp,
        planner=pln,
        expected_telemetry=tel,
        safety_notes=safe,
        cleanup_notes=clean,
        source=src,
        path=path.resolve(),
    )


def _legacy_scenario_to_resolved(name: str, spec: dict[str, Any], cfg: dict[str, Any]) -> ResolvedScenario:
    adv_raw = spec.get("adversary_id")
    if adv_raw in (None, "", []):
        adv = None
    else:
        adv = str(adv_raw).strip() or None
    return ResolvedScenario(
        scenario_id=name,
        display_name=name,
        description=str(spec.get("description") or "").strip(),
        target_vms=[],
        adversary_id=adv,
        group=str(cfg.get("default_group") or "red").strip() or "red",
        planner=str(cfg.get("default_planner") or "atomic").strip() or "atomic",
        expected_telemetry=[],
        safety_notes="(caldera-lab.json legacy entry only — no scenario pack file)",
        cleanup_notes="After `scenario stop`, snapshot revert if needed — docs/caldera-integration.md",
        source=f"config:caldera-lab.json::scenarios.{name}",
        path=None,
    )


def _apply_legacy_fallback(rs: ResolvedScenario, leg: dict[str, Any]) -> None:
    """Pack wins; empty adversary_id and similar fields are filled from caldera-lab.json for the same key."""
    if rs.adversary_id is None and leg.get("adversary_id") not in (None, "", []):
        rs.adversary_id = str(leg.get("adversary_id")).strip() or None
    if not rs.description.strip():
        d = str(leg.get("description") or "").strip()
        if d:
            rs.description = d


def build_scenario_registry(xdr_root: Path, cfg: dict[str, Any]) -> tuple[dict[str, ResolvedScenario], list[str]]:
    """Merge pack files (scenarios/, config/scenarios/) with caldera-lab.json::scenarios.

    Precedence: for the same scenario_id **the pack wins**; caldera-lab.json only fills empty fields (fallback).
    Legacy-only names (e.g. web-test) register from caldera entries alone when no pack exists.
    """
    warnings: list[str] = []
    xr = xdr_root.resolve()
    by_id: dict[str, ResolvedScenario] = {}
    seen_paths: set[str] = set()
    for root in scenario_pack_roots(xdr_root, cfg):
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_file():
                continue
            low = child.suffix.lower()
            if low not in (".json", ".yaml", ".yml"):
                continue
            if child.name.startswith(".") or child.name.startswith("_"):
                continue
            cpath = child.resolve()
            ps = str(cpath)
            if ps in seen_paths:
                continue
            seen_paths.add(ps)
            try:
                doc = _parse_structured_pack_file(cpath)
                rs = pack_doc_to_resolved(doc, cpath, xr, cfg)
            except (OSError, ValueError, json.JSONDecodeError) as e:
                warnings.append(f"invalid_scenario_pack file={cpath} error={e}")
                continue
            sid = rs.scenario_id
            if sid in by_id:
                warnings.append(f"duplicate_scenario_pack ignored scenario_id={sid!r} file={cpath}")
                continue
            by_id[sid] = rs
    scenarios_cfg = cfg.get("scenarios") if isinstance(cfg.get("scenarios"), dict) else {}
    for name, spec in scenarios_cfg.items():
        if name.startswith("_") or not isinstance(spec, dict):
            continue
        if name in by_id:
            _apply_legacy_fallback(by_id[name], spec)
        else:
            by_id[name] = _legacy_scenario_to_resolved(name, spec, cfg)
    return by_id, warnings


def _ellipsize(s: str, max_len: int) -> str:
    s = s.replace("\n", " ").replace("\r", "")
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def load_lab_vm_role_names(xdr_root: Path) -> tuple[set[str] | None, str | None]:
    """Return VM role keys from config/lab-vms.json (vms.*), or (None, error)."""
    p = xdr_root / "config" / "lab-vms.json"
    if not p.is_file():
        return None, f"lab_vms_missing:{p}"
    try:
        raw = p.read_text(encoding="utf-8")
        doc = json.loads(raw)
    except OSError as e:
        return None, f"lab_vms_read_error:{e}"
    except json.JSONDecodeError as e:
        return None, f"lab_vms_json_error:{p.name}:{e.msg} (line {e.lineno}, column {e.colno})"
    if not isinstance(doc, dict):
        return None, "lab_vms_root_not_object"
    vms = doc.get("vms")
    if not isinstance(vms, dict):
        return None, "lab_vms.vms_not_object"
    names: set[str] = set()
    for k, v in vms.items():
        if not isinstance(k, str) or not k.strip():
            continue
        if isinstance(v, dict) and str(v.get("name") or "").strip():
            names.add(str(v["name"]).strip())
        else:
            names.add(k.strip())
    return names, None


def _parse_structured_pack_file_with_errors(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Parse a scenario pack file; on failure return (None, human-readable error)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        return None, f"read_failed:{e}"
    suf = path.suffix.lower()
    if suf in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as e:
            return None, f"yaml_dependency_missing:{path.name}: PyYAML required ({e})"
        try:
            doc = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            return None, f"yaml_parse_error:{path.name}:{e}"
        except Exception as e:  # pragma: no cover
            return None, f"yaml_parse_error:{path.name}:{e}"
    else:
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError as e:
            return None, (
                f"json_parse_error:{path.name}:{e.msg} "
                f"(line {e.lineno}, column {e.colno})"
            )
    if not isinstance(doc, dict):
        return None, f"pack_root_not_object:{path.name}"
    return doc, None


def iter_scenario_pack_files(xdr_root: Path, cfg: dict[str, Any]) -> list[Path]:
    """Pack files only (same discovery rules as build_scenario_registry)."""
    xr = xdr_root.resolve()
    out: list[Path] = []
    seen: set[str] = set()
    for root in scenario_pack_roots(xdr_root, cfg):
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_file():
                continue
            low = child.suffix.lower()
            if low not in (".json", ".yaml", ".yml"):
                continue
            if child.name.startswith(".") or child.name.startswith("_"):
                continue
            cpath = child.resolve()
            ps = str(cpath)
            if ps in seen:
                continue
            seen.add(ps)
            out.append(cpath)
    return out


def _pack_issue(
    severity: str, code: str, message: str, field: str | None = None
) -> dict[str, Any]:
    row: dict[str, Any] = {"severity": severity, "code": code, "message": message}
    if field:
        row["field"] = field
    return row


def validate_scenario_pack_document(
    doc: dict[str, Any],
    *,
    lab_vm_names: set[str],
    duplicate_scenario_id: bool,
) -> list[dict[str, Any]]:
    """Validate one parsed pack dict. Assumes parse already succeeded."""
    issues: list[dict[str, Any]] = []
    if duplicate_scenario_id:
        issues.append(
            _pack_issue(
                "error",
                "duplicate_scenario_id",
                "More than one pack file declares the same scenario_id.",
                "scenario_id",
            )
        )

    sid = str(doc.get("scenario_id") or "").strip()
    if "scenario_id" not in doc:
        issues.append(_pack_issue("error", "missing_field", "scenario_id key is missing.", "scenario_id"))
    elif not sid or sid.startswith("_"):
        issues.append(
            _pack_issue(
                "error",
                "invalid_scenario_id",
                "scenario_id is empty or starts with '_'.",
                "scenario_id",
            )
        )

    for key in ("display_name", "description", "safety_notes", "cleanup_notes"):
        if key not in doc:
            issues.append(_pack_issue("error", "missing_field", f"{key} key is missing.", key))
        elif not isinstance(doc[key], str) or not str(doc[key]).strip():
            issues.append(
                _pack_issue(
                    "error",
                    "empty_or_invalid_field",
                    f"{key} must be a non-empty string.",
                    key,
                )
            )

    if "target_vms" not in doc:
        issues.append(_pack_issue("error", "missing_field", "target_vms key is missing.", "target_vms"))
    elif not isinstance(doc["target_vms"], list):
        issues.append(
            _pack_issue(
                "error",
                "invalid_type",
                "target_vms must be an array of strings.",
                "target_vms",
            )
        )
    else:
        tvs = [str(x).strip() for x in doc["target_vms"] if str(x).strip()]
        if not tvs:
            issues.append(
                _pack_issue(
                    "error",
                    "empty_target_vms",
                    "target_vms needs at least one VM role name.",
                    "target_vms",
                )
            )
        for vm in tvs:
            if vm not in lab_vm_names:
                issues.append(
                    _pack_issue(
                        "error",
                        "unknown_target_vm",
                        f"target_vms references {vm!r}, which is not defined in config/lab-vms.json::vms.",
                        "target_vms",
                    )
                )

    cal = doc.get("caldera")
    if "caldera" not in doc:
        issues.append(_pack_issue("error", "missing_field", "caldera key is missing.", "caldera"))
    elif not isinstance(cal, dict):
        issues.append(
            _pack_issue("error", "invalid_type", "caldera must be an object.", "caldera")
        )
    else:
        for sub in ("group", "planner"):
            if sub not in cal:
                issues.append(
                    _pack_issue(
                        "error",
                        "missing_field",
                        f"caldera.{sub} key is missing.",
                        f"caldera.{sub}",
                    )
                )
            elif not isinstance(cal[sub], str) or not str(cal[sub]).strip():
                issues.append(
                    _pack_issue(
                        "error",
                        "empty_or_invalid_field",
                        f"caldera.{sub} must be a non-empty string.",
                        f"caldera.{sub}",
                    )
                )
        adv_raw = cal.get("adversary_id") if "adversary_id" in cal else None
        if "adversary_id" not in cal:
            issues.append(
                _pack_issue(
                    "warning",
                    "adversary_id_unset",
                    "caldera.adversary_id is missing. Set a CALDERA adversary UUID before running.",
                    "caldera.adversary_id",
                )
            )
        elif adv_raw in (None, "", []):
            issues.append(
                _pack_issue(
                    "warning",
                    "adversary_id_null",
                    "caldera.adversary_id is null/empty. Non-dry scenario run may be refused unless merged from fallback.",
                    "caldera.adversary_id",
                )
            )

    if "expected_telemetry" not in doc:
        issues.append(
            _pack_issue(
                "error",
                "missing_field",
                "expected_telemetry key is missing.",
                "expected_telemetry",
            )
        )
    else:
        tel = doc["expected_telemetry"]
        ok_tel = False
        if isinstance(tel, str) and tel.strip():
            ok_tel = True
        elif isinstance(tel, list) and tel:
            if all(isinstance(x, str) and x.strip() for x in tel):
                ok_tel = True
            elif any(not isinstance(x, str) or not str(x).strip() for x in tel):
                issues.append(
                    _pack_issue(
                        "error",
                        "invalid_expected_telemetry",
                        "expected_telemetry list items must all be non-empty strings.",
                        "expected_telemetry",
                    )
                )
            else:
                ok_tel = False
        if not ok_tel and not any(
            i.get("field") == "expected_telemetry" and i["code"] == "invalid_expected_telemetry"
            for i in issues
        ):
            issues.append(
                _pack_issue(
                    "error",
                    "empty_or_invalid_field",
                    "expected_telemetry must be a non-empty string or "
                    "an array of non-empty strings.",
                    "expected_telemetry",
                )
            )

    return issues


def run_scenario_pack_validation(
    xdr_root: Path, cfg: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, int], str | None]:
    """Validate all scenario pack files. Returns (file_results, summary_counts, fatal_error).

    Each file result:
      path, scenario_id, issues[], status (ok|warning|error)
    """
    lab_names, lab_err = load_lab_vm_role_names(xdr_root)
    if lab_names is None:
        return [], {"pack_files": 0, "errors": 0, "warnings": 0, "clean": 0}, lab_err or "lab_vms_error"

    paths = iter_scenario_pack_files(xdr_root, cfg)
    parsed: list[tuple[Path, dict[str, Any] | None, str | None]] = []
    for cpath in paths:
        doc, perr = _parse_structured_pack_file_with_errors(cpath)
        parsed.append((cpath, doc, perr))

    sid_to_paths: dict[str, list[Path]] = {}
    for cpath, doc, perr in parsed:
        if perr or not isinstance(doc, dict):
            continue
        sid = str(doc.get("scenario_id") or "").strip()
        if sid and not sid.startswith("_"):
            sid_to_paths.setdefault(sid, []).append(cpath)
    dup_sids = {k for k, v in sid_to_paths.items() if len(v) > 1}

    results: list[dict[str, Any]] = []
    n_err = n_warn = n_ok = 0
    for cpath, doc, perr in parsed:
        try:
            rel = str(cpath.resolve().relative_to(xdr_root.resolve()))
        except ValueError:
            rel = str(cpath)
        issues: list[dict[str, Any]] = []
        sid_disp: str | None = None
        if perr:
            issues.append(_pack_issue("error", "parse_error", perr))
        elif isinstance(doc, dict):
            sid_disp = str(doc.get("scenario_id") or "").strip() or None
            sid_key = sid_disp or ""
            dup = bool(sid_key and sid_key in dup_sids)
            issues.extend(validate_scenario_pack_document(doc, lab_vm_names=lab_names, duplicate_scenario_id=dup))

        has_err = any(i["severity"] == "error" for i in issues)
        has_warn = any(i["severity"] == "warning" for i in issues)
        if has_err:
            status = "error"
            n_err += 1
        elif has_warn:
            status = "warning"
            n_warn += 1
        else:
            status = "ok"
            n_ok += 1

        results.append(
            {
                "path": rel,
                "absolute_path": str(cpath),
                "scenario_id": sid_disp,
                "status": status,
                "issues": issues,
            }
        )

    summary = {
        "pack_files": len(paths),
        "errors": n_err,
        "warnings": n_warn,
        "clean": n_ok,
    }
    return results, summary, None


def print_scenario_pack_validation_human(
    results: list[dict[str, Any]], summary: dict[str, int], fatal: str | None
) -> None:
    if fatal:
        print(f"[fatal] {fatal}", file=sys.stderr)
        print(
            "Could not read lab-vms.json; target_vms validation was skipped.",
            file=sys.stderr,
        )
        return
    print("Scenario pack validation (scenarios/, config/scenarios/, scenario_pack_dirs)")
    print(
        f"Summary: pack_files={summary['pack_files']}  "
        f"clean={summary['clean']}  "
        f"with_warnings={summary['warnings']}  "
        f"with_errors={summary['errors']}"
    )
    rows: list[tuple[str, str, str, str, str]] = []
    for fr in results:
        p = fr["path"]
        sid = fr.get("scenario_id") or "-"
        st = fr["status"]
        issues = fr["issues"]
        if not issues:
            rows.append((_ellipsize(p, 44), sid, st, "ok", "OK"))
        else:
            for iss in issues:
                rows.append(
                    (
                        _ellipsize(p, 44),
                        _ellipsize(sid, 18),
                        str(iss.get("severity", "")),
                        _ellipsize(str(iss.get("code", "")), 22),
                        _ellipsize(str(iss.get("message", "")), 56),
                    )
                )
    headers = ("pack_file", "scenario_id", "severity", "code", "message")
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    sep = " | "
    print(sep.join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print(sep.join("-" * widths[i] for i in range(len(headers))))
    for r in rows:
        print(sep.join(r[i].ljust(widths[i]) for i in range(len(r))))


def cmd_pack_validate(
    xdr_root: Path, cfg: dict[str, Any], *, json_out: bool
) -> int:
    results, summary, fatal = run_scenario_pack_validation(xdr_root, cfg)
    lab_path = str((xdr_root / "config" / "lab-vms.json").resolve())
    payload: dict[str, Any] = {
        "schema_version": 1,
        "ok": False,
        "lab_vms_json": lab_path,
        "fatal": fatal,
        "summary": summary,
        "results": results,
    }
    if fatal:
        payload["ok"] = False
        if json_out:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print_scenario_pack_validation_human(results, summary, fatal)
        return 2

    any_err = any(r["status"] == "error" for r in results)
    payload["ok"] = not any_err
    if json_out:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print_scenario_pack_validation_human(results, summary, None)
    return 1 if any_err else 0


def print_scenario_registry_table(reg: dict[str, ResolvedScenario]) -> None:
    rows: list[tuple[str, str, str, str, str, str, str]] = []
    for sid in sorted(reg.keys()):
        rs = reg[sid]
        adv = rs.adversary_id or "(null)"
        adv_d = _ellipsize(adv, 14) if adv != "(null)" else adv
        tgt = ",".join(rs.target_vms) if rs.target_vms else "(default: agent roles)"
        rows.append(
            (
                sid,
                _ellipsize(rs.display_name, 22),
                adv_d,
                _ellipsize(rs.group, 8),
                _ellipsize(rs.planner, 10),
                _ellipsize(rs.source, 28),
                _ellipsize(tgt, 36),
            )
        )
    headers = ("scenario_id", "display_name", "adversary_id", "group", "planner", "source", "target_vms")
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    sep = " | "
    head_line = sep.join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(head_line)
    print(sep.join("-" * widths[i] for i in range(len(headers))))
    for r in rows:
        print(sep.join(r[i].ljust(widths[i]) for i in range(len(r))))


def effective_scenario_dry(cli_dry: bool) -> bool:
    return dry_run() or cli_dry


def format_scenario_operation_name(scenario_name: str) -> str:
    """Stable CALDERA operation name pattern used by `scenario run` (timestamp suffix)."""
    return f"xdr-lab-{scenario_name}-{re.sub(r'[^0-9A-Za-z._-]+', '-', utc_now())}"


def _telemetry_snapshot_from_pack(rs: ResolvedScenario) -> dict[str, Any]:
    """Fields merged into last_history so `telemetry last` can work offline."""
    return {
        "scenario_id": rs.scenario_id,
        "display_name": rs.display_name,
        "expected_telemetry": rs.expected_telemetry,
    }


def compact_preflight_summary_for_record(pf: dict[str, Any]) -> dict[str, Any]:
    """Small JSON-safe snapshot of collect_scenario_run_preflight output for scenario.json / JSONL."""
    s = pf.get("summary") if isinstance(pf.get("summary"), dict) else {}
    warns = pf.get("warnings") if isinstance(pf.get("warnings"), list) else []
    blocks = pf.get("blocking") if isinstance(pf.get("blocking"), list) else []
    gates = (
        pf.get("operator_live_gate_failures")
        if isinstance(pf.get("operator_live_gate_failures"), list)
        else []
    )
    br = pf.get("bootstrap_report") if isinstance(pf.get("bootstrap_report"), dict) else {}
    mir = s.get("mirror") if isinstance(s.get("mirror"), dict) else {}
    return {
        "caldera_reachable": s.get("caldera_reachable"),
        "api_key_configured": s.get("api_key_configured"),
        "api_authenticated": s.get("api_authenticated"),
        "base_url": s.get("base_url"),
        "atomic_plugin_configured": s.get("atomic_plugin_configured"),
        "bootstrap_ok": bool(br.get("ok")) if br else None,
        "warning_codes": [str(w.get("code") or "") for w in warns if isinstance(w, dict)],
        "blocking_codes": [str(b.get("code") or "") for b in blocks if isinstance(b, dict)],
        "live_gate_codes": [str(g.get("code") or "") for g in gates if isinstance(g, dict)],
        "mirror_consistent": mir.get("consistent"),
        "mirror_json_present": mir.get("mirror_json_present"),
        "expected_telemetry_count": s.get("expected_telemetry_count"),
    }


def recommended_next_actions_after_live_submit(
    *,
    scenario_name: str,
    op_name: str,
    op_id: str | None,
    target_vms: list[str],
    snapshot_before: bool,
    snap_result: Any,
    snap_name: str | None,
) -> list[str]:
    """Operator-facing strings persisted on last_live_run (no fabricated CALDERA outcomes)."""
    out: list[str] = [
        f"In CALDERA UI → Operations, open {op_name!r} / id {op_id or '-'} and review timeline, abilities, and agent mapping.",
        "Refresh server_reported_state and scenario.json periodically via `lab scenario status` (or `--human`).",
        f"Manually correlate expected_telemetry via `lab scenario telemetry {scenario_name}` or after the run `lab scenario telemetry last`.",
        "End with `lab scenario stop` — snapshots are not auto-reverted.",
    ]
    if snapshot_before:
        sn = str(snap_name or "").strip()
        if scenario_snapshot_applied(snap_result) and sn:
            out.append(f"If needed, candidate snapshot revert: `aella_cli lab snapshot revert {sn}`")
        elif scenario_snapshot_applied(snap_result):
            out.append("Snapshot was recorded as applied but name is empty — confirm with `lab snapshot list`.")
    if target_vms:
        out.append(f"Target VM roles: {', '.join(target_vms)} — correlate mirror, host logs, and EDR/NDR consoles on the same timeline.")
    return out


def preserve_telemetry_review_status(existing: Any) -> str | Any:
    """After scenario stop: keep operator-complete markers; otherwise default pending."""
    s = str(existing or "not_set").strip().lower()
    if s in ("complete", "completed", "waived", "done", "reviewed", "skipped"):
        return existing
    return "pending_operator_review"


def build_last_live_run_record_on_submit(
    *,
    run_id: str,
    scenario_name: str,
    rs: ResolvedScenario,
    target_vms: list[str],
    started_at: str,
    submitted_at: str,
    op_name: str,
    op_id: str | None,
    server_reported_state: str | None,
    snapshot_before: bool,
    snap_name: str | None,
    snap_result: Any,
    pf: dict[str, Any],
) -> dict[str, Any]:
    s = pf.get("summary") if isinstance(pf.get("summary"), dict) else {}
    matrix = s.get("agent_matrix") if isinstance(s.get("agent_matrix"), dict) else {}
    wall_submit = operation_duration_seconds_between(started_at, submitted_at)
    rec = recommended_next_actions_after_live_submit(
        scenario_name=scenario_name,
        op_name=op_name,
        op_id=op_id,
        target_vms=target_vms,
        snapshot_before=snapshot_before,
        snap_result=snap_result,
        snap_name=snap_name,
    )
    return {
        "schema_version": 1,
        "run_id": run_id,
        "scenario_name": scenario_name,
        "scenario_id": rs.scenario_id,
        "display_name": rs.display_name,
        "target_vms": list(target_vms),
        "started_at": started_at,
        "submitted_at": submitted_at,
        "completed_at": None,
        "duration_seconds_submit": round(wall_submit, 3) if wall_submit is not None else None,
        "duration_seconds_session": None,
        "caldera_operation": {
            "operation_name": op_name,
            "operation_id": op_id,
            "server_reported_state": server_reported_state,
        },
        "snapshot_before": snapshot_before,
        "snapshot_before_name": snap_name if snapshot_before else None,
        "snapshot_before_result": snap_result,
        "preflight_summary": compact_preflight_summary_for_record(pf),
        "agent_matrix_snapshot": dict(matrix),
        "expected_telemetry_snapshot": _expected_telemetry_as_str_list(rs.expected_telemetry),
        "recommended_next_actions": rec,
        "stop_outcome": None,
    }


def merge_last_live_run_on_stop(
    prev: Any,
    *,
    run_id: str,
    stopped_at: str,
    post_state: str | None,
    stop_http_ok: bool,
) -> dict[str, Any] | None:
    if not isinstance(prev, dict):
        return None
    if str(prev.get("run_id") or "").strip() != str(run_id).strip():
        return None
    out = dict(prev)
    out["completed_at"] = stopped_at
    out["stop_outcome"] = {
        "http_finish_ok": stop_http_ok,
        "server_reported_state_after_stop": post_state,
    }
    started = str(out.get("started_at") or "").strip()
    dur = operation_duration_seconds_between(started, stopped_at)
    if dur is not None:
        out["duration_seconds_session"] = round(dur, 3)
    return out


def failure_candidate_lines_for_scenario(
    scenario: dict[str, Any], caldera: dict[str, Any]
) -> list[str]:
    """Heuristic triage bullets — not automated verdicts."""
    lines: list[str] = []
    st = str(scenario.get("status") or "").strip().lower()
    err = str(scenario.get("last_error") or "").strip()
    err_l = err.lower()
    if err:
        lines.append(f"last_error: {err}")
    if st in ("failed", "blocked"):
        lines.append("Re-check CALDERA REST, API key, base_url, and firewall (`bootstrap validate`).")
    if "http_401" in err_l or "http_403" in err_l:
        lines.append("HTTP 401/403 from CALDERA — verify API key (KEY header) matches the server; see bootstrap validate api_key check.")
    if "url_error" in err_l or "connection refused" in err_l:
        lines.append("Transport error to CALDERA — confirm process listening on base_url and no firewall drop (operator host).")
    if "adversary" in err_l and ("missing" in err_l or "uuid" in err_l or "mismatch" in err_l):
        lines.append(
            "Adversary UUID missing or mismatched — copy the adversary id from CALDERA UI into the scenario pack "
            "or caldera-lab.json::scenarios fallback; re-run `scenario pack validate`."
        )
    if "snapshot" in err_l or err == "snapshot_before_failed":
        lines.append("Check libvirt snapshots, disk space, vm-manager script, and target VM power state.")
    if st == "blocked" and err.startswith("preflight_"):
        lines.append("Fix mirror/snapshot/reachability per preflight blocking codes, then re-check with `--dry-run`.")
    if not bool(caldera.get("http_reachable")):
        lines.append("caldera.json http_reachable=false — check server process, port, and KEY header.")
    agents = scenario.get("agents") if isinstance(scenario.get("agents"), dict) else {}
    missing = [k for k, v in agents.items() if not v and str(k).strip()]
    if missing and bool(caldera.get("http_reachable")):
        lines.append(
            "Agent matrix shows disconnected roles: "
            + ", ".join(missing)
            + " — deploy Sandcat (`scenario agent deploy`) and match agent_vm_map host_substrings to CALDERA paws."
        )
    cal = scenario.get("caldera") if isinstance(scenario.get("caldera"), dict) else {}
    if st == "running" and not str(cal.get("operation_id") or "").strip():
        lines.append("If status is running but operation_id is empty, suspect PUT parse issues or refresh_state races.")
    if not lines:
        lines.append("No specific automated root cause — compare JSONL timeline and UI logs first.")
    return lines


def print_post_run_operator_review_human(
    scenario: dict[str, Any],
    caldera: dict[str, Any],
    stated_p: Path,
    cfg: dict[str, Any],
) -> None:
    """Extra `--human` block after a live submit / terminal run (no telemetry auto-verdict)."""
    st_main = str(scenario.get("status") or "").strip().lower()
    llr = scenario.get("last_live_run") if isinstance(scenario.get("last_live_run"), dict) else None
    hist = scenario.get("last_history") if isinstance(scenario.get("last_history"), dict) else None
    if not llr and not hist:
        return
    print("")
    print("=== Post-run review (live run record / observation — no auto verdict) ===")
    if llr:
        cop = llr.get("caldera_operation") if isinstance(llr.get("caldera_operation"), dict) else {}
        print("[last_live_run summary — scenario.json]")
        print(f"  run_id: {llr.get('run_id') or '-'}")
        print(
            f"  submitted_at: {llr.get('submitted_at') or '-'}  completed_at: "
            f"{llr.get('completed_at') or '(not recorded yet; refresh after stop if still running)'}"
        )
        print(
            f"  CALDERA operation: id={cop.get('operation_id') or '-'}  name={cop.get('operation_name') or '-'}  "
            f"state={cop.get('server_reported_state') or '-'}"
        )
        if llr.get("duration_seconds_session") is not None:
            print(f"  session wall-clock seconds (started→completed): {llr.get('duration_seconds_session')}")
        pfs = llr.get("preflight_summary")
        if isinstance(pfs, dict) and pfs:
            print(
                f"  preflight summary (recorded): blocking_codes={pfs.get('blocking_codes')} "
                f"warning_codes={pfs.get('warning_codes')}"
            )
        tvs = llr.get("target_vms")
        if isinstance(tvs, list) and tvs:
            print(f"  target_vms: {', '.join(str(x) for x in tvs)}")
        snapr = llr.get("snapshot_before_result")
        print(
            f"  snapshot_before: {llr.get('snapshot_before')}  result={snapr!s}  name={llr.get('snapshot_before_name') or '-'}"
        )
        am = llr.get("agent_matrix_snapshot")
        if isinstance(am, dict) and am:
            print(
                f"  agent_matrix_snapshot: {', '.join(f'{k}={'connected' if v else 'not connected'}' for k, v in am.items())}"
            )
        etn = llr.get("expected_telemetry_snapshot")
        if isinstance(etn, list) and etn:
            print(f"  expected_telemetry_snapshot: {len(etn)} items (first 8)")
            for line in etn[:8]:
                print(f"    - {line}")
            if len(etn) > 8:
                print(f"    … plus {len(etn) - 8} more")
        ra = llr.get("recommended_next_actions")
        if isinstance(ra, list) and ra:
            print("  recommended_next_actions (as recorded):")
            for a in ra[:12]:
                if isinstance(a, str) and a.strip():
                    print(f"    - {a.strip()}")
        so = llr.get("stop_outcome")
        if isinstance(so, dict):
            print(
                f"  stop_outcome: http_finish_ok={so.get('http_finish_ok')}  "
                f"server_reported_state_after_stop={so.get('server_reported_state_after_stop')!r}"
            )
    if hist:
        hs = str(hist.get("status") or "").strip()
        print("")
        print(f"[last_history.status] {hs} (last completed/blocked overlay)")
        hcal = hist.get("caldera") if isinstance(hist.get("caldera"), dict) else {}
        if hcal:
            print(
                f"  operation_id={hcal.get('operation_id') or '-'}  "
                f"server_reported_state={hcal.get('server_reported_state') or '-'}"
            )
    if st_main in ("failed", "blocked") or scenario.get("last_error"):
        print("")
        print("[Failure / anomaly hints — reference only]")
        for ln in failure_candidate_lines_for_scenario(scenario, caldera):
            print(f"  - {ln}")
    print("")
    print("[Check in CALDERA UI]")
    print("  - Operations: select the operation → timeline / facts / per-agent ability results")
    print("  - Adversary / planner / autonomous settings match expectations (read-only check)")
    print("  - Agents: paw/host/group map to target_vms roles")
    print("")
    print("[Sensor / OVS mirror]")
    mir_doc = load_mirror_doc(stated_p)
    if (stated_p / "mirror.json").is_file():
        print(
            f"  mirror.json: consistent={mir_doc.get('consistent')}  mirror_exists={mir_doc.get('mirror_exists')}  "
            f"sensor_vm={mir_doc.get('sensor_vm')!r}"
        )
    else:
        print("  mirror.json missing — run `lab mirror verify` to refresh consistency")
    print("  - Sensor PCAP/logs (Zeek/Suricata, etc.): correlate run window with IP/port (no auto verdict)")
    print("")
    print("[EDR / NDR / XDR consoles]")
    tvs2 = [str(x) for x in (scenario.get("target_vms") or []) if str(x).strip()]
    if not tvs2 and hist:
        tvs2 = [str(x) for x in (hist.get("target_vms") or []) if str(x).strip()]
    rel = build_related_sensors_log_sources(tvs2 or agent_vm_roles(cfg))
    for vm, msgs in rel.items():
        print(f"  - {vm}:")
        for m in msgs:
            print(f"      {m}")
    print("")
    print("[Snapshot revert guidance]")
    snapr = scenario.get("snapshot_before_result")
    snapnm = str(scenario.get("snapshot_before_name") or "").strip()
    if scenario_snapshot_applied(snapr) and snapnm:
        print(f"  pre-run snapshot applied — if needed: `aella_cli lab snapshot revert {snapnm}`")
    elif scenario_snapshot_applied(snapr):
        print("  snapshot applied but name missing — `lab snapshot list` / snapshots.json")
    else:
        print("  pre-run snapshot not applied or failed — revert is optional (operator decision)")
    print("")
    print("[Cleanup guidance]")
    cr = scenario.get("cleanup_recommended")
    print(
        f"  cleanup_recommended={cr!s} — review guest Sandcat/ability leftovers, orphaned CALDERA operations, "
        "and whether `lab scenario agent remove` is appropriate."
    )


def print_scenario_stop_human_summary(
    *,
    stop_ok: bool,
    stopped_at: str,
    op_id: Any,
    op_name: Any,
    duration_sec: float | None,
    telemetry_review_status: Any,
    cleanup_hints: list[str],
    snap_applied: bool,
    snap_nm: str,
) -> None:
    """stderr — does not interfere with stdout JSON from `scenario stop`."""
    print("", file=sys.stderr)
    print("=== scenario stop summary (stderr) ===", file=sys.stderr)
    print(f"  stop_http_finish: {'ok' if stop_ok else 'failed'}", file=sys.stderr)
    print(f"  stopped_at: {stopped_at}", file=sys.stderr)
    print(f"  caldera_operation_id: {op_id or '-'}  name: {op_name or '-'}", file=sys.stderr)
    if duration_sec is not None:
        print(f"  operation_wall_duration_sec (start→stop): {round(float(duration_sec), 3)}", file=sys.stderr)
    else:
        print("  operation_wall_duration_sec: (started_at unknown)", file=sys.stderr)
    print(f"  telemetry_review_status (preserved/updated): {telemetry_review_status!r}", file=sys.stderr)
    if cleanup_hints:
        print("  remaining_cleanup_hints:", file=sys.stderr)
        for h in cleanup_hints:
            print(f"    - {h}", file=sys.stderr)
    if snap_applied and snap_nm:
        print(
            f"  snapshot: applied — revert is manual (`aella_cli lab snapshot revert {snap_nm}`)",
            file=sys.stderr,
        )
    elif snap_applied:
        print("  snapshot: applied (name not recorded) — `lab snapshot list`", file=sys.stderr)


def _expected_telemetry_as_str_list(tel: Any) -> list[str]:
    coerced = _coerce_telemetry(tel)
    if isinstance(coerced, list):
        return [str(x).strip() for x in coerced if str(x).strip()]
    s = str(coerced).strip()
    return [s] if s else []


def build_related_sensors_log_sources(target_vms: list[str]) -> dict[str, list[str]]:
    """Static lab-role hints — operator-facing, not auto-verified."""
    hints: dict[str, list[str]] = {
        "sensor-vm": [
            "Network sensor path (Zeek/Suricata, per deployment) and OVS/SPAN mirror view (§9 mirror)",
            "Linux host logs: journal/syslog and Sandcat-related agent logs",
        ],
        "victim-linux": [
            "Auth and system logs: journalctl, /var/log/auth.log, etc.",
            "Service logs (web/DB, etc.) and auditd when enabled",
        ],
        "windows-victim": [
            "Windows event logs (Security, Sysmon, PowerShell/Operational, etc.)",
            "CALDERA Sandcat and remote-execution artifacts (per policy/agent config)",
        ],
    }
    out: dict[str, list[str]] = {}
    for vm in target_vms:
        key = str(vm).strip()
        if key in hints:
            out[key] = list(hints[key])
        else:
            out[key] = [
                f"No built-in hint map for role {key!r}. "
                "Confirm SIEM/agent collection paths for that VM in your runbook.",
            ]
    return out


def build_operator_telemetry_checklist(
    *,
    scenario_id: str,
    display_name: str,
    target_vms: list[str],
    expected: list[str],
    anchor: str,
    last_run: dict[str, Any] | None,
) -> list[str]:
    """Human checklist lines — no pass/fail verdict."""
    lines: list[str] = [
        f"Scenario «{display_name}» ({scenario_id}): manually verify the items below before/after the run (no auto verdict).",
        "In CALDERA UI, review operation/ability timelines and target agents.",
        f"Target VMs: {', '.join(target_vms) if target_vms else '(not specified)'} — align host clocks (UTC vs local) before correlating logs.",
    ]
    if anchor == "last_history" and last_run:
        lines.append(
            f"This view is anchored on scenario.json::last_history "
            f"(status={last_run.get('status')!r}, dry_run={last_run.get('dry_run')}, "
            f"run_id={last_run.get('run_id') or '-'})."
        )
    if expected:
        lines.append("For each expected_telemetry line, look for matching or similar events in your observability stack:")
        for i, item in enumerate(expected, start=1):
            lines.append(f"  [{i}] {item}")
    else:
        lines.append(
            "expected_telemetry is empty. "
            "Populate the pack string list or inspect fields with `scenario pack validate`."
        )
    lines.append("If you used snapshots/revert, note whether observations are pre- or post-snapshot.")
    lines.append("Absence of obvious anomalies can still be normal — also review collection gaps and filters.")
    return lines


def build_telemetry_review_doc(
    *,
    scenario_id: str,
    display_name: str,
    target_vms: list[str],
    expected_telemetry: Any,
    anchor: str,
    last_run: dict[str, Any] | None,
) -> dict[str, Any]:
    exp = _expected_telemetry_as_str_list(expected_telemetry)
    related = build_related_sensors_log_sources(target_vms)
    checklist = build_operator_telemetry_checklist(
        scenario_id=scenario_id,
        display_name=display_name,
        target_vms=target_vms,
        expected=exp,
        anchor=anchor,
        last_run=last_run,
    )
    last_ctx: dict[str, Any] | None = None
    if isinstance(last_run, dict):
        for k in (
            "run_id",
            "scenario_name",
            "status",
            "dry_run",
            "started_at",
            "stopped_at",
            "target_vms",
            "snapshot_before",
            "snapshot_before_result",
            "snapshot_before_name",
        ):
            if k in last_run:
                last_ctx = last_ctx or {}
                last_ctx[k] = last_run.get(k)
        hcal = last_run.get("caldera")
        if isinstance(hcal, dict):
            last_ctx = last_ctx or {}
            last_ctx["caldera"] = {
                "operation_id": hcal.get("operation_id"),
                "operation_name": hcal.get("operation_name"),
                "adversary_id": hcal.get("adversary_id"),
            }
    return {
        "scenario_id": scenario_id,
        "display_name": display_name,
        "target_vms": target_vms,
        "expected_telemetry": exp,
        "related_sensors_log_sources": related,
        "operator_checklist": checklist,
        "anchor": anchor,
        "last_run_context": last_ctx,
    }


def print_telemetry_review_human(doc: dict[str, Any]) -> None:
    print("=== Scenario telemetry review (operator checklist — no auto verdict) ===")
    print(f"scenario_id: {doc.get('scenario_id')}")
    print(f"display_name: {doc.get('display_name')}")
    print(f"anchor: {doc.get('anchor')}")
    tvs = doc.get("target_vms") or []
    print(f"target_vms: {', '.join(str(x) for x in tvs) if tvs else '-'}")
    print("")
    print("[expected_telemetry]")
    exp = doc.get("expected_telemetry") or []
    if isinstance(exp, list) and exp:
        for line in exp:
            print(f"  - {line}")
    else:
        print("  (none)")
    print("")
    print("[Related sensors / log sources (per-role hints)]")
    rel = doc.get("related_sensors_log_sources") or {}
    if isinstance(rel, dict) and rel:
        for vm, rows in rel.items():
            print(f"  {vm}:")
            if isinstance(rows, list):
                for r in rows:
                    print(f"    - {r}")
            else:
                print(f"    - {rows}")
    else:
        print("  (none)")
    lrc = doc.get("last_run_context")
    if isinstance(lrc, dict) and lrc:
        print("")
        print("[last_run_context — scenario.json::last_history summary]")
        for k, v in lrc.items():
            if k == "caldera" and isinstance(v, dict):
                print(f"  {k}: {json.dumps(v, ensure_ascii=False)}")
            else:
                print(f"  {k}: {v}")
    print("")
    print("[Operator checklist]")
    cl = doc.get("operator_checklist") or []
    if isinstance(cl, list):
        for line in cl:
            print(line)
    else:
        print(str(cl))


def _resolve_expected_telemetry_for_status(
    scenario: dict[str, Any], xdr_root: Path, cfg: dict[str, Any]
) -> tuple[list[str], str]:
    """Return (items, provenance) for status --human."""
    raw = scenario.get("expected_telemetry")
    if raw not in (None, "", []):
        return _expected_telemetry_as_str_list(raw), "scenario.json top-level"
    hist = scenario.get("last_history") if isinstance(scenario.get("last_history"), dict) else None
    if hist and hist.get("expected_telemetry") not in (None, "", []):
        return _expected_telemetry_as_str_list(hist.get("expected_telemetry")), "last_history snapshot"
    name = str(scenario.get("scenario_name") or scenario.get("current_operation") or "").strip()
    if not name and hist:
        name = str(hist.get("scenario_name") or "").strip()
    if name:
        reg, _ = build_scenario_registry(xdr_root, cfg)
        rs = reg.get(name)
        if rs:
            return _expected_telemetry_as_str_list(rs.expected_telemetry), f"registered scenario {name!r} pack/merge"
    return [], "(nothing to display)"


def print_dry_run_telemetry_summary(rs: ResolvedScenario, target_vms: list[str]) -> None:
    """Extra stdout block after JSON blocks in `scenario run --dry-run`."""
    exp = _expected_telemetry_as_str_list(rs.expected_telemetry)
    doc = build_telemetry_review_doc(
        scenario_id=rs.scenario_id,
        display_name=rs.display_name,
        target_vms=target_vms,
        expected_telemetry=exp,
        anchor="dry_run",
        last_run=None,
    )
    print("")
    print("=== DRY-RUN: expected telemetry summary (operator review) ===")
    print(f"scenario_id={rs.scenario_id}  display_name={rs.display_name}")
    print(f"target_vms: {', '.join(target_vms) if target_vms else '-'}")
    print("expected_telemetry:")
    if exp:
        for line in exp:
            print(f"  - {line}")
    else:
        print("  (empty in pack)")
    print("")
    print("[Related sensors / log sources (per-role hints)]")
    for vm, rows in (doc.get("related_sensors_log_sources") or {}).items():
        print(f"  {vm}:")
        for r in rows:
            print(f"    - {r}")
    print("")
    print(
        "Full checklist: `lab scenario telemetry "
        + rs.scenario_id
        + "` or after the last run `lab scenario telemetry last`."
    )


def load_mirror_doc(stated: Path) -> dict[str, Any]:
    doc = load_json(stated / "mirror.json", {})
    return doc if isinstance(doc, dict) else {}


def load_snapshots_catalog_doc(stated: Path) -> dict[str, Any]:
    doc = load_json(stated / "snapshots.json", {})
    return doc if isinstance(doc, dict) else {}


def collect_scenario_run_preflight(
    xdr_root: Path,
    stated: Path,
    cfg: dict[str, Any],
    *,
    scenario_name: str,
    run_id: str,
    rs: ResolvedScenario,
    target_vms: list[str],
    snapshot_before: bool,
    is_dry: bool,
    log_path: Path | None,
) -> dict[str, Any]:
    """Read-only preflight facts for `scenario run` (no CALDERA mutations)."""
    base_url = str(cfg.get("base_url") or "http://127.0.0.1:8888").strip()
    api_key = resolve_api_key(cfg, xdr_root=xdr_root)
    api_key_ok = bool(api_key.strip())
    bootstrap_report = run_bootstrap_validation(xdr_root, cfg, log_path)
    by_id = {
        str(c.get("id") or ""): c
        for c in (bootstrap_report.get("checks") or [])
        if isinstance(c, dict)
    }
    caldera_ok = bool((by_id.get("caldera_base_url") or {}).get("ok"))
    api_auth_ok = bool((by_id.get("caldera_api_authenticated") or {}).get("ok"))
    plugins_list = cfg.get("plugins")
    plugins_norm = (
        [str(p).strip().lower() for p in plugins_list if str(p).strip()]
        if isinstance(plugins_list, list)
        else []
    )
    atomic_in_plugins = "atomic" in plugins_norm

    agents_list: list[dict[str, Any]] = []
    matrix: dict[str, bool] = {vm: False for vm in agent_vm_roles(cfg)}
    if caldera_ok and api_key_ok:
        client = CalderaClient(base_url, api_key)
        agents_list = fetch_agents(client, log_path)
        matrix = build_agent_matrix(cfg, agents_list)

    caldera_path = stated / "caldera.json"
    caldera_disk = load_json(caldera_path, {})
    art_last = (
        caldera_disk.get("atomic_red_team_validate_last")
        if isinstance(caldera_disk, dict)
        else None
    )
    art_ok: bool | None = None
    art_utc = ""
    art_summary = ""
    if isinstance(art_last, dict):
        art_ok = bool(art_last.get("ok")) if "ok" in art_last else None
        art_utc = str(art_last.get("utc") or "").strip()
        art_summary = str(art_last.get("summary") or "").strip()

    lab = load_lab_vms_json(xdr_root)
    nat_doc = load_nat_state_doc(stated)
    nat_global_ok, nat_global_notes = nat_reverse_happy(nat_doc)

    vm_reach: list[dict[str, Any]] = []
    for vm in target_vms:
        vm = str(vm).strip()
        if not vm:
            continue
        running, lst = vm_libvirt_running(vm)
        entry = lab_vm_entry(lab, vm)
        vtype = str(entry.get("type") or "")
        reach_detail = ""
        reach_ok = running
        if running:
            if vtype == "windows" or vm == "windows-victim":
                inv = probe_windows_access(vm, lab, cfg)
                reach_ok = bool(inv.get("ssh_ok") or inv.get("winrm_tcp") or inv.get("rdp_tcp"))
                reach_detail = (
                    f"libvirt=running transport={inv.get('picked')} "
                    f"ssh={inv.get('ssh_ok')} winrm_tcp={inv.get('winrm_tcp')} rdp_tcp={inv.get('rdp_tcp')}"
                )
            else:
                ssh_ok, ssh_detail = probe_ssh_linux_vm(vm, lab, cfg)
                reach_ok = ssh_ok
                reach_detail = ssh_detail
        vm_reach.append(
            {
                "vm": vm,
                "libvirt_running": running,
                "libvirt_state": lst,
                "reachable": reach_ok,
                "detail": reach_detail or (f"libvirt not running ({lst})" if not running else ""),
            }
        )
        nat_vm_ok, nat_vm_msgs = required_nat_for_vm(vm, lab, nat_doc)
        vm_reach[-1]["nat_vm_ok"] = nat_vm_ok
        vm_reach[-1]["nat_vm_messages"] = nat_vm_msgs

    mirror_doc = load_mirror_doc(stated)
    mirror_path = stated / "mirror.json"
    mirror_file = mirror_path.is_file()
    mirror_consistent = bool(mirror_doc.get("consistent")) if mirror_file else False

    snap_catalog = load_snapshots_catalog_doc(stated)
    per_vm_cat = snap_catalog.get("per_vm") if isinstance(snap_catalog.get("per_vm"), dict) else {}
    snap_rows: list[dict[str, Any]] = []
    for vm in target_vms:
        vm = str(vm).strip()
        if not vm:
            continue
        row = per_vm_cat.get(vm) if isinstance(per_vm_cat.get(vm), dict) else {}
        snap_rows.append(
            {
                "vm": vm,
                "catalog_domain_defined": bool(row.get("domain_defined")),
                "snapshot_count": int(row.get("snapshot_count") or 0),
            }
        )

    vm_mgr = xdr_root / "scripts" / "xdr-lab-vm-manager.sh"
    vm_mgr_ok = vm_mgr.is_file()

    exp_tel = _expected_telemetry_as_str_list(rs.expected_telemetry)

    warnings: list[dict[str, str]] = []
    blocking: list[dict[str, str]] = []
    operator_live_gate_failures: list[dict[str, str]] = []

    def add_warn(code: str, message: str) -> None:
        warnings.append({"code": code, "message": message})

    def add_block(code: str, message: str) -> None:
        blocking.append({"code": code, "message": message})

    def add_live_gate(code: str, message: str) -> None:
        """Conditions that stop a non-dry run; surfaced on dry-run as notices."""
        operator_live_gate_failures.append({"code": code, "message": message})
        if not is_dry:
            blocking.append({"code": code, "message": message})

    if not api_key_ok:
        add_live_gate("api_key_missing", "CALDERA API key is empty.")
    if not caldera_ok:
        add_live_gate("caldera_unreachable", f"CALDERA HTTP probe failed (base_url={base_url}).")
    if caldera_ok and api_key_ok and not api_auth_ok:
        add_live_gate(
            "caldera_api_not_authenticated",
            "GET /api/agents did not return 200 JSON with KEY header "
            f"(base_url={base_url}) — run: sudo bootstrap/ensure-caldera-api-key.sh; "
            "unset stale XDR_CALDERA_API_KEY",
        )
    if snapshot_before and not vm_mgr_ok:
        add_block(
            "snapshot_vm_manager_missing",
            f"vm-manager script required for snapshot-before is missing: {vm_mgr}",
        )

    gate = frozenset(
        {
            "caldera_base_url",
            "api_key",
            "atomic_plugin",
            "atomic_red_team_paths",
            "atomic_bootstrap_scripts",
        }
    )
    for c in bootstrap_report.get("checks") or []:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "")
        if cid not in gate or cid in ("caldera_base_url", "api_key"):
            continue
        if not c.get("ok"):
            add_warn(f"bootstrap:{cid}", str(c.get("label") or cid) + ": " + str(c.get("detail") or ""))

    if not plugins_norm:
        add_warn("plugins_empty", "caldera-lab.json plugins list is empty.")

    roles = agent_vm_roles(cfg)
    for vm in roles:
        if not matrix.get(vm):
            add_warn(f"agent_missing:{vm}", f"CALDERA has not yet seen Sandcat for role {vm!r}.")

    for vm in target_vms:
        vm = str(vm).strip()
        if vm and not matrix.get(vm):
            add_live_gate(
                f"target_agent_missing:{vm}",
                f"Target VM {vm!r} is in scenario targets but missing from the CALDERA agent matrix.",
            )

    if art_last is None or not isinstance(art_last, dict):
        if atomic_in_plugins:
            add_live_gate(
                "atomic_validate_never",
                "No `scenario atomic validate` record (caldera.json::atomic_red_team_validate_last).",
            )
        else:
            add_warn(
                "atomic_validate_never",
                "No `scenario atomic validate` record (caldera.json::atomic_red_team_validate_last).",
            )
    elif art_ok is False:
        if atomic_in_plugins:
            add_live_gate(
                "atomic_validate_failed",
                f"Last atomic validate recorded as failed (utc={art_utc or '?'}): {art_summary or 'no summary'}",
            )
        else:
            add_warn(
                "atomic_validate_failed",
                f"Last atomic validate recorded as failed (utc={art_utc or '?'}): {art_summary or 'no summary'}",
            )

    if not nat_global_ok:
        for n in nat_global_notes:
            add_live_gate("nat_global", n)

    for row in vm_reach:
        if not row.get("libvirt_running"):
            add_live_gate(
                f"vm_down:{row.get('vm')}",
                f"{row.get('vm')}: not libvirt running ({row.get('libvirt_state')}).",
            )
        elif not row.get("reachable"):
            add_live_gate(
                f"vm_unreachable:{row.get('vm')}",
                f"{row.get('vm')}: SSH/RDP/WinRM reachability failed — {row.get('detail')}",
            )
        for m in row.get("nat_vm_messages") or []:
            add_live_gate(f"nat_vm:{row.get('vm')}", str(m))

    if not mirror_file:
        add_live_gate(
            "mirror_json_missing",
            "runtime/state/mirror.json missing — run `xdr-lab-vm-manager.sh mirror status` / refresh first.",
        )
    elif not mirror_consistent:
        add_live_gate(
            "mirror_inconsistent",
            "mirror.json consistent=false — OVS mirror may not match intent (`lab mirror verify`).",
        )

    if not isinstance(snap_catalog, dict) or not snap_catalog:
        add_warn(
            "snapshots_catalog_missing",
            "runtime/state/snapshots.json missing/empty — snapshot catalog may not be recorded yet.",
        )

    if not exp_tel:
        add_warn(
            "expected_telemetry_empty",
            "Scenario pack expected_telemetry is empty (no manual review anchors).",
        )

    summary = {
        "scenario_name": scenario_name,
        "run_id": run_id,
        "base_url": base_url,
        "caldera_reachable": caldera_ok,
        "api_key_configured": api_key_ok,
        "api_authenticated": api_auth_ok,
        "plugins": plugins_norm,
        "atomic_plugin_configured": atomic_in_plugins,
        "agent_matrix": matrix,
        "atomic_red_team_validate_last": {
            "present": isinstance(art_last, dict),
            "ok": art_ok,
            "utc": art_utc or None,
        },
        "target_vm_reachability": vm_reach,
        "mirror": {
            "mirror_json_present": mirror_file,
            "consistent": mirror_consistent if mirror_file else None,
            "sensor_vm": mirror_doc.get("sensor_vm"),
            "mirror_exists": mirror_doc.get("mirror_exists"),
        },
        "snapshots_catalog": {
            "path": str(stated / "snapshots.json"),
            "per_target": snap_rows,
        },
        "snapshot_vm_manager_present": vm_mgr_ok,
        "nat_reference": {
            "nat_json_present": bool(nat_doc),
            "global_ok": nat_global_ok,
        },
        "expected_telemetry_count": len(exp_tel),
    }
    return {
        "summary": summary,
        "bootstrap_report": bootstrap_report,
        "warnings": warnings,
        "blocking": blocking,
        "operator_live_gate_failures": operator_live_gate_failures,
    }


def log_scenario_preflight_jsonl(
    log_path: Path | None,
    *,
    event: str,
    scenario_name: str,
    run_id: str,
    dry_run: bool,
    snapshot_before: bool,
    **extra: Any,
) -> None:
    if not log_path:
        return
    log_jsonl(
        log_path,
        event,
        scenario=scenario_name,
        run_id=run_id,
        dry_run=dry_run,
        snapshot_before=snapshot_before,
        **extra,
    )


def print_scenario_run_preflight_stdout(
    pf: dict[str, Any],
    *,
    operation_name: str,
    adversary_id: Any,
    group: str,
    planner: str,
    target_vms: list[str],
    snapshot_before: bool,
    snapshot_name: str | None,
    rs: ResolvedScenario,
    is_dry: bool,
) -> None:
    """Human-readable preflight + execution plan (stdout; dry-run and live)."""
    s = pf.get("summary") if isinstance(pf.get("summary"), dict) else {}
    print("")
    print("=== scenario run — preflight (pre-run checks) ===")
    print(
        f"CALDERA reachable: {'yes' if s.get('caldera_reachable') else 'no'}  "
        f"API key: {'present' if s.get('api_key_configured') else 'missing'}  "
        f"GET /api/agents: {'200/authenticated' if s.get('api_authenticated') else 'not authenticated'}  "
        f"base_url: {s.get('base_url', '-')}"
    )
    plg = s.get("plugins") or []
    print(f"plugins (config): {', '.join(str(x) for x in plg) if plg else '(empty)'}")
    print(f"atomic plugin (by name): {'yes' if s.get('atomic_plugin_configured') else 'no'}")
    art = s.get("atomic_red_team_validate_last") if isinstance(s.get("atomic_red_team_validate_last"), dict) else {}
    if art.get("present"):
        oks = art.get("ok")
        st = "pass" if oks is True else ("fail" if oks is False else "unknown")
        print(f"Last ART validate record: {st} (utc={art.get('utc') or '-'})")
    else:
        print("Last ART validate record: none — run `lab scenario atomic validate`")
    print("")
    print("[Sandcat / CALDERA agent matrix]")
    mx = s.get("agent_matrix") if isinstance(s.get("agent_matrix"), dict) else {}
    for k, v in mx.items():
        print(f"  - {k}: {'connected' if v else 'not connected'}")
    print("")
    print("[Target VM reachability + NAT per-VM]")
    for row in s.get("target_vm_reachability") or []:
        if not isinstance(row, dict):
            continue
        vm = row.get("vm")
        lr = "running" if row.get("libvirt_running") else f"not_running({row.get('libvirt_state')})"
        rr = "reach_ok" if row.get("reachable") else "reach_fail"
        print(f"  - {vm}: libvirt={lr}  access={rr}  {row.get('detail') or ''}")
        if row.get("nat_vm_messages"):
            for m in row.get("nat_vm_messages") or []:
                print(f"      NAT: {m}")
    mir = s.get("mirror") if isinstance(s.get("mirror"), dict) else {}
    print("")
    print("[OVS mirror — runtime/state/mirror.json]")
    if mir.get("mirror_json_present"):
        print(
            f"  consistent={mir.get('consistent')}  sensor_vm={mir.get('sensor_vm')!r}  "
            f"mirror_exists={mir.get('mirror_exists')}"
        )
    else:
        print("  mirror.json missing — a state file may be needed before `lab mirror verify`")
    sn = s.get("snapshots_catalog") if isinstance(s.get("snapshots_catalog"), dict) else {}
    print("")
    print("[Snapshot catalog — runtime/state/snapshots.json]")
    for row in sn.get("per_target") or []:
        if isinstance(row, dict):
            print(
                f"  - {row.get('vm')}: domain_in_catalog={row.get('catalog_domain_defined')} "
                f"snapshot_count={row.get('snapshot_count')}"
            )
    print(f"  vm-manager script: {'present' if s.get('snapshot_vm_manager_present') else 'missing'}")
    natr = s.get("nat_reference") if isinstance(s.get("nat_reference"), dict) else {}
    print("")
    print("[NAT reference — runtime/state/nat.json]")
    print(
        f"  nat.json present: {'yes' if natr.get('nat_json_present') else 'no'}  "
        f"global_ok: {'yes' if natr.get('global_ok') else 'no'}"
    )
    exp = _expected_telemetry_as_str_list(rs.expected_telemetry)
    print("")
    print(f"[expected_telemetry] count: {len(exp)} (no automated verification)")
    if exp:
        for line in exp[:25]:
            print(f"  - {line}")
        if len(exp) > 25:
            print(f"  … plus {len(exp) - 25} more")
    else:
        print("  (empty)")
    print("")
    print("=== CALDERA operation parameters (conceptual) ===")
    print(f"  operation_name: {operation_name}")
    print(f"  adversary_id:   {adversary_id}")
    print(f"  group:          {group}")
    print(f"  planner:        {planner}")
    print(f"  target_vms:     {', '.join(target_vms) if target_vms else '-'}")
    print(f"  snapshot_before: {'yes' if snapshot_before else 'no'}")
    if snapshot_before:
        snm = str(snapshot_name or "").strip() or proposed_snapshot_before_name()
        print(f"  snapshot name (attempted when not dry-run): {snm}")
        print(f"  snapshot target VMs (batch): {', '.join(target_vms) if target_vms else '-'}")
        if is_dry:
            print("  (dry-run: libvirt snapshot not created — name pre-selected only)")
    warns = pf.get("warnings") if isinstance(pf.get("warnings"), list) else []
    blocks = pf.get("blocking") if isinstance(pf.get("blocking"), list) else []
    gates = (
        pf.get("operator_live_gate_failures")
        if isinstance(pf.get("operator_live_gate_failures"), list)
        else []
    )
    if warns:
        print("")
        print("[preflight warnings — review even on dry-run]")
        for w in warns:
            if isinstance(w, dict):
                print(f"  - [{w.get('code')}] {w.get('message')}")
    if is_dry and gates:
        print("")
        print("[non-dry-run hard stops — dry-run now; no CALDERA PUT/snapshot]")
        for b in gates:
            if isinstance(b, dict):
                print(f"  - [{b.get('code')}] {b.get('message')}")
    if blocks:
        print("")
        if is_dry:
            print("[preflight blocks — verify before live; same conditions abort live runs]")
        else:
            print("[preflight blocks — run aborted]")
        for b in blocks:
            if isinstance(b, dict):
                print(f"  - [{b.get('code')}] {b.get('message')}")


def print_scenario_dry_run_checklist_summary(rs: ResolvedScenario, target_vms: list[str]) -> None:
    """Short operator checklist lines for dry-run stdout."""
    exp = _expected_telemetry_as_str_list(rs.expected_telemetry)
    lines = build_operator_telemetry_checklist(
        scenario_id=rs.scenario_id,
        display_name=rs.display_name,
        target_vms=target_vms,
        expected=exp,
        anchor="dry_run",
        last_run=None,
    )
    print("")
    print("=== DRY-RUN: telemetry review checklist (first lines only) ===")
    max_lines = 14
    for ln in lines[:max_lines]:
        print(ln)
    if len(lines) > max_lines:
        print(
            f"… {len(lines) - max_lines} more checklist lines — full list: `lab scenario telemetry {rs.scenario_id}`"
        )


def next_operator_actions_human(scenario: dict[str, Any]) -> list[str]:
    """Actionable next steps from persisted scenario.json (heuristic)."""
    actions: list[str] = []
    st = str(scenario.get("status") or "").strip().lower()
    dry = bool(scenario.get("dry_run"))
    snapr = scenario.get("snapshot_before_result")
    snapnm = str(scenario.get("snapshot_before_name") or "").strip()
    snap_applied = scenario_snapshot_applied(snapr)
    trs = str(scenario.get("telemetry_review_status") or "not_set").strip().lower()
    last_err = str(scenario.get("last_error") or "").strip()
    op_id = None
    cal = scenario.get("caldera") if isinstance(scenario.get("caldera"), dict) else {}
    op_id = str(cal.get("operation_id") or "").strip()

    if st == "running" and op_id:
        actions.append(
            "CALDERA operation is running — monitor via UI and `scenario status` (JSON); end with `lab scenario stop`."
        )
    elif st == "running":
        actions.append(
            "status=running but operation_id is empty — compare CALDERA UI with `scenario status` JSON."
        )

    if st == "blocked" or last_err:
        actions.append(
            f"Recent error/block (last_error={last_err or '-'}, status={st or '-'}). "
            "Check stderr, remediation_hints, `scenario pack validate`, and `bootstrap validate`."
        )

    if snap_applied and snapnm and st != "running":
        rr = scenario.get("recommended_revert")
        if isinstance(rr, str) and rr.strip():
            actions.append(f"Pre-run snapshot was applied — revert candidate: {rr.strip()}")
        else:
            actions.append(
                f"Pre-run snapshot was applied (name={snapnm}) — consider `aella_cli lab snapshot revert {snapnm}` "
                "or the equivalent vm-manager command."
            )

    if trs in ("pending_operator_review", "pending"):
        actions.append(
            "Use `lab scenario telemetry last` to walk expected_telemetry and correlate with your observability stack."
        )

    if bool(scenario.get("cleanup_recommended")):
        actions.append(
            "cleanup_recommended=true — after `scenario stop`, review guest leftovers, CALDERA operations, "
            "and whether `scenario agent remove` is needed."
        )

    if dry and st == "idle":
        actions.append(
            "Last record was dry_run — before a live run, confirm you removed --dry-run from `scenario run …`."
        )

    if not actions:
        actions.append(
            "No special follow-ups — you can re-run `lab scenario run <id> --dry-run` before the next experiment."
        )
    return actions


def cmd_telemetry_verify(
    xdr_root: Path,
    stated: Path,
    cfg: dict[str, Any],
    log_path: Path | None,
    *,
    json_out: bool = False,
    dry_run: bool = False,
) -> int:
    """Placeholder for future automated lab telemetry correlation (no SIEM parsing here).

    Architecture (TODO, additive extension only):
      - Optional collectors under ``scripts/telemetry_verify/`` invoked from this command.
      - Inputs: ``runtime/state/scenario.json`` (``last_history``, ``expected_telemetry``),
        ``logs/caldera-orchestration.jsonl``, optional operator-supplied PCAP paths via env
        (e.g. ``XDR_LAB_TELEMETRY_VERIFY_PCAP_DIR`` — not read in this phase).
      - Outputs: structured report JSON + JSONL events; never mutate CALDERA or guest disks
        from this path unless explicitly specified in a future spec.

    This command MUST NOT emit fabricated pass/fail verdicts against live sensors.
    """
    if log_path:
        log_jsonl(
            log_path,
            "scenario_telemetry_verify_placeholder",
            dry_run=dry_run,
            implementation_status="not_implemented",
            roadmap=(
                "Correlate expected_telemetry strings with evidence channels "
                "(OVS mirror PCAP hints, CALDERA operation timeline, ART execution traces); "
                "operators continue to use `scenario telemetry <id|last>` for manual review."
            ),
            extension_points=[
                "cmd_telemetry_verify → plugin entry `run_telemetry_verify(ctx)`",
                "reuse build_operator_telemetry_checklist / last_history.operation_duration_seconds",
                "preserve JSONL event names; add only new `scenario_telemetry_verify_*` events",
            ],
        )
    doc: dict[str, Any] = {
        "command": "telemetry verify",
        "implementation": "placeholder",
        "dry_run": dry_run,
        "message": (
            "Automated telemetry verification is not implemented yet. "
            "Use `lab scenario telemetry last` and the manual checklist in docs/caldera-integration.md."
        ),
        "see_also": [
            "lab scenario telemetry <NAME|last> [--json]",
            "lab scenario status --human",
            "docs/caldera-integration.md — «Live CALDERA Operation Validation Workflow», «Telemetry review & checklist», «Future: lab scenario telemetry verify»",
        ],
    }
    if json_out:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print("=== lab scenario telemetry verify (reserved / placeholder) ===")
        print(doc["message"])
        print("")
        print("A future version may correlate expected_telemetry, mirror traffic, and CALDERA logs.")
        print("(Currently no verdict or evidence collection — only the JSONL event above is emitted.)")
        print("")
        for line in doc["see_also"]:
            print(f"  - {line}")
    return 0


def cmd_telemetry(
    xdr_root: Path,
    stated: Path,
    cfg: dict[str, Any],
    log_path: Path | None,
    ref: str,
    *,
    json_out: bool = False,
    dry_run: bool = False,
) -> int:
    ref_norm = str(ref or "").strip()
    if not ref_norm:
        print("Usage: scenario telemetry <scenario_id|last|verify> [--json] [--dry-run]", file=sys.stderr)
        return 2
    reg, warns = build_scenario_registry(xdr_root, cfg)
    for w in warns:
        print(f"[warn] {w}", file=sys.stderr)
    if ref_norm.lower() == "verify" and ref_norm not in reg:
        return cmd_telemetry_verify(
            xdr_root, stated, cfg, log_path, json_out=json_out, dry_run=dry_run
        )
    if ref_norm.lower() == "last":
        _ = refresh_state(xdr_root, stated, cfg, log_path=log_path)
        scenario_path = stated / "scenario.json"
        disk = load_json(scenario_path, default_scenario_doc())
        hist = disk.get("last_history") if isinstance(disk.get("last_history"), dict) else None
        if not hist:
            print(
                "scenario.json has no usable last_history. "
                "Run `scenario run` (or dry-run) and `scenario stop` so history is recorded, then retry.",
                file=sys.stderr,
            )
            return 1
        sid = str(hist.get("scenario_id") or "").strip()
        if not sid:
            sid = str(hist.get("scenario_name") or "").strip()
        rs = reg.get(sid) if sid else None
        tv = [str(x) for x in (hist.get("target_vms") or []) if str(x).strip()]
        disp = str(hist.get("display_name") or "").strip()
        et_raw = hist.get("expected_telemetry")
        if rs:
            disp = disp or rs.display_name
            if et_raw in (None, "", []):
                et_raw = rs.expected_telemetry
            sid = sid or rs.scenario_id
        if not sid:
            print("Could not determine scenario id from last_history.", file=sys.stderr)
            return 1
        doc = build_telemetry_review_doc(
            scenario_id=sid,
            display_name=disp or sid,
            target_vms=tv or (rs.target_vms if rs and rs.target_vms else agent_vm_roles(cfg)),
            expected_telemetry=et_raw,
            anchor="last_history",
            last_run=hist,
        )
    else:
        if ref_norm not in reg:
            avail = ", ".join(sorted(reg.keys()))
            print(
                f"Unknown scenario {ref_norm!r}.\n"
                f"Available: {avail}\n"
                "Confirm scenario_id with `scenario list`.",
                file=sys.stderr,
            )
            return 2
        rs = reg[ref_norm]
        tv = rs.target_vms if rs.target_vms else agent_vm_roles(cfg)
        scenario_path = stated / "scenario.json"
        disk = load_json(scenario_path, default_scenario_doc())
        hist = disk.get("last_history") if isinstance(disk.get("last_history"), dict) else None
        last_matching: dict[str, Any] | None = None
        if hist:
            hn = str(hist.get("scenario_name") or "").strip()
            hid = str(hist.get("scenario_id") or "").strip()
            if hn == rs.scenario_id or hid == rs.scenario_id:
                last_matching = hist
        doc = build_telemetry_review_doc(
            scenario_id=rs.scenario_id,
            display_name=rs.display_name,
            target_vms=tv,
            expected_telemetry=rs.expected_telemetry,
            anchor="registry",
            last_run=last_matching,
        )
        if hist and last_matching is None:
            other = str(hist.get("scenario_name") or "").strip() or "?"
            doc["last_history_note"] = (
                f"last_history is for a different scenario ({other!r}). "
                f"For a post-run review of «{rs.scenario_id}», run that scenario then use `telemetry last`."
            )
    if json_out:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print_telemetry_review_human(doc)
        note = doc.get("last_history_note")
        if isinstance(note, str) and note:
            print("")
            print(f"[note] {note}")
    return 0


def default_scenario_doc() -> dict[str, Any]:
    """Operator-facing scenario runtime (persisted to runtime/state/scenario.json).

    Legacy keys (`started_utc`, `stopped_utc`, `current_operation`) are preserved
    for backward-compatible tooling. Newer fields add lifecycle clarity and
    JSONL correlation via `run_id`.
    """
    return {
        "engine": "caldera",
        "run_id": "",
        "scenario_name": "",
        "current_operation": "",
        "status": "idle",
        "started_at": "",
        "started_utc": "",
        "stopped_at": "",
        "stopped_utc": "",
        "dry_run": False,
        "target_vms": [],
        "snapshot_before": False,
        "snapshot_before_name": None,
        "snapshot_before_result": None,
        "caldera": {
            "operation_name": None,
            "operation_id": None,
            "adversary_id": None,
            "group": None,
            "planner": None,
            "server_reported_state": None,
        },
        "cleanup_scope_note": (
            "`scenario stop` finishes the active CALDERA operation only. "
            "`lab cleanup` / vm-manager `cleanup all` tears down lab VMs and is unrelated."
        ),
        "last_stop": None,
        "last_history": None,
        "remediation_hints": [],
        "caldera_server_running": False,
        "agents": {
            "sensor-vm": False,
            "victim-linux": False,
            "windows-victim": False,
        },
        "last_error": None,
        # Operator telemetry review metadata (additive; manual or orchestrator-filled).
        "telemetry_review_notes": "",
        "telemetry_review_status": "not_set",
        "last_operation_summary": None,
        "last_live_run": None,
        "recommended_revert": None,
        "cleanup_recommended": False,
    }


_VALIDATE_PRESERVE_KEYS = frozenset(
    {
        "bootstrap_install_status",
        "bootstrap_install_detail",
        "last_bootstrap_validate_utc",
        "bootstrap_validate_checks",
        "bootstrap_validate_ok",
    }
)


def server_bootstrap_block_from_cfg(
    cfg: dict[str, Any],
    *,
    preserve: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Snapshot of plugins/atomic_red_team from config plus bootstrap_validate* metadata (preserved when set).

    `preserve` is the previous ``caldera.json::server_bootstrap`` block.
    When ``last_bootstrap_validate_utc`` is set, last ``bootstrap validate`` result fields are carried forward
    so ``refresh_state`` from ``scenario list`` does not wipe them.
    """
    pl = cfg.get("plugins")
    art = cfg.get("atomic_red_team")
    block: dict[str, Any] = {
        "plugins": list(pl) if isinstance(pl, list) else [],
        "atomic_red_team": dict(art) if isinstance(art, dict) else {},
        "bootstrap_install_status": "not_probed",
        "bootstrap_install_detail": (
            "Placeholder: confirm actual systemd/docker install on the CALDERA server host. "
            "See bootstrap/caldera-server-bootstrap.sh and systemctl status caldera.service."
        ),
    }
    prev = preserve if isinstance(preserve, dict) else None
    if prev and str(prev.get("last_bootstrap_validate_utc") or "").strip():
        for k in _VALIDATE_PRESERVE_KEYS:
            if k in prev:
                block[k] = prev[k]
    return block


def default_caldera_doc(cfg: dict[str, Any]) -> dict[str, Any]:
    dep = cfg.get("deployment") if isinstance(cfg.get("deployment"), dict) else {}
    doc: dict[str, Any] = {
        "schema_version": 1,
        "base_url": str(cfg.get("base_url") or "http://127.0.0.1:8888"),
        "deployment": dep,
        "http_reachable": False,
        "api_authenticated": False,
        "last_probe_utc": "",
        "caldera_server_running": False,
        "active_caldera_operation_id": None,
        "active_caldera_operation_name": None,
        "last_error": None,
        "agent_deploy_last": None,
        "atomic_red_team_validate_last": None,
        "server_bootstrap": server_bootstrap_block_from_cfg(cfg, preserve=None),
    }
    pl = cfg.get("plugins")
    if isinstance(pl, list):
        doc["plugins"] = pl
    art = cfg.get("atomic_red_team")
    if isinstance(art, dict):
        doc["atomic_red_team"] = art
    return doc


def build_agent_deploy_remediation_hints(
    *,
    is_dry: bool,
    nat_ok: bool,
    caldera_up: bool,
    api_key_present: bool,
    vm_rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Structured hints for agent_deploy_last (and operator stdout cross-reference)."""
    hints: list[dict[str, str]] = []
    if not api_key_present:
        hints.append(
            {
                "code": "api_key_missing",
                "message": "CALDERA API key is empty.",
                "action": "Set XDR_CALDERA_API_KEY, caldera-lab.json api_key_file, or api_key_env.",
            }
        )
    if not caldera_up:
        hints.append(
            {
                "code": "caldera_unreachable",
                "message": "CALDERA HTTP probe (api/agents, etc.) failed from the appliance.",
                "action": "Verify the server is up, base_url, TLS/firewall, and routing.",
            }
        )
    if not nat_ok:
        hints.append(
            {
                "code": "nat_contract_mismatch",
                "message": "Reverse NAT state in runtime/state/nat.json does not match expectations.",
                "action": "On the host run nat verify / nat status and reconcile Golden Image DNAT/iptables.",
            }
        )
    for row in vm_rows:
        if not isinstance(row, dict):
            continue
        st = str(row.get("status") or "")
        if st in ("ok", "dry_run"):
            continue
        vm = str(row.get("vm") or "?")
        detail = str(row.get("detail") or "")
        if st == "failed":
            hints.append(
                {
                    "code": f"vm_failed:{vm}",
                    "message": f"{vm} deploy step failed ({detail}).",
                    "action": "Check VM power, SSH/NAT, and bootstrap logs, then retry agent deploy.",
                }
            )
        elif st == "skipped" and "caldera_unreachable" in detail:
            hints.append(
                {
                    "code": f"vm_skipped_caldera:{vm}",
                    "message": f"{vm}: skipped remote bootstrap because CALDERA was unreachable.",
                    "action": "After CALDERA is reachable, rerun non-dry-run deploy.",
                }
            )
        elif st == "manual":
            hints.append(
                {
                    "code": f"vm_manual_windows:{vm}",
                    "message": f"{vm}: no Windows auto-remote execution path ({detail}).",
                    "action": "Run runtime/caldera-agent/bootstrap-windows.ps1 in an elevated guest PowerShell session.",
                }
            )
    return hints


def finalize_agent_deploy_report(
    deploy_report: dict[str, Any],
    *,
    is_dry: bool,
    fatal_preflight: bool,
    fatal_reason: str | None,
    rc_partial: int,
    nat_ok: bool,
    caldera_up: bool,
    api_key_present: bool,
    vm_rows: list[dict[str, Any]],
) -> int:
    """Populate exit_code / fatal_preflight / remediation_hints; return process exit code."""
    deploy_report["per_vm"] = vm_rows
    deploy_report["vms"] = vm_rows
    deploy_report["remediation_hints"] = build_agent_deploy_remediation_hints(
        is_dry=is_dry,
        nat_ok=nat_ok,
        caldera_up=caldera_up,
        api_key_present=api_key_present,
        vm_rows=vm_rows,
    )
    if is_dry:
        deploy_report["fatal_preflight"] = False
        deploy_report["fatal_reason"] = None
        deploy_report["exit_code"] = 0
        return 0
    deploy_report["fatal_preflight"] = bool(fatal_preflight)
    deploy_report["fatal_reason"] = fatal_reason if fatal_preflight else None
    if fatal_preflight:
        deploy_report["exit_code"] = 2
        return 2
    if rc_partial != 0:
        deploy_report["exit_code"] = 1
        return 1
    deploy_report["exit_code"] = 0
    return 0


def probe_http_reachable(base_url: str, api_key: str, log_path: Path | None) -> bool:
    """True when CALDERA answers HTTP (including 302→/login or 401 without a valid key)."""
    c = CalderaClient(base_url, api_key, timeout_sec=4.0)
    for idx in ("agents", "abilities"):
        code, _, err = c.get_index(idx, log_path)
        if code == 0:
            continue
        if code == 200 and err is None:
            return True
        if err == "auth_required" or code in (401, 403):
            return True
        if code in (301, 302, 303, 307, 308):
            return True
    code, _, err = c.request_json("GET", base_url.rstrip("/") + "/", body=None, log_path=log_path)
    if code == 0:
        return False
    if err == "auth_required":
        return True
    return code in (200, 302, 401, 403)


def probe_http(base_url: str, api_key: str, log_path: Path | None) -> bool:
    """Backward-compatible alias: HTTP reachability (not API-authenticated)."""
    return probe_http_reachable(base_url, api_key, log_path)


def probe_api_authenticated(client: CalderaClient, log_path: Path | None) -> bool:
    code, data, err = client.get_index("agents", log_path)
    return code == 200 and isinstance(data, list) and err is None


def classify_agents_fetch_error(client: CalderaClient, err: str | None) -> str | None:
    if not err:
        return err
    if not str(client.api_key or "").strip():
        if err == "auth_required":
            return "api_key_missing"
        return err
    if err == "auth_required":
        return "api_key_invalid"
    return err


def fetch_agents(client: CalderaClient, log_path: Path | None) -> list[dict[str, Any]]:
    code, data, err = client.get_index("agents", log_path)
    if code != 200 or not isinstance(data, list):
        err = classify_agents_fetch_error(client, err)
        if err and "refused" not in str(err).lower():
            log_jsonl(
                log_path,
                "caldera_agents_fetch_failed",
                http_code=code,
                auth_header=client.last_auth_header or CALDERA_API_AUTH_HEADER,
                location=client.last_location,
                content_type=client.last_content_type,
                error=err,
            )
        return []
    out: list[dict[str, Any]] = []
    for row in data:
        if isinstance(row, dict):
            out.append(row)
    return out


def agent_matches(row: dict[str, Any], substrings: list[str]) -> bool:
    hay = " ".join(
        str(row.get(k) or "")
        for k in ("paw", "host", "display_name", "platform", "group", "contact")
    ).lower()
    return any(s.lower() in hay for s in substrings if s)


def agent_vm_roles(cfg: dict[str, Any]) -> list[str]:
    """VM names that participate in CALDERA agent deploy/status (caldera-lab.json::agents)."""
    raw = cfg.get("agents")
    if not isinstance(raw, dict):
        return ["sensor-vm", "victim-linux", "windows-victim"]
    ordered: list[str] = []
    for name in ("sensor-vm", "victim-linux", "windows-victim"):
        if name not in raw:
            continue
        spec = raw[name]
        if isinstance(spec, dict) and spec.get("enabled") is False:
            continue
        ordered.append(name)
    for name in sorted(raw.keys()):
        if name.startswith("_") or name in ordered:
            continue
        spec = raw.get(name)
        if not isinstance(spec, dict):
            continue
        if spec.get("enabled") is False:
            continue
        ordered.append(name)
    return ordered or ["sensor-vm", "victim-linux", "windows-victim"]


def build_agent_matrix(
    cfg: dict[str, Any], agents: list[dict[str, Any]]
) -> dict[str, bool]:
    vm_map = cfg.get("agent_vm_map")
    if not isinstance(vm_map, dict):
        vm_map = {}
    roles = agent_vm_roles(cfg)
    result: dict[str, bool] = {vm: False for vm in roles}
    for vm in roles:
        spec = vm_map.get(vm)
        subs: list[str] = []
        if isinstance(spec, dict):
            raw = spec.get("host_substrings")
            if isinstance(raw, list):
                subs = [str(x) for x in raw if str(x).strip()]
        for row in agents:
            if agent_matches(row, subs):
                result[vm] = True
                break
    return result


def extract_operation_id(resp: Any) -> str | None:
    if isinstance(resp, dict):
        for k in ("id", "op_id", "operation_id"):
            v = resp.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
    if isinstance(resp, list):
        for item in resp:
            oid = extract_operation_id(item)
            if oid:
                return oid
    return None


def find_operation_row_by_id(
    client: CalderaClient, op_id: str | None, log_path: Path | None
) -> tuple[str | None, dict[str, Any] | None]:
    """Return (state, row) for a CALDERA operation id from GET /api/operations."""
    if not op_id or not str(op_id).strip():
        return None, None
    code, data, _err = client.get_index("operations", log_path)
    if code != 200 or not isinstance(data, list):
        return None, None
    want = str(op_id).strip()
    want_num = int(want) if want.isdigit() else None
    for row in data:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or row.get("op_id") or "").strip()
        if not rid:
            continue
        if rid == want or (want_num is not None and rid == str(want_num)):
            st = row.get("state")
            return (str(st) if st is not None else None, row)
    return None, None


def _touch_utc_aliases(doc: dict[str, Any]) -> None:
    """Keep started_at/stopped_at in sync with started_utc/stopped_utc (same UTC Z string)."""
    su = str(doc.get("started_utc") or "").strip()
    if su:
        doc["started_at"] = su
    stp = str(doc.get("stopped_utc") or "").strip()
    if stp:
        doc["stopped_at"] = stp


def _ensure_scenario_nested_defaults(doc: dict[str, Any]) -> None:
    defaults = default_scenario_doc()
    for k, v in defaults.items():
        if k not in doc:
            doc[k] = json.loads(json.dumps(v)) if isinstance(v, (dict, list)) else v
    cal = doc.get("caldera")
    if not isinstance(cal, dict):
        doc["caldera"] = dict(defaults["caldera"])
    else:
        for ck, cv in defaults["caldera"].items():
            cal.setdefault(ck, cv)


def build_stop_remediation_hints(
    *,
    stop_http_failed: bool,
    operation_still_running: bool,
    snapshot_before_applied: bool,
    caldera_unreachable: bool,
    snapshot_before_name: str | None = None,
) -> list[dict[str, str]]:
    hints: list[dict[str, str]] = []
    if caldera_unreachable:
        hints.append(
            {
                "code": "caldera_unreachable",
                "message": "Cannot reach CALDERA over HTTP, so operation completion could not be verified.",
                "action": "Check base_url, firewall, and the CALDERA service, then confirm operation state in the UI.",
            }
        )
    if stop_http_failed:
        hints.append(
            {
                "code": "caldera_stop_post_failed",
                "message": "CALDERA REST POST to set operation state=finished failed.",
                "action": "In the CALDERA UI manually complete/cancel the operation, or fix network/API key and retry `scenario stop`.",
            }
        )
    if operation_still_running:
        hints.append(
            {
                "code": "caldera_operation_still_running",
                "message": "The server still reports at least one operation in a non-terminal state (e.g. running).",
                "action": "Finish the operation in the UI or inspect the agent/ability queue. Preserve data before restarting CALDERA if needed.",
            }
        )
    hints.append(
        {
            "code": "guest_orphaned_process_possible",
            "message": "The appliance orchestrator does not leave long-lived processes, but Sandcat/ability processes inside guest VMs are separate.",
            "action": "SSH/RDP into affected VMs to inspect processes, or use `scenario agent` flows to clean up agents.",
        }
    )
    if snapshot_before_applied:
        nm = str(snapshot_before_name or "").strip()
        rev = (
            f"`xdr-lab-vm-manager.sh snapshot revert {nm}` (or `aella_cli lab snapshot revert {nm}`)"
            if nm
            else "`xdr-lab-vm-manager.sh snapshot revert <name>` or `aella_cli lab snapshot revert <name>`"
        )
        hints.append(
            {
                "code": "snapshot_revert_recommended",
                "message": "A pre-run snapshot exists and the scenario ended abnormally or attack residue is a concern.",
                "action": f"Consider reverting batch VMs with {rev}. `scenario stop` does not perform an automatic revert.",
            }
        )
    return hints


def build_snapshot_before_failure_hints(snapshot_name: str) -> list[dict[str, str]]:
    """When batch snapshot (vm-manager) fails before scenario run."""
    sn = str(snapshot_name or "").strip() or "<name>"
    return [
        {
            "code": "snapshot_before_libvirt_failed",
            "message": "Batch libvirt snapshot creation failed before scenario run.",
            "action": f"On the host run `virsh list --all` to confirm domains exist, then run `xdr-lab-vm-manager.sh snapshot create {sn}` alone and inspect stderr.",
        },
        {
            "code": "snapshot_before_disk_or_state",
            "message": "Failure may be due to low snapshot space, paused VM state, or QEMU snapshot limits.",
            "action": "Check free disk on the KVM host, VM power state, and existing snapshot count; retry with the same name or change the name and validate `snapshot create`.",
        },
        {
            "code": "snapshot_before_script_missing",
            "message": "Without `scripts/xdr-lab-vm-manager.sh` the orchestrator cannot invoke snapshots.",
            "action": "Confirm the vm-manager script is deployed under the XDR root and that `XDR_BASE`/`XDR_ROOT` are correct.",
        },
    ]


def scenario_snapshot_applied(result: Any) -> bool:
    return str(result or "") == "applied"


def proposed_snapshot_before_name() -> str:
    """Batch snapshot name (libvirt) for scenario pre-run; stable pattern for operators."""
    return f"pre-scenario-{utc_now().replace(':', '')}"


def find_agent_paws(cfg: dict[str, Any], agents: list[dict[str, Any]], vm: str) -> list[str]:
    vm_map = cfg.get("agent_vm_map") if isinstance(cfg.get("agent_vm_map"), dict) else {}
    spec = vm_map.get(vm, {})
    subs: list[str] = []
    if isinstance(spec, dict):
        raw = spec.get("host_substrings")
        if isinstance(raw, list):
            subs = [str(x) for x in raw if str(x).strip()]
    paws: list[str] = []
    for row in agents:
        if not isinstance(row, dict):
            continue
        if agent_matches(row, subs):
            paw = str(row.get("paw") or "").strip()
            if paw:
                paws.append(paw)
    return paws


def write_agent_bootstraps(xdr_root: Path, base_url: str, log_path: Path | None) -> None:
    """Emit Sandcat-style bootstrap hints (operator runs on victim VMs)."""
    out_dir = xdr_root / "runtime" / "caldera-agent"
    out_dir.mkdir(parents=True, exist_ok=True)
    bu = base_url.rstrip("/")
    # CALDERA standard Sandcat one-liners (HTTP contact); operator must pick correct binary in UI if needed.
    ps1 = out_dir / "bootstrap-windows.ps1"
    sh = out_dir / "bootstrap-linux.sh"
    ps1.write_text(
        f"""# Generated by caldera_orchestration.py — run on Windows victim (elevated if required).
$server="{bu}"
# Typical Sandcat pull (plugin / deployment may vary — verify in CALDERA UI if this fails):
try {{
  IEX (New-Object Net.WebClient).DownloadString("$server/file/download/sandcat.go")
}} catch {{
  Write-Error $_
}}
""",
        encoding="utf-8",
    )
    sh.write_text(
        f"""#!/bin/sh
# Generated by caldera_orchestration.py — run on Linux victim.
set -e
SERVER="{bu}"
curl -fsSL "$SERVER/file/download/sandcat.go" | python3 - 2>/dev/null || curl -fsSL "$SERVER/file/download/sandcat.sh" | sh
""",
        encoding="utf-8",
    )
    try:
        os.chmod(sh, 0o755)
    except OSError:
        pass
    if log_path:
        log_jsonl(
            log_path,
            "caldera_agent_bootstrap_written",
            windows_script=str(ps1),
            linux_script=str(sh),
        )


def load_lab_vms_json(xdr_root: Path) -> dict[str, Any]:
    doc = load_json(xdr_root / "config" / "lab-vms.json", {})
    return doc if isinstance(doc, dict) else {}


def load_nat_state_doc(stated: Path) -> dict[str, Any]:
    doc = load_json(stated / "nat.json", {})
    return doc if isinstance(doc, dict) else {}


def vm_libvirt_running(vm: str) -> tuple[bool, str]:
    if domstate is None or domain_exists is None:
        return False, "libvirt_probe_unavailable"
    if not domain_exists(vm):
        return False, "domain_missing"
    st = domstate(vm)
    return (st == "running"), st or "unknown"


def lab_vm_entry(lab: dict[str, Any], vm: str) -> dict[str, Any]:
    vms = lab.get("vms") if isinstance(lab.get("vms"), dict) else {}
    row = vms.get(vm)
    return row if isinstance(row, dict) else {}


def agent_spec_for_vm(cfg: dict[str, Any], vm: str) -> dict[str, Any]:
    agents = cfg.get("agents")
    if not isinstance(agents, dict):
        return {}
    spec = agents.get(vm)
    return spec if isinstance(spec, dict) else {}


def linux_materialized_ip(lab: dict[str, Any]) -> str:
    return str(lab_vm_entry(lab, "victim-linux").get("internal_ip") or "10.10.10.20")


def nat_reverse_happy(nat_doc: dict[str, Any]) -> tuple[bool, list[str]]:
    notes: list[str] = []
    if not nat_doc:
        notes.append("No nat.json — run `nat status` or `nat verify` on the host.")
        return False, notes
    if not bool(nat_doc.get("iptables_readable", True)):
        notes.append("iptables query failed — check root privileges and that iptables is installed.")
    miss = nat_doc.get("missing")
    if isinstance(miss, list) and miss:
        notes.append(f"Missing NAT rules: {len(miss)} (see nat.json missing[]).")
    if nat_doc.get("consistent") is False:
        notes.append(
            "nat.json consistent=false — Golden Image DNAT/MASQUERADE does not match live iptables."
        )
    ok = bool(nat_doc.get("consistent", True)) and bool(nat_doc.get("iptables_readable", True))
    if isinstance(miss, list) and miss:
        ok = False
    return ok, notes


def nat_row_present(vm: str, ext_port: int, nat_doc: dict[str, Any]) -> bool | None:
    for row in nat_doc.get("dnat") or []:
        if not isinstance(row, dict):
            continue
        if row.get("vm") != vm:
            continue
        try:
            ep = int(row.get("external_port") or 0)
        except (TypeError, ValueError):
            continue
        if ep == ext_port:
            return bool(row.get("present"))
    return None


def required_nat_for_vm(vm: str, lab: dict[str, Any], nat_doc: dict[str, Any]) -> tuple[bool, list[str]]:
    msgs: list[str] = []
    dnat_list = nat_doc.get("dnat") if isinstance(nat_doc.get("dnat"), list) else []
    if not dnat_list:
        return True, msgs

    entry = lab_vm_entry(lab, vm)
    pmap = entry.get("external_nat_port_mapping") if isinstance(entry.get("external_nat_port_mapping"), dict) else {}
    vtype = str(entry.get("type") or "")
    ok = True
    if vtype == "windows":
        raw_rp = pmap.get("rdp")
        try:
            rport = int(raw_rp) if raw_rp is not None and str(raw_rp).strip() else None
        except (TypeError, ValueError):
            rport = None
        if rport is not None:
            st = nat_row_present(vm, rport, nat_doc)
            if st is False:
                ok = False
                msgs.append(f"NAT DNAT mismatch: {vm} RDP external tcp/{rport}")
            elif st is None:
                msgs.append(f"No NAT DNAT record: {vm} RDP tcp/{rport} — refresh with `nat verify`.")
    else:
        raw_sp = pmap.get("ssh")
        try:
            sport = int(raw_sp) if raw_sp is not None and str(raw_sp).strip() else None
        except (TypeError, ValueError):
            sport = None
        if sport is not None:
            st = nat_row_present(vm, sport, nat_doc)
            if st is False:
                ok = False
                msgs.append(f"NAT DNAT mismatch: {vm} SSH external tcp/{sport}")
            elif st is None:
                msgs.append(f"No NAT DNAT record: {vm} SSH tcp/{sport} — refresh with `nat verify`.")
    return ok, msgs


def ssh_stdin_remote_linux(host: str, user: str, script_body: str) -> tuple[int, str]:
    if not host or not user:
        return 1, "missing_host_or_user"
    proc = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=10",
            f"{user}@{host}",
            "bash",
            "-s",
        ],
        input=script_body,
        capture_output=True,
        text=True,
        timeout=240,
    )
    tail = (proc.stderr or proc.stdout or "")[-1600:]
    return int(proc.returncode or 0), tail


def ssh_stdin_remote_linux_full(
    host: str,
    user: str,
    script_body: str,
    *,
    timeout: int = 120,
) -> tuple[int, str, str]:
    """Pipe a script to bash -s on a Linux guest; returns full stdout/stderr."""
    if not host or not user:
        return 1, "", "missing_host_or_user"
    proc = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=10",
            f"{user}@{host}",
            "bash",
            "-s",
        ],
        input=script_body,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return int(proc.returncode or 0), proc.stdout or "", proc.stderr or ""


def resolve_linux_ssh_user(vm: str, cfg: dict[str, Any], lab: dict[str, Any]) -> str:
    spec = agent_spec_for_vm(cfg, vm)
    override = str(spec.get("ssh_user") or "").strip()
    if override:
        return override
    if vm == "victim-linux":
        return os.environ.get("VICTIM_LINUX_SSH_USER", "lab").strip() or "lab"
    entry = lab_vm_entry(lab, vm)
    vtype = str(entry.get("type") or "")
    if pick_ssh_user is not None:
        lu = os.environ.get("VICTIM_LINUX_SSH_USER", "ubuntu").strip() or "ubuntu"
        return pick_ssh_user(vm, vtype, lu, entry) or "ubuntu"
    return "ubuntu"


def probe_host_for_vm(vm: str, lab: dict[str, Any]) -> str:
    if expected_ip_for_vm is None:
        return ""
    lmi = linux_materialized_ip(lab)
    return str(expected_ip_for_vm(lab, vm, lmi) or "").strip()


def actual_ip_hint(vm: str) -> str:
    if collect_domifaddr_ipv4 is None:
        return ""
    ips = collect_domifaddr_ipv4(vm)
    return ips[0] if ips else ""


def windows_transport_inventory(entry: dict[str, Any]) -> dict[str, Any]:
    pmap = entry.get("external_nat_port_mapping") if isinstance(entry.get("external_nat_port_mapping"), dict) else {}

    def _pi(key: str) -> int | None:
        raw = pmap.get(key)
        if raw is None or not str(raw).strip():
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    return {
        "ssh_ext": _pi("ssh"),
        "rdp_ext": _pi("rdp"),
        "winrm_https_ext": _pi("winrm_https"),
        "winrm_http_ext": _pi("winrm_http"),
    }


def probe_windows_access(vm: str, lab: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "inventory": {},
        "ssh_ok": False,
        "winrm_tcp": False,
        "rdp_tcp": False,
        "picked": "none",
    }
    if tcp_port_open is None or primary_bind_ipv4 is None:
        out["note"] = "tcp_probe_unavailable"
        return out
    entry = lab_vm_entry(lab, vm)
    inv = windows_transport_inventory(entry)
    out["inventory"] = {k: v for k, v in inv.items() if v is not None}
    internal = str(entry.get("internal_ip") or "").strip()
    ext = (primary_bind_ipv4() or "").strip()
    win_user = str(agent_spec_for_vm(cfg, vm).get("ssh_user") or "").strip() or os.environ.get(
        "XDR_LAB_WINDOWS_SSH_USER", ""
    ).strip() or str(entry.get("ssh_user") or "").strip()

    if internal:
        out["rdp_tcp"] = bool(tcp_port_open(internal, 3389, timeout=2.0))
        out["winrm_tcp"] = bool(
            tcp_port_open(internal, 5986, timeout=1.6) or tcp_port_open(internal, 5985, timeout=1.6)
        )

    wh = inv.get("winrm_https_ext")
    if wh and ext:
        if tcp_port_open(ext, int(wh), timeout=2.0):
            out["winrm_tcp"] = True

    ssh_ext = inv.get("ssh_ext")
    if ssh_ext and ext and win_user:
        rc = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "ConnectTimeout=10",
                "-p",
                str(ssh_ext),
                f"{win_user}@{ext}",
                "true",
            ],
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        out["ssh_ok"] = rc == 0
    elif internal and win_user and ssh_batch_cmd is not None:
        out["ssh_ok"] = bool(ssh_batch_cmd(internal, win_user, "true"))

    if out["ssh_ok"]:
        out["picked"] = "ssh"
    elif out["winrm_tcp"]:
        out["picked"] = "winrm_https"
    elif out["rdp_tcp"]:
        out["picked"] = "rdp_only"
    return out


def deploy_effective_dry(cli_dry: bool) -> bool:
    return dry_run() or cli_dry


def probe_ssh_linux_vm(vm: str, lab: dict[str, Any], cfg: dict[str, Any]) -> tuple[bool, str]:
    user = resolve_linux_ssh_user(vm, cfg, lab)
    exp = probe_host_for_vm(vm, lab)
    act = actual_ip_hint(vm)
    host = act or exp
    if not host:
        return False, "no_target_ip"
    if ssh_batch_cmd is None:
        return False, "ssh_probe_unavailable"
    if ssh_batch_cmd(host, user, "true"):
        return True, f"ssh_ok user={user} host={host}"
    return False, f"ssh_unreachable user={user} host={host}"


def run_lab_snapshot_batch_create(
    xdr_root: Path,
    log_path: Path | None,
    snapshot_name: str,
    *,
    run_id: str,
    scenario_name: str,
    target_vms: list[str],
    dry_run: bool,
) -> tuple[int, str]:
    """Invoke vm-manager batch snapshot. Returns (rc, stderr_snippet).

    Emits JSONL: snapshot_before_requested; on success snapshot_before_created;
    on failure snapshot_before_failed. Does not perform revert.
    """
    mgr = xdr_root / "scripts" / "xdr-lab-vm-manager.sh"
    nm = str(snapshot_name or "").strip()
    if not nm:
        nm = proposed_snapshot_before_name()
    if log_path:
        log_jsonl(
            log_path,
            "snapshot_before_requested",
            run_id=run_id,
            scenario=scenario_name,
            snapshot_name=nm,
            target_vms=target_vms,
            dry_run=dry_run,
        )
    if not mgr.is_file():
        if log_path:
            log_jsonl(
                log_path,
                "snapshot_before_failed",
                run_id=run_id,
                scenario=scenario_name,
                snapshot_name=nm,
                reason="vm_manager_missing",
                path=str(mgr),
            )
        return 1, "vm_manager_missing"
    env = os.environ.copy()
    env.setdefault("XDR_BASE", str(xdr_root))
    env.setdefault("XDR_ROOT", str(xdr_root))
    proc = subprocess.run(
        ["bash", str(mgr), "snapshot", "create", nm],
        cwd=str(xdr_root),
        env=env,
        capture_output=True,
        text=True,
    )
    rc = int(proc.returncode or 0)
    err_tail = (proc.stderr or "")[-4000:]
    if log_path:
        if rc == 0:
            log_jsonl(
                log_path,
                "snapshot_before_created",
                run_id=run_id,
                scenario=scenario_name,
                snapshot_name=nm,
                rc=rc,
                dry_run=dry_run,
            )
        else:
            log_jsonl(
                log_path,
                "snapshot_before_failed",
                run_id=run_id,
                scenario=scenario_name,
                snapshot_name=nm,
                rc=rc,
                stderr_tail=err_tail.strip() or None,
            )
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return rc, err_tail


def refresh_state(
    xdr_root: Path,
    stated: Path,
    cfg: dict[str, Any],
    *,
    merge_scenario: dict[str, Any] | None = None,
    merge_caldera: dict[str, Any] | None = None,
    log_path: Path | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    base_url = str(cfg.get("base_url") or "http://127.0.0.1:8888")
    client = make_caldera_client(cfg)
    reachable = probe_http_reachable(base_url, client.api_key, log_path)
    authenticated = probe_api_authenticated(client, log_path) if reachable else False
    agents = fetch_agents(client, log_path) if authenticated else []
    matrix = build_agent_matrix(cfg, agents)

    scenario_path = stated / "scenario.json"
    caldera_path = stated / "caldera.json"
    scenario_doc = load_json(scenario_path, default_scenario_doc())
    if not isinstance(scenario_doc, dict):
        scenario_doc = default_scenario_doc()
    caldera_doc = load_json(caldera_path, default_caldera_doc(cfg))
    if not isinstance(caldera_doc, dict):
        caldera_doc = default_caldera_doc(cfg)

    prev_reachable = bool(caldera_doc.get("caldera_server_running"))
    prev_agents = (
        scenario_doc.get("agents") if isinstance(scenario_doc.get("agents"), dict) else {}
    )

    scenario_doc["engine"] = "caldera"
    scenario_doc["caldera_server_running"] = reachable
    scenario_doc["caldera_api_authenticated"] = authenticated
    scenario_doc["agents"] = matrix
    if merge_scenario:
        cal_in = merge_scenario.get("caldera")
        shallow = {k: v for k, v in merge_scenario.items() if k != "caldera"}
        scenario_doc.update(shallow)
        if isinstance(cal_in, dict):
            cal_existing = scenario_doc.get("caldera")
            if not isinstance(cal_existing, dict):
                scenario_doc["caldera"] = {}
            scenario_doc["caldera"].update(cal_in)
    _ensure_scenario_nested_defaults(scenario_doc)
    _touch_utc_aliases(scenario_doc)
    caldera_doc["base_url"] = base_url
    caldera_doc["http_reachable"] = reachable
    caldera_doc["api_authenticated"] = authenticated
    caldera_doc["last_probe_utc"] = utc_now()
    caldera_doc["caldera_server_running"] = reachable
    caldera_doc["agent_matrix_last"] = matrix
    pl = cfg.get("plugins")
    if isinstance(pl, list):
        caldera_doc["plugins"] = pl
    art = cfg.get("atomic_red_team")
    if isinstance(art, dict):
        caldera_doc["atomic_red_team"] = art
    prev_sb = caldera_doc.get("server_bootstrap")
    caldera_doc["server_bootstrap"] = server_bootstrap_block_from_cfg(
        cfg,
        preserve=prev_sb if isinstance(prev_sb, dict) else None,
    )
    if merge_caldera:
        caldera_doc.update(merge_caldera)
    if reachable and not prev_reachable and log_path:
        log_jsonl(log_path, "caldera_server_started", base_url=base_url)
    if log_path:
        for vm, ok in matrix.items():
            if ok and not bool(prev_agents.get(vm)):
                log_jsonl(log_path, "caldera_agent_connected", vm=vm)

    save_json_atomic(scenario_path, scenario_doc)
    save_json_atomic(caldera_path, caldera_doc)
    return scenario_doc, caldera_doc


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_list(cfg: dict[str, Any], stated: Path, log_path: Path | None) -> int:
    xdr_root = Path(stated.parent.parent).resolve()
    reg, warns = build_scenario_registry(xdr_root, cfg)
    if warns:
        for w in warns:
            print(f"[warn] {w}", file=sys.stderr)
        if scenario_pack_strict():
            refresh_state(xdr_root, stated, cfg, log_path=log_path)
            print(
                "Error: corrupted scenario pack(s); listing aborted. "
                "(strict mode: XDR_LAB_SCENARIO_PACK_STRICT=1)",
                file=sys.stderr,
            )
            return 1
    print("CALDERA scenarios (scenario pack merged with caldera-lab.json):")
    print_scenario_registry_table(reg)
    _scenario_doc, caldera_doc = refresh_state(xdr_root, stated, cfg, log_path=log_path)
    if not bool(caldera_doc.get("api_authenticated")):
        if not bool(caldera_doc.get("http_reachable")):
            print(
                "[note] CALDERA HTTP unreachable — agent matrix not updated; "
                "check base_url and caldera.service.",
                file=sys.stderr,
            )
        else:
            print(
                "[note] CALDERA API not authenticated — agent roles not fetched. "
                "Run: sudo bootstrap/ensure-caldera-api-key.sh "
                "(see docs/caldera-integration.md §3).",
                file=sys.stderr,
            )
    return 0


def cmd_status(
    cfg: dict[str, Any], stated: Path, log_path: Path | None, *, human: bool = False
) -> int:
    xdr_root = Path(stated.parent.parent)
    scenario_doc, caldera_doc = refresh_state(xdr_root, stated, cfg, log_path=log_path)
    api_key = resolve_api_key(cfg)
    base_url = str(cfg.get("base_url") or "http://127.0.0.1:8888")
    client = CalderaClient(base_url, api_key)
    op_id = caldera_doc.get("active_caldera_operation_id")
    if op_id and str(op_id).strip() and bool(caldera_doc.get("http_reachable")):
        st, _row = find_operation_row_by_id(client, str(op_id), log_path)
        if isinstance(scenario_doc.get("caldera"), dict):
            scenario_doc["caldera"]["server_reported_state"] = st
    if human:
        _print_scenario_status_human(scenario_doc, caldera_doc, xdr_root, cfg)
        return 0
    print(json.dumps({"scenario": scenario_doc, "caldera": caldera_doc}, indent=2, ensure_ascii=False))
    return 0


def build_operator_troubleshooting_hints_for_status(
    scenario: dict[str, Any],
    caldera: dict[str, Any],
    stated_p: Path,
    cfg: dict[str, Any],
) -> list[str]:
    """Action-oriented English hints for first-live triage (reference only; no auto-verdict)."""
    out: list[str] = []
    seen: set[str] = set()

    def add(tag: str, line: str) -> None:
        if tag in seen:
            return
        seen.add(tag)
        out.append(line)

    err = str(scenario.get("last_error") or "").strip()
    err_l = err.lower()
    st = str(scenario.get("status") or "").strip().lower()

    if not bool(caldera.get("http_reachable")):
        add(
            "caldera_unreachable",
            "CALDERA unreachable from the appliance: confirm the server process, base_url bind, TLS/proxy, "
            "and host firewall; run `scenario bootstrap validate` and compare stderr with JSONL caldera_* lines.",
        )

    if "http_401" in err_l or "http_403" in err_l:
        add(
            "api_key_invalid",
            "CALDERA rejected the API key (HTTP 401/403): align XDR_CALDERA_API_KEY or caldera-lab.json "
            "api_key_file / api_key_env with the KEY the server expects, then re-run `scenario bootstrap validate`.",
        )

    agents = scenario.get("agents") if isinstance(scenario.get("agents"), dict) else {}
    missing = [str(k) for k, v in agents.items() if not v and str(k).strip()]
    if missing and bool(caldera.get("http_reachable")):
        add(
            "agent_missing",
            "Expected Sandcat roles show disconnected in the agent matrix: "
            + ", ".join(missing)
            + ". Run `scenario agent deploy` (non-dry), confirm CALDERA UI paws, and tune caldera-lab.json::agent_vm_map host_substrings.",
        )

    mir_path = stated_p / "mirror.json"
    mir = load_mirror_doc(stated_p)
    if not mir_path.is_file():
        add(
            "mirror_unavailable",
            "mirror.json is absent: run `xdr-lab-vm-manager.sh mirror status` then `aella_cli lab mirror verify` before relying on SPAN/mirror traffic to the sensor.",
        )
    elif mir.get("consistent") is False:
        add(
            "mirror_inconsistent",
            "mirror.json reports consistent=false: OVS mirror intent does not match ovs-vsctl reality — run `lab mirror verify` and reconcile apply steps.",
        )

    snapr = scenario.get("snapshot_before_result")
    if err == "snapshot_before_failed" or str(snapr or "").lower() in ("failed", "error"):
        add(
            "snapshot_failure",
            "Pre-run snapshot path failed: inspect JSONL snapshot_before_failed, libvirt disk space, VM power state, "
            "and `vm-manager.sh snapshot create` logs; retry with `scenario run … --dry-run` to rehearse the catalog path.",
        )

    if st == "blocked" and err.startswith("preflight_"):
        add(
            "vm_reachability",
            "Preflight blocked on reachability or lab contract: read blocking_codes from the last preflight (stdout/JSONL), "
            "confirm libvirt running, reverse NAT ports, SSH/RDP paths, and `nat verify` on the host.",
        )

    if "adversary" in err_l and ("missing" in err_l or "uuid" in err_l or "mismatch" in err_l):
        add(
            "adversary_uuid_mismatch",
            "Adversary UUID missing or mismatched: register the CALDERA UI adversary id in the scenario pack `caldera.adversary_id` "
            "or caldera-lab.json::scenarios fallback; `scenario pack validate` surfaces the merged value.",
        )

    nat_doc = load_nat_state_doc(stated_p)
    nat_ok, nat_notes = nat_reverse_happy(nat_doc)
    if not nat_ok and nat_notes:
        add(
            "nat_contract",
            "Reverse NAT snapshot is not healthy: " + nat_notes[0] + " Use `nat verify` / `nat status` on the KVM host.",
        )

    snap_cat = load_snapshots_catalog_doc(stated_p)
    per_vm = snap_cat.get("per_vm") if isinstance(snap_cat.get("per_vm"), dict) else {}
    snap_catalog_weak = not (stated_p / "snapshots.json").is_file() or not per_vm
    if snap_catalog_weak and (
        bool(scenario.get("snapshot_before"))
        or "snapshot" in err_l
        or (err.startswith("preflight") if err else False)
    ):
        add(
            "snapshots_catalog",
            "snapshots.json missing or empty per_vm: refresh the catalog via vm-manager snapshot flows so preflight can size rollback coverage.",
        )

    llr = scenario.get("last_live_run") if isinstance(scenario.get("last_live_run"), dict) else None
    if llr:
        pfs = llr.get("preflight_summary") if isinstance(llr.get("preflight_summary"), dict) else {}
        bc = pfs.get("blocking_codes") if isinstance(pfs.get("blocking_codes"), list) else []
        if any("reach" in str(x).lower() for x in bc):
            add(
                "vm_reachability_llr",
                "last_live_run preflight_summary lists reachability-related blocking_codes — re-check NAT, VM power, and SSH/RDP for target_vms.",
            )

    return out


def _print_scenario_status_human(
    scenario: dict[str, Any], caldera: dict[str, Any], xdr_root: Path, cfg: dict[str, Any]
) -> None:
    """English operator summary (stdout). JSON consumers should omit --human."""
    cal = scenario.get("caldera") if isinstance(scenario.get("caldera"), dict) else {}
    agents = scenario.get("agents") if isinstance(scenario.get("agents"), dict) else {}
    hist = scenario.get("last_history") if isinstance(scenario.get("last_history"), dict) else None
    last_stop = scenario.get("last_stop") if isinstance(scenario.get("last_stop"), dict) else None
    hints = scenario.get("remediation_hints")
    if not isinstance(hints, list):
        hints = []
    los = scenario.get("last_operation_summary") if isinstance(scenario.get("last_operation_summary"), dict) else None
    stated_p = xdr_root / "runtime" / "state"
    mir_doc = load_mirror_doc(stated_p)
    nat_doc = load_nat_state_doc(stated_p)
    snap_doc = load_snapshots_catalog_doc(stated_p)
    triage = build_operator_troubleshooting_hints_for_status(scenario, caldera, stated_p, cfg)

    print("=== lab scenario status --human ===")
    print("")
    print("--- Scenario core (scenario.json + live probe) ---")
    if scenario.get("status") == "running" and (scenario.get("current_operation") or scenario.get("scenario_name")):
        cur = scenario.get("current_operation") or scenario.get("scenario_name")
        print(f"Running scenario: {cur}")
    else:
        print("Running scenario: (none) — last_history and the CALDERA operation block below describe recent activity.")
    print(f"Engine: {scenario.get('engine', '-')}")
    print(f"Status: {scenario.get('status', '-')}")
    print(f"run_id: {scenario.get('run_id') or '-'}")
    print(f"Current scenario name: {scenario.get('scenario_name') or scenario.get('current_operation') or '-'}")
    print(f"dry_run (last recorded): {'yes' if scenario.get('dry_run') else 'no'}")
    print(f"Target VMs (target_vms): {', '.join(scenario.get('target_vms') or []) or '-'}")
    tvs = [str(x) for x in (scenario.get("target_vms") or []) if str(x).strip()]
    if tvs:
        print("")
        print("  L2 contract hints (fixed lab; config/lab-vms.json is authoritative):")
        for vm in tvs:
            ip_hint = _LAB_VM_IP_HINTS.get(vm, "(per-role IPs: config/lab-vms.json)")
            print(f"    - {vm}: {ip_hint}")
        print(
            "    Reverse NAT (host→guest): 1022→sensor-vm:22, 2022→victim-linux:22, "
            "3389→windows-victim:3389, 6080→noVNC/websockify (no new ports)."
        )

    print("")
    print("--- Telemetry (operator reference; no auto verdict) ---")
    exp_items, exp_src = _resolve_expected_telemetry_for_status(scenario, xdr_root, cfg)
    print(f"expected_telemetry (source: {exp_src})")
    if exp_items:
        print(f"  item count: {len(exp_items)}")
        for line in exp_items:
            print(f"  - {line}")
    else:
        print("  (no items)")
    print("  Full checklist: `lab scenario telemetry last` or `lab scenario telemetry <scenario_id>`")
    print("  Reserved auto-correlation: `lab scenario telemetry verify` (placeholder; see docs).")
    print("")
    print("Telemetry review metadata:")
    trs = str(scenario.get("telemetry_review_status") or "not_set").strip() or "not_set"
    print(f"  telemetry_review_status: {trs}")
    notes = scenario.get("telemetry_review_notes")
    if isinstance(notes, str) and notes.strip():
        print(f"  telemetry_review_notes: {notes.strip()}")
    else:
        print("  telemetry_review_notes: (empty — you may add operator notes in scenario.json)")
    print("  Suggested follow-up:")
    print("    - `lab mirror verify` / sensor PCAP and NDR for checklist-style coverage")
    print("    - Cross-check `logs/caldera-orchestration.jsonl` with CALDERA UI operation logs")

    print("")
    print("--- CALDERA server & Sandcat agents ---")
    print(
        "Agent matrix (api/agents + agent_vm_map): "
        + (
            ", ".join(f"{k}={'connected' if v else 'disconnected'}" for k, v in agents.items())
            or "-"
        )
    )
    print("  Detail: `lab scenario agent status`")
    print("")
    print("CALDERA operation block:")
    print(f"  operation_name: {cal.get('operation_name') or caldera.get('active_caldera_operation_name') or '-'}")
    print(f"  operation_id: {cal.get('operation_id') or caldera.get('active_caldera_operation_id') or '-'}")
    print(f"  adversary_id: {cal.get('adversary_id') or '-'}")
    print(f"  server_reported_state: {cal.get('server_reported_state') or '-'}")
    print(f"  http_reachable: {'yes' if caldera.get('http_reachable') else 'no'}  base_url: {caldera.get('base_url', '-')}")
    if los:
        print(
            f"  last_operation_summary (one line): phase={los.get('phase')!s}  "
            f"caldera_operation_id={los.get('caldera_operation_id') or '-'}  "
            f"operation_name={los.get('operation_name') or '-'}"
        )

    print("")
    print("--- Snapshots & rollback labels ---")
    snap = scenario.get("snapshot_before")
    snapr = scenario.get("snapshot_before_result")
    snapnm = scenario.get("snapshot_before_name")
    snapnm_s = str(snapnm).strip() if snapnm else ""
    st = str(scenario.get("status") or "")
    print(f"Pre-run snapshot requested (snapshot_before): {'yes' if snap else 'no'}")
    res_disp = snapr if snapr is not None else "-"
    if snapr == "dry_run_skipped":
        res_disp = "dry_run_skipped (nothing created)"
    elif snapr == "skipped":
        res_disp = "skipped (not requested)"
    print(f"Snapshot create result (snapshot_before_result): {res_disp}")
    print(f"Recorded snapshot name (snapshot_before_name): {snapnm_s or '-'}")
    if scenario_snapshot_applied(snapr) and snapnm_s:
        if st == "running":
            print("Revert recommended: no (scenario still running — consider manual revert after `scenario stop`)")
        else:
            print("Revert recommended: yes (no automatic revert — review alongside CALDERA/cleanup guidance below)")
    elif scenario_snapshot_applied(snapr) and not snapnm_s:
        print("Revert recommended: conditional (snapshot applied but name missing — check `lab snapshot list`)")
    else:
        print("Revert recommended: no (no pre-run snapshot applied or snapshot failed)")
    rr_json = scenario.get("recommended_revert")
    if isinstance(rr_json, str) and rr_json.strip():
        print(f"scenario.json recommended_revert: {rr_json.strip()}")
    crb = scenario.get("cleanup_recommended")
    if isinstance(crb, bool):
        print(
            f"cleanup_recommended (recorded hint): {'yes' if crb else 'no'} "
            "(whether extra checks for guest Sandcat/ability residue or CALDERA operations are advised)"
        )
    print(
        "Note: runtime/state/snapshots.json is the batch catalog; "
        "names may match scenario.json snapshot_before_name (expected)."
    )
    print("")
    print("  snapshots.json catalog (aggregate):")
    if (stated_p / "snapshots.json").is_file() and isinstance(snap_doc.get("per_vm"), dict) and snap_doc.get("per_vm"):
        print(f"    updated_utc: {snap_doc.get('updated_utc') or '-'}")
        for vm, row in sorted(snap_doc["per_vm"].items()):
            if isinstance(row, dict):
                print(
                    f"    - {vm}: domain_defined={row.get('domain_defined')} "
                    f"snapshot_count={row.get('snapshot_count')}"
                )
    else:
        print("    (file missing or empty per_vm — refresh via vm-manager snapshot flows)")

    print("")
    print("--- Lab infrastructure state (mirror + NAT) ---")
    print("mirror.json:")
    if (stated_p / "mirror.json").is_file():
        print(
            f"  consistent={mir_doc.get('consistent')}  mirror_exists={mir_doc.get('mirror_exists')}  "
            f"sensor_vm={mir_doc.get('sensor_vm')!r}"
        )
    else:
        print("  (missing — run `xdr-lab-vm-manager.sh mirror status` or refresh if needed)")
    print("nat.json:")
    if (stated_p / "nat.json").is_file():
        print(
            f"  consistent={nat_doc.get('consistent')}  iptables_readable={nat_doc.get('iptables_readable')}  "
            f"ts={nat_doc.get('ts') or '-'}"
        )
    else:
        print("  (missing — run `nat status` / `nat verify` on the host)")

    print("")
    print("--- Timing ---")
    print(f"  started_at: {scenario.get('started_at') or scenario.get('started_utc') or '-'}")
    print(f"  stopped_at: {scenario.get('stopped_at') or scenario.get('stopped_utc') or '-'}")
    cur_dur = operation_duration_seconds_between(
        scenario.get("started_at") or scenario.get("started_utc"),
        scenario.get("stopped_at") or scenario.get("stopped_utc"),
    )
    if cur_dur is not None:
        print(f"  duration_seconds (from current record): {round(cur_dur, 3)}")

    if los:
        print("")
        print("--- last_operation_summary (scenario.json) ---")
        for k in (
            "phase",
            "run_id",
            "scenario_id",
            "operation_name",
            "caldera_operation_id",
            "started_at",
            "stopped_at",
            "operation_duration_seconds",
            "snapshot_before_applied",
            "snapshot_before_name",
            "caldera_server_reported_state",
            "caldera_operation_remaining",
        ):
            if k in los and los.get(k) is not None:
                print(f"  {k}: {los.get(k)}")

    print("")
    print("--- Cleanup scope ---")
    print(f"  {scenario.get('cleanup_scope_note', '')}")
    if last_stop:
        print("")
        print("Last scenario stop:")
        for k in sorted(last_stop.keys()):
            print(f"  {k}: {last_stop.get(k)}")
    if hist:
        print("")
        print("Last completed run (last_history):")
        for k in (
            "scenario_id",
            "display_name",
            "scenario_name",
            "status",
            "dry_run",
            "started_at",
            "stopped_at",
            "run_id",
            "target_vms",
            "snapshot_before",
            "snapshot_before_result",
            "snapshot_before_name",
            "operation_duration_seconds",
        ):
            if k in hist:
                print(f"  {k}: {hist.get(k)}")
        et_hist = hist.get("expected_telemetry")
        if et_hist not in (None, "", []):
            print("  expected_telemetry:")
            for line in _expected_telemetry_as_str_list(et_hist):
                print(f"    - {line}")
        hcal = hist.get("caldera")
        if isinstance(hcal, dict):
            print(f"  caldera.operation_id: {hcal.get('operation_id')}")
            print(f"  caldera.operation_name: {hcal.get('operation_name')}")

    if scenario.get("last_error"):
        print("")
        print("--- last_error ---")
        print(f"  {scenario.get('last_error')}")
    if hints:
        print("")
        print("--- remediation_hints (scenario.json) ---")
        for h in hints:
            if isinstance(h, dict):
                print(f"  - ({h.get('code')}) {h.get('message')}")
                print(f"    → {h.get('action')}")

    if triage:
        print("")
        print("--- Troubleshooting hints (operator; heuristic) ---")
        for line in triage:
            print(f"  - {line}")

    print_post_run_operator_review_human(scenario, caldera, stated_p, cfg)
    print("")
    print("--- Next operator actions ---")
    for line in next_operator_actions_human(scenario):
        print(f"  - {line}")


def stellar_sensor_artifacts_present(xdr_root: Path) -> bool:
    sensor_dir = xdr_root / "images" / "sensor" / "6.2.0"
    script_name = "virt_deploy_modular_ds.sh"
    qcow2_name = "aella-modular-ds-6.2.0.qcow2"
    cfg_path = xdr_root / "config" / "lab-vms.json"
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        sensor = (data.get("vms") or {}).get("sensor-vm") or {}
        cache = str(sensor.get("sensor_cache_dir") or "")
        if cache:
            sensor_dir = Path(cache) if Path(cache).is_absolute() else xdr_root / cache
        script_name = str(sensor.get("virt_deploy_script_name") or script_name)
        qcow2_name = str(sensor.get("qcow2_name") or Path(str(sensor.get("image_url") or qcow2_name)).name)
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return (sensor_dir / script_name).is_file() and (sensor_dir / qcow2_name).is_file()


def cmd_run(
    xdr_root: Path,
    stated: Path,
    cfg: dict[str, Any],
    scenario_name: str,
    snapshot_before: bool,
    log_path: Path | None,
    *,
    cli_scenario_dry: bool = False,
) -> int:
    run_id = str(uuid.uuid4())
    reg, pack_warns = build_scenario_registry(xdr_root, cfg)
    for w in pack_warns:
        print(f"[warn] {w}", file=sys.stderr)
    if scenario_name not in reg:
        avail = ", ".join(sorted(reg.keys()))
        print(
            f"Unknown scenario {scenario_name!r}.\n"
            f"Available scenarios: {avail}\n"
            "Use `scenario list` for the table, and check scenarios/·config/scenarios/ packs and "
            "config/caldera-lab.json::scenarios definitions.",
            file=sys.stderr,
        )
        return 2
    rs = reg[scenario_name]
    target_vms = rs.target_vms if rs.target_vms else agent_vm_roles(cfg)
    group = rs.group
    planner = rs.planner
    is_dry = effective_scenario_dry(cli_scenario_dry)
    adversary_id: Any = rs.adversary_id
    if adversary_id in (None, "", []):
        msg = (
            f"Scenario {scenario_name!r} has no valid adversary_id. "
            "Set caldera.adversary_id in the scenario pack or the same key as a fallback in caldera-lab.json "
            "to a CALDERA Adversary UUID."
        )
        if not is_dry:
            print(msg, file=sys.stderr)
            t = utc_now()
            last_hist = {
                "run_id": run_id,
                "scenario_name": scenario_name,
                "started_at": t,
                "stopped_at": t,
                "status": "blocked",
                "dry_run": False,
                "target_vms": target_vms,
                "snapshot_before": snapshot_before,
                "snapshot_before_name": None,
                "snapshot_before_result": "skipped" if not snapshot_before else None,
                "caldera": {
                    "operation_name": None,
                    "operation_id": None,
                    "adversary_id": None,
                    "group": group,
                    "planner": planner,
                    "server_reported_state": None,
                },
                **_telemetry_snapshot_from_pack(rs),
            }
            attach_last_history_timing(last_hist)
            refresh_state(
                xdr_root,
                stated,
                cfg,
                merge_scenario={
                    "run_id": run_id,
                    "scenario_name": scenario_name,
                    "current_operation": scenario_name,
                    "status": "blocked",
                    "started_utc": t,
                    "stopped_utc": t,
                    "dry_run": False,
                    "target_vms": target_vms,
                    "snapshot_before": snapshot_before,
                    "snapshot_before_name": None,
                    "snapshot_before_result": "skipped" if not snapshot_before else None,
                    "last_error": msg,
                    "remediation_hints": [
                        {
                            "code": "missing_adversary_id",
                            "message": msg,
                            "action": "Set caldera.adversary_id in scenarios/<id>.json or in caldera-lab.json.",
                        }
                    ],
                    "caldera": last_hist["caldera"],
                    "last_history": last_hist,
                    "last_live_run": None,
                },
                log_path=log_path,
            )
            if log_path:
                log_jsonl(
                    log_path,
                    "scenario_operation_failed",
                    scenario=scenario_name,
                    run_id=run_id,
                    error="missing_adversary_id",
                    target_vms=target_vms,
                    snapshot_before=snapshot_before,
                )
                log_jsonl(
                    log_path,
                    "scenario_live_run_failed",
                    scenario=scenario_name,
                    run_id=run_id,
                    phase="missing_adversary_id",
                    error="missing_adversary_id",
                )
            return 1
        adversary_id = "DRY-RUN-PLACEHOLDER"

    op_name = format_scenario_operation_name(scenario_name)
    snap_preview_nm = proposed_snapshot_before_name() if snapshot_before else None

    if log_path:
        log_scenario_preflight_jsonl(
            log_path,
            event="scenario_preflight_started",
            scenario_name=scenario_name,
            run_id=run_id,
            dry_run=is_dry,
            snapshot_before=snapshot_before,
            target_vms=target_vms,
            scenario_id=rs.scenario_id,
        )

    pf = collect_scenario_run_preflight(
        xdr_root,
        stated,
        cfg,
        scenario_name=scenario_name,
        run_id=run_id,
        rs=rs,
        target_vms=target_vms,
        snapshot_before=snapshot_before,
        is_dry=is_dry,
        log_path=log_path,
    )
    warns_raw = pf.get("warnings") if isinstance(pf.get("warnings"), list) else []
    blocks_raw = pf.get("blocking") if isinstance(pf.get("blocking"), list) else []
    for w in warns_raw:
        if isinstance(w, dict) and log_path:
            log_jsonl(
                log_path,
                "scenario_preflight_warning",
                scenario=scenario_name,
                run_id=run_id,
                code=str(w.get("code") or ""),
                message=str(w.get("message") or ""),
            )
    br = pf.get("bootstrap_report")
    br_ok = bool(br.get("ok")) if isinstance(br, dict) else None
    gate_raw = (
        pf.get("operator_live_gate_failures")
        if isinstance(pf.get("operator_live_gate_failures"), list)
        else []
    )
    if log_path:
        log_jsonl(
            log_path,
            "scenario_preflight_completed",
            scenario=scenario_name,
            run_id=run_id,
            dry_run=is_dry,
            snapshot_before=snapshot_before,
            warning_count=len(warns_raw),
            blocking_count=len(blocks_raw),
            live_gate_failure_count=len(gate_raw),
            blocking_codes=[str(b.get("code") or "") for b in blocks_raw if isinstance(b, dict)],
            live_gate_codes=[str(b.get("code") or "") for b in gate_raw if isinstance(b, dict)],
            bootstrap_ok=br_ok,
        )

    blocking_live = bool(blocks_raw) and not is_dry
    if blocking_live:
        first = blocks_raw[0] if blocks_raw and isinstance(blocks_raw[0], dict) else {}
        fcode = str(first.get("code") or "preflight_blocked")
        fmsg = str(first.get("message") or "preflight blocked")
        if log_path:
            log_jsonl(
                log_path,
                "scenario_preflight_failed",
                scenario=scenario_name,
                run_id=run_id,
                reason=fcode,
                messages=[str(b.get("message") or "") for b in blocks_raw if isinstance(b, dict)],
            )
            log_jsonl(
                log_path,
                "scenario_live_run_failed",
                scenario=scenario_name,
                run_id=run_id,
                phase="preflight_blocked",
                reason=fcode,
                dry_run=False,
            )
        print("", file=sys.stderr)
        print("[failure] scenario run preflight — aborting non-dry-run execution.", file=sys.stderr)
        for b in blocks_raw:
            if isinstance(b, dict):
                print(f"  [{b.get('code')}] {b.get('message')}", file=sys.stderr)
        if any(
            isinstance(b, dict)
            and str(b.get("code") or "")
            in ("caldera_api_not_authenticated", "api_key_missing", "caldera_unreachable")
            for b in blocks_raw
        ):
            log_caldera_auth_journal()
        print_scenario_run_preflight_stdout(
            pf,
            operation_name=op_name,
            adversary_id=adversary_id,
            group=group,
            planner=planner,
            target_vms=target_vms,
            snapshot_before=snapshot_before,
            snapshot_name=snap_preview_nm,
            rs=rs,
            is_dry=False,
        )
        t = utc_now()
        last_hist = {
            "run_id": run_id,
            "scenario_name": scenario_name,
            "started_at": t,
            "stopped_at": t,
            "status": "blocked",
            "dry_run": False,
            "target_vms": target_vms,
            "snapshot_before": snapshot_before,
            "snapshot_before_name": None,
            "snapshot_before_result": "skipped" if not snapshot_before else None,
            "caldera": {
                "operation_name": None,
                "operation_id": None,
                "adversary_id": str(adversary_id) if adversary_id else None,
                "group": group,
                "planner": planner,
                "server_reported_state": None,
            },
            **_telemetry_snapshot_from_pack(rs),
        }
        attach_last_history_timing(last_hist)
        refresh_state(
            xdr_root,
            stated,
            cfg,
            merge_scenario={
                "run_id": run_id,
                "scenario_name": scenario_name,
                "current_operation": scenario_name,
                "status": "blocked",
                "started_utc": t,
                "stopped_utc": t,
                "dry_run": False,
                "target_vms": target_vms,
                "snapshot_before": snapshot_before,
                "snapshot_before_name": None,
                "snapshot_before_result": "skipped" if not snapshot_before else None,
                "last_error": f"preflight_{fcode}",
                "remediation_hints": [
                    {
                        "code": fcode,
                        "message": fmsg,
                        "action": "Run `lab scenario bootstrap validate` and check API key, base_url, and snapshot scripts.",
                    }
                ],
                "caldera": last_hist["caldera"],
                "last_history": last_hist,
                "last_live_run": None,
            },
            log_path=log_path,
        )
        return 2

    if warns_raw and not is_dry:
        print("", file=sys.stderr)
        print("=== scenario run preflight warnings (execution continues) ===", file=sys.stderr)
        for w in warns_raw:
            if isinstance(w, dict):
                print(f"  [{w.get('code')}] {w.get('message')}", file=sys.stderr)

    if log_path:
        log_jsonl(
            log_path,
            "scenario_run_ready",
            scenario=scenario_name,
            run_id=run_id,
            dry_run=is_dry,
            snapshot_before=snapshot_before,
            preflight_warnings=len(warns_raw),
        )
    infrastructure_ready = not blocks_raw and not gate_raw
    ready_for_stellar = infrastructure_ready and stellar_sensor_artifacts_present(xdr_root)
    print(f"READY_FOR_STELLAR_SENSOR_SCENARIO={'true' if ready_for_stellar else 'false'}")
    print(f"READY_FOR_LIVE_SCENARIO={'true' if ready_for_stellar else 'false'}")

    if not is_dry:
        print_scenario_run_preflight_stdout(
            pf,
            operation_name=op_name,
            adversary_id=adversary_id,
            group=group,
            planner=planner,
            target_vms=target_vms,
            snapshot_before=snapshot_before,
            snapshot_name=snap_preview_nm,
            rs=rs,
            is_dry=False,
        )

    snap_name: str | None = None
    if snapshot_before:
        snap_name = proposed_snapshot_before_name()

    if not snapshot_before:
        snap_result = "skipped"
    elif is_dry:
        snap_result = "dry_run_skipped"
        if log_path:
            log_jsonl(
                log_path,
                "snapshot_before_requested",
                run_id=run_id,
                scenario=scenario_name,
                snapshot_name=snap_name,
                target_vms=target_vms,
                dry_run=True,
                note="orchestrator_dry_run_no_libvirt",
            )
    else:
        snap_result = None

    if snapshot_before and not is_dry:
        if not snap_name:
            snap_name = proposed_snapshot_before_name()
        rc, _err_tail = run_lab_snapshot_batch_create(
            xdr_root,
            log_path,
            snap_name,
            run_id=run_id,
            scenario_name=scenario_name,
            target_vms=target_vms,
            dry_run=False,
        )
        if rc != 0:
            fail_hints = build_snapshot_before_failure_hints(snap_name)
            print("snapshot create failed; aborting scenario run", file=sys.stderr)
            print("", file=sys.stderr)
            print("=== remediation (snapshot-before) ===", file=sys.stderr)
            for h in fail_hints:
                print(f"  [{h['code']}] {h['message']}", file=sys.stderr)
                print(f"      → {h['action']}", file=sys.stderr)
            t = utc_now()
            last_hist = {
                "run_id": run_id,
                "scenario_name": scenario_name,
                "started_at": t,
                "stopped_at": t,
                "status": "failed",
                "dry_run": False,
                "target_vms": target_vms,
                "snapshot_before": True,
                "snapshot_before_name": snap_name,
                "snapshot_before_result": "failed",
                "caldera": {
                    "operation_name": None,
                    "operation_id": None,
                    "adversary_id": str(adversary_id) if adversary_id else None,
                    "group": group,
                    "planner": planner,
                    "server_reported_state": None,
                },
                **_telemetry_snapshot_from_pack(rs),
            }
            attach_last_history_timing(last_hist)
            refresh_state(
                xdr_root,
                stated,
                cfg,
                merge_scenario={
                    "run_id": run_id,
                    "scenario_name": scenario_name,
                    "current_operation": scenario_name,
                    "status": "failed",
                    "started_utc": t,
                    "stopped_utc": t,
                    "dry_run": False,
                    "target_vms": target_vms,
                    "snapshot_before": True,
                    "snapshot_before_name": snap_name,
                    "snapshot_before_result": "failed",
                    "last_error": "snapshot_before_failed",
                    "remediation_hints": fail_hints,
                    "caldera": last_hist["caldera"],
                    "last_history": last_hist,
                    "last_live_run": None,
                },
                log_path=log_path,
            )
            if log_path:
                log_jsonl(
                    log_path,
                    "scenario_operation_failed",
                    scenario=scenario_name,
                    run_id=run_id,
                    error="snapshot_before_failed",
                    target_vms=target_vms,
                    snapshot_before=True,
                    snapshot_name=snap_name,
                )
                log_jsonl(
                    log_path,
                    "scenario_live_run_failed",
                    scenario=scenario_name,
                    run_id=run_id,
                    phase="snapshot_before",
                    error="snapshot_before_failed",
                    snapshot_name=snap_name,
                )
            return rc
        snap_result = "applied"

    api_key = resolve_api_key(cfg)
    base_url = str(cfg.get("base_url") or "http://127.0.0.1:8888")
    client = CalderaClient(base_url, api_key)
    started = utc_now()

    merge_s: dict[str, Any] = {
        "run_id": run_id,
        "scenario_name": scenario_name,
        "current_operation": scenario_name,
        "status": "starting",
        "started_utc": started,
        "stopped_utc": "",
        "stopped_at": "",
        "dry_run": is_dry,
        "target_vms": target_vms,
        "snapshot_before": snapshot_before,
        "snapshot_before_name": snap_name if snapshot_before else None,
        "snapshot_before_result": snap_result,
        "last_error": None,
        "remediation_hints": [],
        "caldera": {
            "operation_name": op_name,
            "operation_id": None,
            "adversary_id": str(adversary_id),
            "group": group,
            "planner": planner,
            "server_reported_state": None,
        },
    }
    merge_c: dict[str, Any] = {
        "active_caldera_operation_id": None,
        "active_caldera_operation_name": op_name,
    }
    refresh_state(xdr_root, stated, cfg, merge_scenario=merge_s, merge_caldera=merge_c, log_path=log_path)

    if not is_dry and log_path:
        log_jsonl(
            log_path,
            "scenario_live_run_started",
            scenario=scenario_name,
            run_id=run_id,
            dry_run=False,
            started_at=started,
            target_vms=target_vms,
            snapshot_before=snapshot_before,
            snapshot_before_result=snap_result,
            preflight_summary=compact_preflight_summary_for_record(pf),
            operation_name_planned=op_name,
        )

    if is_dry:
        if log_path:
            log_jsonl(
                log_path,
                "scenario_operation_started",
                scenario=scenario_name,
                run_id=run_id,
                operation_name=op_name,
                dry_run=True,
                target_vms=target_vms,
                adversary_id=str(adversary_id),
                snapshot_before=snapshot_before,
                snapshot_before_result=snap_result,
                snapshot_before_name=snap_name if snapshot_before else None,
            )
            log_jsonl(
                log_path,
                "scenario_operation_completed",
                scenario=scenario_name,
                run_id=run_id,
                operation_name=op_name,
                dry_run=True,
                note="no_caldera_operation_created",
                target_vms=target_vms,
                snapshot_before_result=snap_result,
                snapshot_before_name=snap_name if snapshot_before else None,
            )
        stopped = utc_now()
        merge_s["status"] = "idle"
        merge_s["stopped_utc"] = stopped
        merge_s["current_operation"] = ""
        merge_s["scenario_name"] = ""
        lh_dry = {
            "run_id": run_id,
            "scenario_name": scenario_name,
            "started_at": started,
            "stopped_at": stopped,
            "status": "dry_run",
            "dry_run": True,
            "target_vms": target_vms,
            "snapshot_before": snapshot_before,
            "snapshot_before_name": snap_name if snapshot_before else None,
            "snapshot_before_result": snap_result,
            "caldera": dict(merge_s["caldera"]),
            **_telemetry_snapshot_from_pack(rs),
        }
        attach_last_history_timing(lh_dry)
        merge_s["last_history"] = lh_dry
        merge_c["active_caldera_operation_id"] = None
        merge_c["active_caldera_operation_name"] = None
        refresh_state(xdr_root, stated, cfg, merge_scenario=merge_s, merge_caldera=merge_c, log_path=log_path)
        base_url = str(cfg.get("base_url") or "http://127.0.0.1:8888")
        pack_out: dict[str, Any] = {
            "scenario_id": rs.scenario_id,
            "display_name": rs.display_name,
            "description": rs.description,
            "target_vms": target_vms,
            "caldera": {
                "adversary_id": rs.adversary_id,
                "group": group,
                "planner": planner,
            },
            "expected_telemetry": rs.expected_telemetry,
            "safety_notes": rs.safety_notes,
            "cleanup_notes": rs.cleanup_notes,
            "source": rs.source,
            "pack_path": str(rs.path) if rs.path else None,
        }
        plan = {
            "note": "Conceptual operation-create payload that would be sent appliance→CALDERA on a live run",
            "method": "PUT",
            "url": urljoin(base_url.rstrip("/") + "/", "api/rest"),
            "body": {
                "index": "operations",
                "name": op_name,
                "adversary_id": str(adversary_id),
                "group": group,
                "planner": planner,
                "autonomous": 1,
                "state": "running",
            },
        }
        print_scenario_run_preflight_stdout(
            pf,
            operation_name=op_name,
            adversary_id=adversary_id,
            group=group,
            planner=planner,
            target_vms=target_vms,
            snapshot_before=snapshot_before,
            snapshot_name=snap_name if snapshot_before else None,
            rs=rs,
            is_dry=True,
        )
        print_scenario_dry_run_checklist_summary(rs, target_vms)
        print("=== DRY-RUN: selected scenario pack ===")
        print(json.dumps(pack_out, ensure_ascii=False, indent=2))
        print("=== DRY-RUN: CALDERA operation plan ===")
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        print(
            f"(summary) operation name={op_name!r} adversary_id={adversary_id!r} — "
            "no live PUT or snapshot creation was performed."
        )
        print_dry_run_telemetry_summary(rs, target_vms)
        print_dry_run_runtime_preview(
            rs=rs,
            target_vms=target_vms,
            snapshot_before=snapshot_before,
            snap_name=snap_name if snapshot_before else None,
            op_name=op_name,
            adversary_id=adversary_id,
            pf=pf,
        )
        return 0

    payload: dict[str, Any] = {
        "index": "operations",
        "name": op_name,
        "adversary_id": str(adversary_id),
        "group": group,
        "planner": planner,
        "autonomous": 1,
        "state": "running",
    }
    if log_path:
        log_jsonl(
            log_path,
            "scenario_operation_started",
            scenario=scenario_name,
            run_id=run_id,
            operation_name=op_name,
            adversary_id=str(adversary_id),
            dry_run=False,
            target_vms=target_vms,
            snapshot_before=snapshot_before,
            snapshot_before_result=snap_result,
            snapshot_before_name=snap_name if snapshot_before else None,
        )
    code, resp, err = client.rest_put(payload, log_path)
    if code not in (200, 201) or resp is None:
        msg = err or f"unexpected_http_{code}"
        if log_path:
            log_jsonl(
                log_path,
                "scenario_operation_failed",
                scenario=scenario_name,
                run_id=run_id,
                operation_name=op_name,
                error=msg,
                target_vms=target_vms,
            )
            log_jsonl(
                log_path,
                "scenario_live_run_failed",
                scenario=scenario_name,
                run_id=run_id,
                phase="operation_create",
                operation_name=op_name,
                error=msg,
                http_code=code,
            )
        stopped = utc_now()
        merge_s["status"] = "failed"
        merge_s["stopped_utc"] = stopped
        merge_s["last_error"] = msg
        merge_s["last_live_run"] = None
        lh_fail = {
            "run_id": run_id,
            "scenario_name": scenario_name,
            "started_at": started,
            "stopped_at": stopped,
            "status": "failed",
            "dry_run": False,
            "target_vms": target_vms,
            "snapshot_before": snapshot_before,
            "snapshot_before_name": snap_name if snapshot_before else None,
            "snapshot_before_result": snap_result,
            "caldera": dict(merge_s["caldera"]),
            **_telemetry_snapshot_from_pack(rs),
        }
        attach_last_history_timing(lh_fail)
        merge_s["last_history"] = lh_fail
        merge_s["remediation_hints"] = build_stop_remediation_hints(
            stop_http_failed=True,
            operation_still_running=False,
            snapshot_before_applied=scenario_snapshot_applied(snap_result),
            caldera_unreachable=not probe_http(base_url, api_key, log_path),
            snapshot_before_name=str(merge_s.get("snapshot_before_name") or "").strip() or None,
        )
        refresh_state(xdr_root, stated, cfg, merge_scenario=merge_s, merge_caldera=merge_c, log_path=log_path)
        print(f"CALDERA operation create failed: {msg}", file=sys.stderr)
        return 1

    op_id = extract_operation_id(resp)
    merge_s["status"] = "running"
    merge_c["active_caldera_operation_id"] = op_id
    merge_c["active_caldera_operation_name"] = op_name
    merge_s["caldera"] = {
        "operation_name": op_name,
        "operation_id": op_id,
        "adversary_id": str(adversary_id),
        "group": group,
        "planner": planner,
        "server_reported_state": "running",
    }
    snap_ap_run = scenario_snapshot_applied(snap_result)
    rec_rev_cmd: str | None = None
    if snap_ap_run and snap_name:
        rec_rev_cmd = f"aella_cli lab snapshot revert {snap_name}"
    merge_s["last_operation_summary"] = {
        "phase": "operation_active",
        "run_id": run_id,
        "scenario_id": scenario_name,
        "operation_name": op_name,
        "caldera_operation_id": op_id,
        "started_at": started,
        "snapshot_before_applied": snap_ap_run,
        "snapshot_before_name": snap_name if snapshot_before else None,
    }
    merge_s["recommended_revert"] = rec_rev_cmd
    merge_s["cleanup_recommended"] = True
    merge_s["telemetry_review_status"] = "pending_operator_review"
    submitted_ts = utc_now()
    merge_s["last_live_run"] = build_last_live_run_record_on_submit(
        run_id=run_id,
        scenario_name=scenario_name,
        rs=rs,
        target_vms=target_vms,
        started_at=started,
        submitted_at=submitted_ts,
        op_name=op_name,
        op_id=op_id,
        server_reported_state="running",
        snapshot_before=snapshot_before,
        snap_name=snap_name if snapshot_before else None,
        snap_result=snap_result,
        pf=pf,
    )
    if log_path:
        log_jsonl(
            log_path,
            "scenario_operation_completed",
            scenario=scenario_name,
            run_id=run_id,
            operation_name=op_name,
            caldera_operation_id=op_id,
            note="operation_created",
            target_vms=target_vms,
            snapshot_before_result=snap_result,
            snapshot_before_name=snap_name if snapshot_before else None,
            last_operation_phase="operation_active",
            recommended_revert_cli=rec_rev_cmd,
        )
        log_jsonl(
            log_path,
            "scenario_live_run_submitted",
            scenario=scenario_name,
            run_id=run_id,
            caldera_operation_id=op_id,
            operation_name=op_name,
            submitted_at=submitted_ts,
            target_vms=target_vms,
            snapshot_before_result=snap_result,
            snapshot_before_name=snap_name if snapshot_before else None,
        )
        log_jsonl(
            log_path,
            "scenario_post_run_review_recommended",
            scenario=scenario_name,
            run_id=run_id,
            caldera_operation_id=op_id,
            telemetry_review_status="pending_operator_review",
            note="manual_telemetry_and_ui_review_required",
        )
    refresh_state(xdr_root, stated, cfg, merge_scenario=merge_s, merge_caldera=merge_c, log_path=log_path)
    print(json.dumps({"operation_name": op_name, "caldera_operation_id": op_id, "response": resp}, indent=2))
    return 0


def print_scenario_stop_snapshot_advisory(snapshot_applied: bool, snapshot_name: str | None) -> None:
    """stderr — `scenario stop` never performs libvirt snapshot revert."""
    if not snapshot_applied:
        return
    nm = str(snapshot_name or "").strip()
    print("", file=sys.stderr)
    print("=== Note: snapshots / no automatic revert ===", file=sys.stderr)
    if nm:
        print(
            "`scenario stop` does not automatically perform a libvirt snapshot revert.\n"
            f"Pre-run snapshot name: {nm}\n"
            "Example manual revert:\n"
            f"  xdr-lab-vm-manager.sh snapshot revert {nm}",
            file=sys.stderr,
        )
        print("  (equivalent) use `aella_cli lab snapshot revert` with the same name.", file=sys.stderr)
    else:
        print(
            "`scenario stop` does not automatically perform a snapshot revert.\n"
            "A pre-run snapshot was recorded as applied but scenario.json has no name. "
            "Check `lab snapshot list` or runtime/state/snapshots.json.",
            file=sys.stderr,
        )


def cmd_stop(xdr_root: Path, stated: Path, cfg: dict[str, Any], log_path: Path | None) -> int:
    scenario_path = stated / "scenario.json"
    scenario_disk = load_json(scenario_path, default_scenario_doc())
    if not isinstance(scenario_disk, dict):
        scenario_disk = default_scenario_doc()
    run_id = str(scenario_disk.get("run_id") or "").strip()
    snap_nm = str(scenario_disk.get("snapshot_before_name") or "").strip()
    snap_applied = scenario_snapshot_applied(scenario_disk.get("snapshot_before_result"))

    caldera_path = stated / "caldera.json"
    caldera_doc = load_json(caldera_path, default_caldera_doc(cfg))
    if not isinstance(caldera_doc, dict):
        caldera_doc = default_caldera_doc(cfg)
    op_id = caldera_doc.get("active_caldera_operation_id")
    op_name = caldera_doc.get("active_caldera_operation_name")

    api_key = resolve_api_key(cfg)
    base_url = str(cfg.get("base_url") or "http://127.0.0.1:8888")
    client = CalderaClient(base_url, api_key)
    reachable = bool(caldera_doc.get("http_reachable")) and probe_http(base_url, api_key, log_path)

    def _terminal_state(s: str | None) -> bool:
        if not s:
            return True
        t = str(s).lower()
        return t in ("finished", "complete", "completed")

    if dry_run():
        if log_path:
            log_jsonl(
                log_path,
                "scenario_operation_completed",
                action="stop",
                dry_run=True,
                run_id=run_id or None,
                caldera_operation_id=op_id,
                caldera_operation_name=op_name,
                cleanup={"scenario_stop": "skipped_dry_run", "result": "skipped"},
            )
        merge_cd = dict(caldera_doc)
        merge_cd["active_caldera_operation_id"] = None
        merge_cd["active_caldera_operation_name"] = None
        refresh_state(
            xdr_root,
            stated,
            cfg,
            merge_scenario={
                "status": "idle",
                "current_operation": "",
                "scenario_name": "",
                "dry_run": False,
                "stopped_utc": utc_now(),
                "caldera": {
                    "operation_name": None,
                    "operation_id": None,
                    "adversary_id": None,
                    "group": None,
                    "planner": None,
                    "server_reported_state": None,
                },
                "last_stop": {
                    "dry_run": True,
                    "stopped_at": utc_now(),
                    "caldera_operation_id": op_id,
                    "caldera_operation_name": op_name,
                    "cleanup": {
                        "scenario_stop": "caldera_operation_finish_post",
                        "result": "skipped",
                        "note": "XDR_LAB_DRY_RUN — no HTTP mutation",
                    },
                    "caldera_operation_remaining": bool(op_id) and not _terminal_state(
                        find_operation_row_by_id(client, str(op_id), log_path)[0] if reachable else None
                    ),
                    "orphaned_local_orchestrator_processes": False,
                },
            },
            merge_caldera=merge_cd,
            log_path=log_path,
        )
        print(f"DRY-RUN: would finish CALDERA operation id={op_id!r} name={op_name!r}")
        print("", file=sys.stderr)
        print("=== scenario stop (dry-run / stderr) ===", file=sys.stderr)
        print("  CALDERA operation finish POST was not performed (XDR_LAB_DRY_RUN).", file=sys.stderr)
        print(
            f"  telemetry_review_status is unchanged (current: {scenario_disk.get('telemetry_review_status')!r}).",
            file=sys.stderr,
        )
        print_scenario_stop_snapshot_advisory(snap_applied, snap_nm or None)
        return 0

    if not op_id:
        print("No active_caldera_operation_id in caldera.json — nothing to stop.", file=sys.stderr)
        noop_stopped = utc_now()
        refresh_state(
            xdr_root,
            stated,
            cfg,
            merge_scenario={
                "status": "idle",
                "stopped_utc": noop_stopped,
                "current_operation": "",
                "scenario_name": "",
                "last_stop": {
                    "stopped_at": noop_stopped,
                    "cleanup": {
                        "scenario_stop": "no_active_operation",
                        "result": "noop",
                        "note": "active_caldera_operation_id was empty",
                    },
                    "caldera_operation_remaining": False,
                    "orphaned_local_orchestrator_processes": False,
                    "stop_http_finish_ok": True,
                    "remaining_cleanup_hints": [
                        "No operation to finish — only confirm in the UI whether anything is orphaned.",
                    ],
                },
            },
            log_path=log_path,
        )
        print_scenario_stop_human_summary(
            stop_ok=True,
            stopped_at=noop_stopped,
            op_id=None,
            op_name=None,
            duration_sec=None,
            telemetry_review_status=preserve_telemetry_review_status(
                scenario_disk.get("telemetry_review_status")
            ),
            cleanup_hints=[
                "No active_caldera_operation_id — there was no CALDERA operation to stop.",
                "Confirm in the UI whether it was already stopped or cleaned up from another host.",
            ],
            snap_applied=snap_applied,
            snap_nm=snap_nm,
        )
        return 0

    pre_state, _pre_row = (
        find_operation_row_by_id(client, str(op_id), log_path) if reachable else (None, None)
    )
    op_raw = str(op_id).strip()
    op_kw: str | int = int(op_raw) if op_raw.isdigit() else op_raw

    post_body: dict[str, Any] = {"index": "operation", "op_id": op_kw, "state": "finished"}
    code, resp, err = client.rest_post(post_body, log_path)
    stopped = utc_now()

    if code not in (200, 201) or err:
        msg = err or f"unexpected_http_{code}"
        if log_path:
            log_jsonl(
                log_path,
                "scenario_operation_failed",
                action="stop",
                run_id=run_id or None,
                error=msg,
                caldera_operation_id=str(op_id),
                cleanup={"scenario_stop": "caldera_operation_finish_post", "result": "failed"},
            )
            log_jsonl(
                log_path,
                "scenario_live_run_failed",
                action="stop",
                run_id=run_id or None,
                phase="stop_finish_post",
                caldera_operation_id=str(op_id),
                error=msg,
                http_code=code,
            )
        post_state, _ = find_operation_row_by_id(client, str(op_id), log_path) if reachable else (None, None)
        still_running = bool(post_state and not _terminal_state(post_state))
        hints = build_stop_remediation_hints(
            stop_http_failed=True,
            operation_still_running=still_running,
            snapshot_before_applied=bool(snap_applied),
            caldera_unreachable=not reachable,
            snapshot_before_name=snap_nm or None,
        )
        refresh_state(
            xdr_root,
            stated,
            cfg,
            merge_scenario={
                "status": "failed",
                "stopped_utc": stopped,
                "last_error": msg,
                "remediation_hints": hints,
                "caldera": {
                    "server_reported_state": post_state,
                },
                "last_stop": {
                    "stopped_at": stopped,
                    "cleanup": {
                        "scenario_stop": "caldera_operation_finish_post",
                        "result": "failed",
                        "http_code": code,
                    },
                    "caldera_operation_remaining": still_running,
                    "caldera_server_reported_state": post_state,
                    "orphaned_local_orchestrator_processes": False,
                    "stop_http_finish_ok": False,
                    "telemetry_review_status_after": preserve_telemetry_review_status(
                        scenario_disk.get("telemetry_review_status")
                    ),
                    "remaining_cleanup_hints": [
                        "In the CALDERA UI manually finish the operation, then fix network/API key and retry `scenario stop`",
                        "Cross-check `scenario status --human` server_reported_state with the JSONL timeline",
                    ],
                },
            },
            log_path=log_path,
        )
        print(f"CALDERA operation stop failed: {msg}", file=sys.stderr)
        dur_fail = operation_duration_seconds_between(
            scenario_disk.get("started_at") or scenario_disk.get("started_utc"),
            stopped,
        )
        print_scenario_stop_human_summary(
            stop_ok=False,
            stopped_at=stopped,
            op_id=op_id,
            op_name=op_name,
            duration_sec=dur_fail,
            telemetry_review_status=preserve_telemetry_review_status(scenario_disk.get("telemetry_review_status")),
            cleanup_hints=[
                "stop POST failed — follow remediation codes in the hints block",
                "If needed, finish the same operation in the CALDERA UI",
            ],
            snap_applied=snap_applied,
            snap_nm=snap_nm,
        )
        print("", file=sys.stderr)
        print("=== remediation (scenario stop) ===", file=sys.stderr)
        for h in hints:
            print(f"  [{h['code']}] {h['message']}", file=sys.stderr)
            print(f"      → {h['action']}", file=sys.stderr)
        print_scenario_stop_snapshot_advisory(snap_applied, snap_nm or None)
        return 1

    post_state, _ = find_operation_row_by_id(client, str(op_id), log_path) if reachable else (None, None)
    still_running = bool(post_state and not _terminal_state(post_state))

    merge_c = dict(caldera_doc)
    merge_c["active_caldera_operation_id"] = None
    merge_c["active_caldera_operation_name"] = None

    cal_sub = scenario_disk.get("caldera") if isinstance(scenario_disk.get("caldera"), dict) else {}
    adv_keep = cal_sub.get("adversary_id")
    grp_keep = cal_sub.get("group")
    pln_keep = cal_sub.get("planner")

    last_hist = {
        "run_id": scenario_disk.get("run_id"),
        "scenario_name": scenario_disk.get("scenario_name") or scenario_disk.get("current_operation"),
        "started_at": scenario_disk.get("started_at") or scenario_disk.get("started_utc"),
        "stopped_at": stopped,
        "status": "stopped",
        "dry_run": bool(scenario_disk.get("dry_run")),
        "target_vms": list(scenario_disk.get("target_vms") or []),
        "snapshot_before": bool(scenario_disk.get("snapshot_before")),
        "snapshot_before_name": snap_nm or None,
        "snapshot_before_result": scenario_disk.get("snapshot_before_result"),
        "caldera": {
            "operation_name": op_name,
            "operation_id": str(op_id),
            "adversary_id": adv_keep,
            "group": grp_keep,
            "planner": pln_keep,
            "server_reported_state": post_state,
        },
    }
    sn_stop = str(last_hist.get("scenario_name") or "").strip()
    if sn_stop:
        reg_stop, _pw = build_scenario_registry(xdr_root, cfg)
        rs_stop = reg_stop.get(sn_stop)
        if rs_stop:
            last_hist.update(_telemetry_snapshot_from_pack(rs_stop))
    attach_last_history_timing(last_hist)
    dur_sec = last_hist.get("operation_duration_seconds")
    sid_done = str(last_hist.get("scenario_id") or last_hist.get("scenario_name") or "").strip()
    last_op_summary: dict[str, Any] = {
        "phase": "operation_stopped",
        "run_id": last_hist.get("run_id"),
        "scenario_id": sid_done or None,
        "caldera_operation_id": str(op_id),
        "operation_name": op_name,
        "started_at": last_hist.get("started_at"),
        "stopped_at": stopped,
        "operation_duration_seconds": dur_sec,
        "snapshot_before_applied": snap_applied,
        "snapshot_before_name": snap_nm or None,
        "caldera_server_reported_state": post_state,
        "caldera_operation_remaining": still_running,
    }
    rec_revert: str | None = None
    if snap_applied and snap_nm:
        rec_revert = f"aella_cli lab snapshot revert {snap_nm}"
    cleanup_rec = bool(snap_applied or still_running)
    hints_ok: list[dict[str, str]] = []
    if still_running:
        hints_ok = build_stop_remediation_hints(
            stop_http_failed=False,
            operation_still_running=True,
            snapshot_before_applied=bool(snap_applied),
            caldera_unreachable=not reachable,
            snapshot_before_name=snap_nm or None,
        )

    trs_next = preserve_telemetry_review_status(scenario_disk.get("telemetry_review_status"))
    llr_merged = merge_last_live_run_on_stop(
        scenario_disk.get("last_live_run"),
        run_id=str(scenario_disk.get("run_id") or ""),
        stopped_at=stopped,
        post_state=post_state,
        stop_http_ok=True,
    )
    cleanup_hints_post: list[str] = [
        "In the CALDERA UI, finalize operation, facts, and per-agent ability results",
        "Manually cross-check expected_telemetry with `lab scenario telemetry last` (no automatic verdict)",
    ]
    if still_running:
        cleanup_hints_post.append("If the server still reports a non-terminal state, check queues and agent responses in the UI.")
    if snap_applied:
        cleanup_hints_post.append(
            f"If needed, manual snapshot revert: `aella_cli lab snapshot revert {snap_nm}`"
            if snap_nm
            else "Use `lab snapshot list` to find the snapshot name, then consider revert"
        )
    cleanup_hints_post.append("Review whether removing Sandcat with `lab scenario agent remove` matches lab policy")

    last_stop_d: dict[str, Any] = {
        "stopped_at": stopped,
        "cleanup": {
            "scenario_stop": "caldera_operation_finish_post",
            "result": "ok",
            "server_reported_state_after_stop": post_state,
        },
        "caldera_operation_remaining": still_running,
        "orphaned_local_orchestrator_processes": False,
        "stop_http_finish_ok": True,
        "operation_wall_duration_seconds": dur_sec,
        "telemetry_review_status_after": trs_next,
        "remaining_cleanup_hints": cleanup_hints_post,
    }

    merge_scenario_ok: dict[str, Any] = {
        "status": "stopped",
        "stopped_utc": stopped,
        "current_operation": "",
        "scenario_name": "",
        "last_error": None,
        "caldera": {
            "operation_name": None,
            "operation_id": None,
            "adversary_id": adv_keep,
            "group": grp_keep,
            "planner": pln_keep,
            "server_reported_state": post_state,
        },
        "last_stop": last_stop_d,
        "last_history": last_hist,
        "remediation_hints": hints_ok,
        "last_operation_summary": last_op_summary,
        "recommended_revert": rec_revert,
        "cleanup_recommended": cleanup_rec,
        "telemetry_review_status": trs_next,
    }
    if llr_merged is not None:
        merge_scenario_ok["last_live_run"] = llr_merged

    if log_path:
        log_jsonl(
            log_path,
            "scenario_operation_completed",
            action="stop",
            run_id=run_id or None,
            caldera_operation_id=str(op_id),
            response_is=type(resp).__name__,
            cleanup={
                "scenario_stop": "caldera_operation_finish_post",
                "result": "ok",
                "server_reported_state_after_stop": post_state,
            },
            caldera_operation_remaining=still_running,
            operation_duration_seconds=dur_sec,
            snapshot_before_applied=snap_applied,
            recommended_revert_cli=rec_revert,
        )
        log_jsonl(
            log_path,
            "scenario_live_run_completed",
            run_id=run_id or None,
            caldera_operation_id=str(op_id),
            stopped_at=stopped,
            operation_duration_seconds=dur_sec,
            caldera_operation_remaining=still_running,
            telemetry_review_status=trs_next,
        )

    refresh_state(
        xdr_root,
        stated,
        cfg,
        merge_scenario=merge_scenario_ok,
        merge_caldera=merge_c,
        log_path=log_path,
    )
    print(json.dumps({"stopped": True, "caldera_operation_id": str(op_id), "raw": resp}, indent=2))
    print_scenario_stop_human_summary(
        stop_ok=True,
        stopped_at=stopped,
        op_id=op_id,
        op_name=op_name,
        duration_sec=float(dur_sec) if dur_sec is not None else None,
        telemetry_review_status=trs_next,
        cleanup_hints=cleanup_hints_post,
        snap_applied=snap_applied,
        snap_nm=snap_nm,
    )
    if still_running and hints_ok:
        print("", file=sys.stderr)
        print("=== remediation (post-stop poll) ===", file=sys.stderr)
        for h in hints_ok:
            print(f"  [{h['code']}] {h['message']}", file=sys.stderr)
            print(f"      → {h['action']}", file=sys.stderr)
    elif still_running:
        print("", file=sys.stderr)
        print(
            "WARN: CALDERA still does not report the operation in a terminal state. "
            "Check server_reported_state with `scenario status --human`.",
            file=sys.stderr,
        )
    print_scenario_stop_snapshot_advisory(snap_applied, snap_nm or None)
    return 0


def cmd_agent_status(
    cfg: dict[str, Any], stated: Path, log_path: Path | None, *, json_only: bool
) -> int:
    xdr_root = Path(stated.parent.parent)
    if json_only:
        _, _ = refresh_state(xdr_root, stated, cfg, log_path=log_path)
        scenario_path = stated / "scenario.json"
        doc = load_json(scenario_path, default_scenario_doc())
        print(json.dumps(doc.get("agents", {}), indent=2, ensure_ascii=False))
        return 0

    scenario_doc, caldera_doc = refresh_state(xdr_root, stated, cfg, log_path=log_path)

    base_url = str(caldera_doc.get("base_url") or cfg.get("base_url") or "")
    reachable = bool(caldera_doc.get("caldera_server_running"))
    matrix = caldera_doc.get("agent_matrix_last")
    if not isinstance(matrix, dict):
        matrix = scenario_doc.get("agents") if isinstance(scenario_doc.get("agents"), dict) else {}

    print("=== CALDERA lab — agent status (from runtime/state/caldera.json) ===")
    print(f"CALDERA URL: {base_url}")
    print(f"Server HTTP reachable: {'yes' if reachable else 'no'}  (last probe: {caldera_doc.get('last_probe_utc') or '-'})")
    op_id = str(caldera_doc.get("active_caldera_operation_id") or "").strip()
    op_name = str(caldera_doc.get("active_caldera_operation_name") or "").strip()
    scen_cal = scenario_doc.get("caldera") if isinstance(scenario_doc.get("caldera"), dict) else {}
    if not op_id:
        op_id = str(scen_cal.get("operation_id") or "").strip()
    if not op_name:
        op_name = str(scen_cal.get("operation_name") or "").strip()
    print(f"Active CALDERA operation_id: {op_id or '-'}  operation_name: {op_name or '-'}")
    print("  Quick summary: `lab runtime summary`  |  operation detail: `lab runtime operation`")
    if not reachable:
        print("  → remediation: cannot reach CALDERA server. Check base_url, firewall, and service state.")
    api_key = resolve_api_key(cfg)
    if not api_key.strip():
        print("API key: (missing)")
        print("  → remediation: CALDERA API key missing — set XDR_CALDERA_API_KEY, api_key_file, or api_key_env.")
    else:
        print("API key: (set)")

    print("")
    print("[Agents visible to CALDERA — lab roles]")
    roles = agent_vm_roles(cfg)
    for vm in roles:
        ok = bool(matrix.get(vm))
        line = "connected" if ok else "disconnected (CALDERA has not seen Sandcat for this VM yet)"
        print(f"  - {vm}: {line}")
        if reachable and not ok:
            print(
                "      → remediation: agent not seen by CALDERA — "
                f"run `scenario agent deploy`, wait briefly, and align agent_vm_map.host_substrings with real hostnames."
            )

    dep = caldera_doc.get("agent_deploy_last")
    if isinstance(dep, dict) and dep.get("utc"):
        print("")
        print("[Last agent deploy summary]")
        print(f"  time: {dep.get('utc')}")
        print(f"  dry_run: {dep.get('dry_run')}")
        ec = dep.get("exit_code")
        print(f"  exit_code: {ec if ec is not None else '(missing — legacy record)'}")
        fp = dep.get("fatal_preflight")
        if fp is None:
            print("  fatal_preflight: (missing — legacy record)")
        else:
            print(f"  fatal_preflight: {'yes' if fp else 'no'}")
        fr = dep.get("fatal_reason")
        if isinstance(fr, str) and fr.strip():
            print(f"  fatal_reason: {fr}")
        rows = dep.get("per_vm") if isinstance(dep.get("per_vm"), list) else dep.get("vms")
        for row in rows or []:
            if isinstance(row, dict):
                print(f"  - {row.get('vm')}: {row.get('status')} — {row.get('detail', '')}")

    sb = caldera_doc.get("server_bootstrap")
    if isinstance(sb, dict) and sb:
        print("")
        print("[CALDERA server bootstrap notes — caldera.json::server_bootstrap]")
        print(f"  bootstrap_install_status: {sb.get('bootstrap_install_status', '?')}")
        pls = sb.get("plugins")
        if isinstance(pls, list) and pls:
            n = min(len(pls), 6)
            shown = ", ".join(str(x) for x in pls[:n])
            extra = f" … +{len(pls) - n} more" if len(pls) > n else ""
            print(f"  plugins (config snapshot, first {n}): {shown}{extra}")
        if isinstance(sb.get("atomic_red_team"), dict) and sb.get("atomic_red_team"):
            print("  atomic_red_team: (object present — see caldera.json for keys)")

    return 0


def cmd_agent_verify(
    cfg: dict[str, Any], stated: Path, log_path: Path | None, *, json_only: bool
) -> int:
    xdr_root = Path(stated.parent.parent)
    scenario_doc, caldera_doc = refresh_state(xdr_root, stated, cfg, log_path=log_path)
    matrix = caldera_doc.get("agent_matrix_last")
    if not isinstance(matrix, dict):
        matrix = scenario_doc.get("agents") if isinstance(scenario_doc.get("agents"), dict) else {}
    roles = agent_vm_roles(cfg)
    disconnected = [vm for vm in roles if not bool(matrix.get(vm))]
    payload = {
        "result": "PASS" if not disconnected else "FAIL",
        "roles": roles,
        "connected": [vm for vm in roles if bool(matrix.get(vm))],
        "disconnected": disconnected,
        "matrix": {vm: bool(matrix.get(vm)) for vm in roles},
    }
    scenario_doc["agents"] = payload["matrix"]
    save_json_atomic(stated / "scenario.json", scenario_doc)
    if json_only:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("=== CALDERA lab — agent verify ===")
        for vm in roles:
            print(f"[{'PASS' if bool(matrix.get(vm)) else 'FAIL'}] {vm}")
        print(f"RESULT: {payload['result']}")
    return 0 if not disconnected else 1


def cmd_agent_deploy(
    xdr_root: Path,
    cfg: dict[str, Any],
    stated: Path,
    log_path: Path | None,
    *,
    cli_dry_run: bool,
) -> int:
    is_dry = deploy_effective_dry(cli_dry_run)
    lab = load_lab_vms_json(xdr_root)
    nat_doc = load_nat_state_doc(stated)
    base_url = str(cfg.get("base_url") or "http://127.0.0.1:8888")
    api_key = resolve_api_key(cfg)
    api_key_present = bool(api_key.strip())
    vm_rows: list[dict[str, Any]] = []
    deploy_report: dict[str, Any] = {
        "utc": utc_now(),
        "dry_run": is_dry,
    }
    rc_all = 0

    print("=== CALDERA lab — agent deploy flow ===")
    print("Targets: config/caldera-lab.json agents (sensor-vm, victim-linux, windows-victim)")
    print("1) Linux roles (sensor-vm, victim-linux): appliance→VM SSH, run bootstrap-linux.sh via bash on the guest")
    print("2) Windows (windows-victim): prefer SSH, then WinRM TCP per lab-vms.json external_nat_port_mapping;")
    print("   if only RDP is open, manual bootstrap guidance (no credential-less WinRM remote execution)")
    print("")

    if not api_key_present:
        if is_dry:
            print("[warn] CALDERA API key missing — dry-run continues with VM reachability checks and bootstrap file generation only.")
            print("  → remediation: set XDR_CALDERA_API_KEY or api_key_file before a real deploy.")
        else:
            print("[failure] CALDERA API key missing (preflight fatal — non-dry-run exits with code 2)")
            print("  → remediation: set XDR_CALDERA_API_KEY, caldera-lab.json api_key_file, or api_key_env.")
            write_agent_bootstraps(xdr_root, base_url, log_path)
            exit_final = finalize_agent_deploy_report(
                deploy_report,
                is_dry=False,
                fatal_preflight=True,
                fatal_reason="api_key_missing",
                rc_partial=1,
                nat_ok=True,
                caldera_up=True,
                api_key_present=False,
                vm_rows=vm_rows,
            )
            refresh_state(
                xdr_root,
                stated,
                cfg,
                merge_caldera={"agent_deploy_last": deploy_report},
                log_path=log_path,
            )
            if log_path:
                log_jsonl(
                    log_path,
                    "caldera_agent_deploy_preflight_failed",
                    reason="api_key_missing",
                    exit_code=exit_final,
                )
                log_jsonl(
                    log_path,
                    "caldera_agent_deploy_finished",
                    dry_run=False,
                    exit_code=exit_final,
                    ok=(exit_final == 0),
                )
            return exit_final

    sh_path = xdr_root / "runtime" / "caldera-agent" / "bootstrap-linux.sh"
    ps1_path = xdr_root / "runtime" / "caldera-agent" / "bootstrap-windows.ps1"
    if is_dry:
        print("[dry-run] runtime/caldera-agent bootstrap files are not written.")
        linux_body = ""
        ps1_body = ""
    else:
        write_agent_bootstraps(xdr_root, base_url, log_path)
        linux_body = sh_path.read_text(encoding="utf-8") if sh_path.is_file() else ""
        ps1_body = ps1_path.read_text(encoding="utf-8") if ps1_path.is_file() else ""

    nat_ok, nat_notes = nat_reverse_happy(nat_doc)
    if not nat_ok:
        print("[warn] Reverse NAT check (nat.json)")
        for n in nat_notes:
            print(f"  - {n}")
        print("  → remediation: on the KVM host run `nat verify` / `nat status` and reconcile iptables/DNAT contracts.")
        rc_all = 1
    else:
        print("[OK] Reverse NAT looks healthy per nat.json (consistent / iptables_readable).")

    caldera_up = probe_http(base_url, api_key, log_path)
    if not caldera_up:
        msg = "CALDERA server unreachable (HTTP probe failed)"
        print(f"[failure] {msg}")
        if not is_dry:
            print("  (non-dry-run: unreachable CALDERA is treated as preflight fatal with exit 2.)")
        print("  → remediation: start the server, verify base_url, TLS, and firewall rules.")
        if log_path:
            log_jsonl(log_path, "caldera_agent_deploy_preflight_failed", reason="caldera_unreachable")
        if is_dry:
            print("(dry-run: VM reachability checks continue even when CALDERA is unreachable.)")
        rc_all = 1
    allow_remote_exec = caldera_up and not is_dry

    for vm in agent_vm_roles(cfg):
        row: dict[str, Any] = {"vm": vm, "status": "skipped", "detail": ""}
        spec = agent_spec_for_vm(cfg, vm)
        bootstrap = str(spec.get("bootstrap") or "").strip().lower()
        if not bootstrap:
            bootstrap = "windows" if vm == "windows-victim" else "linux"

        running, lst = vm_libvirt_running(vm)
        if not running:
            row["status"] = "failed"
            row["detail"] = f"VM not running (libvirt: {lst})"
            print(f"[{vm}] failure: VM is not in running state ({lst}).")
            print("  → remediation: start the VM with `start`, then deploy again.")
            rc_all = 1
            vm_rows.append(row)
            continue

        nat_vm_ok, nat_vm_msgs = required_nat_for_vm(vm, lab, nat_doc)
        for m in nat_vm_msgs:
            print(f"[{vm}] NAT: {m}")
        if not nat_vm_ok:
            row["status"] = "failed"
            row["detail"] = "nat_contract; " + "; ".join(nat_vm_msgs)
            print(f"[{vm}] failure: Reverse NAT DNAT contract does not match expectations.")
            rc_all = 1
            vm_rows.append(row)
            continue

        entry = lab_vm_entry(lab, vm)
        vtype = str(entry.get("type") or "")

        if bootstrap == "linux" or vtype in ("linux", "sensor"):
            ssh_ok, ssh_detail = probe_ssh_linux_vm(vm, lab, cfg)
            if not ssh_ok:
                row["status"] = "failed"
                row["detail"] = ssh_detail
                print(f"[{vm}] failure: SSH unreachable ({ssh_detail}).")
                print("  → remediation: SSH unreachable — check keys, victim-linux-authorized_keys, and firewall.")
                rc_all = 1
                vm_rows.append(row)
                continue
            user = resolve_linux_ssh_user(vm, cfg, lab)
            host = actual_ip_hint(vm) or probe_host_for_vm(vm, lab)
            print(f"[{vm}] Linux SSH deploy: user={user} host={host} (internal/assigned IP)")
            if is_dry:
                row["status"] = "dry_run"
                row["detail"] = "would_run_ssh_bash_s_bootstrap_linux"
                print("  … dry-run: skipping remote bootstrap (local scripts already written).")
            elif not allow_remote_exec:
                row["status"] = "skipped"
                row["detail"] = "caldera_unreachable_skip_remote"
                print("  … skipping remote bootstrap because CALDERA is unreachable (scripts still written).")
                rc_all = 1
            else:
                code, tail = ssh_stdin_remote_linux(host, user, linux_body)
                if code != 0:
                    row["status"] = "failed"
                    row["detail"] = tail
                    print(f"  failure: remote bootstrap exit code {code}")
                    print(f"  ssh stderr/stdout tail:\n{tail}")
                    rc_all = 1
                else:
                    row["status"] = "ok"
                    row["detail"] = "remote_bootstrap_executed"
                    print("  Remote bootstrap finished (agent registration on CALDERA may lag).")
                if log_path:
                    log_jsonl(
                        log_path,
                        "caldera_agent_deploy_remote_linux",
                        vm=vm,
                        rc=code,
                        dry_run=False,
                    )
            vm_rows.append(row)
            continue

        if vm == "windows-victim" or bootstrap == "windows" or vtype == "windows":
            w = probe_windows_access(vm, lab, cfg)
            picked = str(w.get("picked") or "none")
            print(f"[{vm}] Windows transport selection from inventory: {picked} (mapping={w.get('inventory')})")
            if picked == "none":
                row["status"] = "failed"
                row["detail"] = "no_ssh_winrm_rdp"
                print("  failure: no reachable WinRM/SSH/RDP channel.")
                print("  → remediation: WinRM unreachable / SSH unreachable — check firewall, WinRM service, OpenSSH install.")
                rc_all = 1
                vm_rows.append(row)
                continue
            if picked == "ssh":
                inv = w.get("inventory") or {}
                ext = (primary_bind_ipv4() or "").strip() if primary_bind_ipv4 else ""
                win_user = str(agent_spec_for_vm(cfg, vm).get("ssh_user") or "").strip() or os.environ.get(
                    "XDR_LAB_WINDOWS_SSH_USER", ""
                ).strip() or str(entry.get("ssh_user") or "").strip()
                sport = inv.get("ssh_ext")
                if is_dry:
                    row["status"] = "dry_run"
                    row["detail"] = "would_ssh_powershell_bootstrap"
                    print("  … dry-run: skipping Windows SSH bootstrap.ps1 transfer/execution.")
                elif not allow_remote_exec:
                    row["status"] = "skipped"
                    row["detail"] = "caldera_unreachable_skip_remote"
                    print("  … skipping Windows remote bootstrap because CALDERA is unreachable.")
                    rc_all = 1
                elif sport and ext and win_user:
                    proc = subprocess.run(
                        [
                            "ssh",
                            "-o",
                            "BatchMode=yes",
                            "-o",
                            "StrictHostKeyChecking=no",
                            "-o",
                            "UserKnownHostsFile=/dev/null",
                            "-o",
                            "ConnectTimeout=12",
                            "-p",
                            str(sport),
                            f"{win_user}@{ext}",
                            "powershell.exe",
                            "-NoProfile",
                            "-NonInteractive",
                            "-ExecutionPolicy",
                            "Bypass",
                            "-Command",
                            "-",
                        ],
                        input=ps1_body,
                        capture_output=True,
                        text=True,
                        timeout=300,
                    )
                    if proc.returncode != 0:
                        row["status"] = "failed"
                        row["detail"] = (proc.stderr or proc.stdout or "")[-1200:]
                        print(f"  failure: remote PowerShell over SSH rc={proc.returncode}")
                        rc_all = 1
                    else:
                        row["status"] = "ok"
                        row["detail"] = "ssh_powershell_bootstrap"
                        print("  Submitted bootstrap script execution over Windows SSH path.")
                elif win_user:
                    internal = str(entry.get("internal_ip") or "").strip()
                    if not allow_remote_exec:
                        row["status"] = "skipped"
                        row["detail"] = "caldera_unreachable_skip_remote"
                        print("  … skipping Windows remote bootstrap because CALDERA is unreachable.")
                        rc_all = 1
                    else:
                        proc = subprocess.run(
                            [
                                "ssh",
                                "-o",
                                "BatchMode=yes",
                                "-o",
                                "StrictHostKeyChecking=no",
                                "-o",
                                "UserKnownHostsFile=/dev/null",
                                "-o",
                                "ConnectTimeout=12",
                                f"{win_user}@{internal}",
                                "powershell.exe",
                                "-NoProfile",
                                "-NonInteractive",
                                "-ExecutionPolicy",
                                "Bypass",
                                "-Command",
                                "-",
                            ],
                            input=ps1_body,
                            capture_output=True,
                            text=True,
                            timeout=300,
                        )
                        if proc.returncode != 0:
                            row["status"] = "failed"
                            row["detail"] = (proc.stderr or proc.stdout or "")[-1200:]
                            rc_all = 1
                        else:
                            row["status"] = "ok"
                            row["detail"] = "ssh_powershell_bootstrap_internal"
                            print("  Submitted bootstrap execution over Windows SSH (internal IP).")
                else:
                    row["status"] = "failed"
                    row["detail"] = "ssh_port_open_but_no_user"
                    print("  failure: SSH is open but no username is configured.")
                    print("  → remediation: set caldera-lab.json agents.windows-victim.ssh_user or XDR_LAB_WINDOWS_SSH_USER.")
                    rc_all = 1
                if log_path and not is_dry:
                    log_jsonl(log_path, "caldera_agent_deploy_remote_windows_ssh", vm=vm, status=row.get("status"))
            else:
                row["status"] = "manual" if picked in ("winrm_https", "rdp_only") else "manual"
                row["detail"] = picked
                print("  No automatic remote execution: WinRM is not used without credentials to run scripts.")
                print(f"  → remediation: run {xdr_root}/runtime/caldera-agent/bootstrap-windows.ps1 in an elevated PowerShell session,")
                print("     or copy/run the same content via WinRM (PSSession). If only RDP works, use share/paste deployment.")
                if picked == "winrm_https" and not w.get("winrm_tcp"):
                    pass
                if not is_dry:
                    rc_all = 1
            vm_rows.append(row)
            continue

        row["detail"] = "unknown_bootstrap"
        rc_all = 1
        vm_rows.append(row)

    fatal_preflight = bool(not is_dry and not caldera_up)
    exit_final = finalize_agent_deploy_report(
        deploy_report,
        is_dry=is_dry,
        fatal_preflight=fatal_preflight,
        fatal_reason="caldera_unreachable" if fatal_preflight else None,
        rc_partial=rc_all,
        nat_ok=nat_ok,
        caldera_up=caldera_up,
        api_key_present=api_key_present,
        vm_rows=vm_rows,
    )
    merge_c = {"agent_deploy_last": deploy_report}
    refresh_state(xdr_root, stated, cfg, merge_caldera=merge_c, log_path=log_path)
    print("")
    print(f"Bootstrap directory: {xdr_root / 'runtime' / 'caldera-agent'}")
    if is_dry:
        print("Mode: DRY-RUN — skipping execution on remote VMs (checks and script generation only).")
    if log_path:
        log_jsonl(
            log_path,
            "caldera_agent_deploy_finished",
            dry_run=is_dry,
            exit_code=exit_final,
            ok=(exit_final == 0),
        )
    return exit_final


def cmd_agent_remove(cfg: dict[str, Any], stated: Path, log_path: Path | None) -> int:
    api_key = resolve_api_key(cfg)
    base_url = str(cfg.get("base_url") or "http://127.0.0.1:8888")
    client = CalderaClient(base_url, api_key)
    if dry_run():
        if log_path:
            log_jsonl(log_path, "caldera_agent_remove_skipped", dry_run=True)
        print("DRY-RUN: would DELETE matched CALDERA agents via /api/rest (index=agents).")
        return 0
    agents = fetch_agents(client, log_path)
    removed = 0
    for vm in agent_vm_roles(cfg):
        paws = find_agent_paws(cfg, agents, vm)
        for paw in paws:
            code, _, err = client.request_json(
                "DELETE",
                urljoin(base_url.rstrip("/") + "/", "api/rest"),
                body={"index": "agents", "paw": paw},
                log_path=log_path,
            )
            if code in (200, 204):
                removed += 1
                if log_path:
                    log_jsonl(log_path, "caldera_agent_removed", vm=vm, paw=paw)
            elif log_path:
                log_jsonl(log_path, "caldera_agent_remove_failed", vm=vm, paw=paw, error=err, http_code=code)
    refresh_state(Path(stated.parent.parent), stated, cfg, log_path=log_path)
    print(f"Removed {removed} agent(s) (matched lab roles).")
    return 0


# --- Atomic Red Team — per-VM validate (victim-linux / windows-victim) ---

ATOMIC_VALIDATE_VM_ROLES: tuple[str, ...] = ("victim-linux", "windows-victim")


def atomic_red_team_bootstrap_paths(xdr_root: Path) -> tuple[Path, Path]:
    b = xdr_root / "bootstrap"
    return b / "atomic-red-team-linux.sh", b / "atomic-red-team-windows.ps1"


def _try_parse_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if len(line) < 2 or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def linux_atomic_probe_script(repo_path: str) -> str:
    """Script run on the guest via bash -s; prints one JSON line as the last line of output."""
    q = shlex.quote(repo_path)
    return f"""set +e
export ART_REPO={q}
python3 <<'PY'
import json, os, shutil, subprocess
from pathlib import Path

repo = Path(os.environ.get("ART_REPO", ""))
j: dict = {{
    "repo_dir": repo.is_dir(),
    "atomics_dir": (repo / "atomics").is_dir() if repo.is_dir() else False,
    "safe_marker": (repo / ".xdr-lab-atomic-safe-defaults").is_file() if repo.is_dir() else False,
    "bash": shutil.which("bash") is not None,
    "python3": shutil.which("python3") is not None,
    "pwsh_path": shutil.which("pwsh") or "",
}}
atomics = repo / "atomics"
if j["atomics_dir"]:
    yaml_hit = False
    try:
        for p in atomics.rglob("*.yaml"):
            if p.is_file():
                yaml_hit = True
                break
    except OSError:
        yaml_hit = False
    j["atomics_yaml_present"] = yaml_hit
else:
    j["atomics_yaml_present"] = False
j["linux_exec_ready"] = bool(j["bash"] and j["python3"])
if j["pwsh_path"]:
    cmd = [
        j["pwsh_path"],
        "-NoLogo",
        "-NonInteractive",
        "-Command",
        "(Get-Module -ListAvailable -Name Invoke-AtomicRedTeam | Measure-Object).Count",
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    try:
        j["invoke_art_module_count"] = int((p.stdout or "0").strip() or "0")
    except ValueError:
        j["invoke_art_module_count"] = -1
    gc = subprocess.run(
        [j["pwsh_path"], "-NoLogo", "-NonInteractive", "-Command", "Get-Command Invoke-AtomicTest -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    try:
        j["invoke_atomictest_cmd"] = int((gc.stdout or "0").strip() or "0") > 0
    except ValueError:
        j["invoke_atomictest_cmd"] = False
else:
    j["invoke_art_module_count"] = None
    j["invoke_atomictest_cmd"] = False
if j["pwsh_path"]:
    j["pwsh_invoke_ready"] = bool(j.get("invoke_art_module_count", 0) and j.get("invoke_art_module_count", 0) > 0)
else:
    j["pwsh_invoke_ready"] = None
print(json.dumps(j, ensure_ascii=False))
PY
"""


def windows_atomic_probe_ps1(repo_path: str) -> str:
    b64 = base64.b64encode(repo_path.encode("utf-8")).decode("ascii")
    return f"""
$ErrorActionPreference = 'Stop'
$repo = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{b64}'))
$atomics = Join-Path $repo 'atomics'
$modCount = @(Get-Module -ListAvailable -Name Invoke-AtomicRedTeam).Count
$cmdOk = $false
if (Get-Command Invoke-AtomicTest -ErrorAction SilentlyContinue) {{ $cmdOk = $true }}
$out = @{{
  repo_dir = (Test-Path -LiteralPath $repo)
  atomics_dir = (Test-Path -LiteralPath $atomics)
  invoke_mod_count = $modCount
  invoke_atomictest_cmd = [bool]$cmdOk
  ps_edition = $PSVersionTable.PSEdition
  ps_version = $PSVersionTable.PSVersion.ToString()
}}
$out | ConvertTo-Json -Compress
""".strip()


def ssh_powershell_stdin_windows_victim(
    vm: str,
    lab: dict[str, Any],
    cfg: dict[str, Any],
    ps_body: str,
    *,
    timeout: int = 150,
) -> tuple[int, str, str, str]:
    """Pipe PowerShell stdin to windows-victim over SSH. Returns (rc, stdout, stderr, reason)."""
    entry = lab_vm_entry(lab, vm)
    w = probe_windows_access(vm, lab, cfg)
    if str(w.get("picked") or "none") != "ssh" or not w.get("ssh_ok"):
        return 127, "", "", "ssh_not_available"
    win_user = (
        str(agent_spec_for_vm(cfg, vm).get("ssh_user") or "").strip()
        or os.environ.get("XDR_LAB_WINDOWS_SSH_USER", "").strip()
        or str(entry.get("ssh_user") or "").strip()
    )
    if not win_user:
        return 127, "", "", "windows_ssh_user_missing"
    inv = w.get("inventory") or {}
    ext = (primary_bind_ipv4() or "").strip() if primary_bind_ipv4 else ""
    sport = inv.get("ssh_ext")
    internal = str(entry.get("internal_ip") or "").strip()
    base_ssh = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "ConnectTimeout=12",
    ]
    argv: list[str]
    if sport and ext:
        argv = base_ssh + [
            "-p",
            str(sport),
            f"{win_user}@{ext}",
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "-",
        ]
    elif internal and win_user:
        argv = base_ssh + [
            f"{win_user}@{internal}",
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "-",
        ]
    else:
        return 127, "", "", "ssh_target_unresolved"
    proc = subprocess.run(
        argv,
        input=ps_body,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return int(proc.returncode or 0), proc.stdout or "", proc.stderr or "", "ok"


def _append_check(
    checks: list[dict[str, Any]],
    *,
    cid: str,
    label: str,
    ok: bool,
    detail: str,
) -> None:
    checks.append({"id": cid, "label": label, "ok": ok, "detail": detail})


def validate_linux_server_atomic(
    xdr_root: Path,
    cfg: dict[str, Any],
    lab: dict[str, Any],
) -> dict[str, Any]:
    vm = "victim-linux"
    checks: list[dict[str, Any]] = []
    art = cfg.get("atomic_red_team") if isinstance(cfg.get("atomic_red_team"), dict) else {}
    repo_cfg = str(art.get("linux_repo_path") or "").strip()
    sh_art, ps1_art = atomic_red_team_bootstrap_paths(xdr_root)

    running, lst = vm_libvirt_running(vm)
    _append_check(
        checks,
        cid="vm_running",
        label="libvirt running",
        ok=running,
        detail=f"state={lst}" if running else f"not_running ({lst})",
    )
    if not running:
        return {"vm": vm, "ok": False, "checks": checks, "remote": None, "ssh_detail": ""}

    ssh_ok, ssh_detail = probe_ssh_linux_vm(vm, lab, cfg)
    _append_check(
        checks,
        cid="ssh_reachable",
        label="VM SSH reachability",
        ok=ssh_ok,
        detail=ssh_detail,
    )
    if not ssh_ok:
        return {"vm": vm, "ok": False, "checks": checks, "remote": None, "ssh_detail": ssh_detail}

    _append_check(
        checks,
        cid="appliance_bootstrap_scripts",
        label="appliance bootstrap/atomic-red-team-* present",
        ok=sh_art.is_file() and ps1_art.is_file(),
        detail=f"{sh_art.name}: {'present' if sh_art.is_file() else 'missing'}; {ps1_art.name}: {'present' if ps1_art.is_file() else 'missing'}",
    )

    if not repo_cfg:
        _append_check(
            checks,
            cid="linux_repo_path_config",
            label="caldera-lab.json linux_repo_path",
            ok=False,
            detail="atomic_red_team.linux_repo_path is empty",
        )
        return {"vm": vm, "ok": False, "checks": checks, "remote": None, "ssh_detail": ssh_detail}

    _append_check(
        checks,
        cid="linux_repo_path_config",
        label="caldera-lab.json linux_repo_path",
        ok=True,
        detail=repo_cfg,
    )

    user = resolve_linux_ssh_user(vm, cfg, lab)
    host = (actual_ip_hint(vm) or probe_host_for_vm(vm, lab) or "").strip()
    rc, out, err = ssh_stdin_remote_linux_full(host, user, linux_atomic_probe_script(repo_cfg))
    remote_obj = _try_parse_json_object(out) or _try_parse_json_object(err)
    tail = (err or out)[-1200:]
    _append_check(
        checks,
        cid="remote_probe_rc",
        label="Guest remote probe (SSH) succeeded",
        ok=(rc == 0 and isinstance(remote_obj, dict)),
        detail=f"rc={rc}; tail={tail.strip()[:400]}" if rc != 0 or not remote_obj else "json_ok",
    )
    if rc != 0 or not isinstance(remote_obj, dict):
        return {"vm": vm, "ok": False, "checks": checks, "remote": None, "ssh_detail": ssh_detail}

    rd = bool(remote_obj.get("repo_dir"))
    ad = bool(remote_obj.get("atomics_dir"))
    yp = bool(remote_obj.get("atomics_yaml_present"))
    lex = bool(remote_obj.get("linux_exec_ready"))
    pwsh_path = str(remote_obj.get("pwsh_path") or "").strip()
    modc = remote_obj.get("invoke_art_module_count")
    iat_cmd = bool(remote_obj.get("invoke_atomictest_cmd"))

    _append_check(
        checks,
        cid="guest_art_repo_path",
        label="Guest ART repo path",
        ok=rd,
        detail=f"path exists: {repo_cfg}" if rd else f"missing: {repo_cfg}",
    )
    _append_check(
        checks,
        cid="guest_art_atomics",
        label="Guest atomics/ directory",
        ok=ad,
        detail="atomics present" if ad else "atomics missing",
    )
    _append_check(
        checks,
        cid="guest_art_atomics_yaml",
        label="Guest atomics YAML sample",
        ok=yp,
        detail="yaml found" if yp else "yaml missing (clone may be incomplete)",
    )
    _append_check(
        checks,
        cid="linux_exec_method",
        label="Linux execution baseline (bash+python3)",
        ok=lex,
        detail="bash+python3 OK" if lex else "bash or python3 missing",
    )
    if pwsh_path:
        mod_ok = isinstance(modc, int) and modc > 0
        _append_check(
            checks,
            cid="powershell_invoke_atomic_linux",
            label="Linux pwsh + Invoke-AtomicRedTeam",
            ok=mod_ok and iat_cmd,
            detail=f"pwsh={pwsh_path}; module_count={modc}; Invoke-AtomicTest_cmd={iat_cmd}",
        )
        pwsh_gate = mod_ok and iat_cmd
    else:
        _append_check(
            checks,
            cid="powershell_invoke_atomic_linux",
            label="Linux pwsh + Invoke-AtomicRedTeam (optional)",
            ok=True,
            detail="pwsh not installed — bash/atomics path only (optionally bootstrap with WITH_PWSH=1)",
        )
        pwsh_gate = True

    appliance_ok = sh_art.is_file() and ps1_art.is_file()
    ok_all = appliance_ok and rd and ad and yp and lex and pwsh_gate
    return {
        "vm": vm,
        "ok": ok_all,
        "checks": checks,
        "remote": remote_obj,
        "ssh_detail": ssh_detail,
        "host": host,
        "ssh_user": user,
    }


def validate_windows_victim_atomic(
    xdr_root: Path,
    cfg: dict[str, Any],
    lab: dict[str, Any],
) -> dict[str, Any]:
    vm = "windows-victim"
    checks: list[dict[str, Any]] = []
    art = cfg.get("atomic_red_team") if isinstance(cfg.get("atomic_red_team"), dict) else {}
    repo_cfg = str(art.get("windows_repo_path") or "").strip()
    sh_art, ps1_art = atomic_red_team_bootstrap_paths(xdr_root)

    running, lst = vm_libvirt_running(vm)
    _append_check(
        checks,
        cid="vm_running",
        label="libvirt running",
        ok=running,
        detail=f"state={lst}" if running else f"not_running ({lst})",
    )
    if not running:
        return {"vm": vm, "ok": False, "checks": checks, "remote": None, "transport": "n/a"}

    w = probe_windows_access(vm, lab, cfg)
    picked = str(w.get("picked") or "none")
    _append_check(
        checks,
        cid="vm_transport_reachable",
        label="VM transport channel (SSH/WinRM/RDP) reachable",
        ok=picked != "none",
        detail=f"picked={picked}; inventory={w.get('inventory')}",
    )
    if picked == "none":
        return {"vm": vm, "ok": False, "checks": checks, "remote": None, "transport": picked}

    _append_check(
        checks,
        cid="appliance_bootstrap_scripts",
        label="appliance bootstrap/atomic-red-team-* present",
        ok=sh_art.is_file() and ps1_art.is_file(),
        detail=f"{sh_art.name}: {'present' if sh_art.is_file() else 'missing'}; {ps1_art.name}: {'present' if ps1_art.is_file() else 'missing'}",
    )

    if not repo_cfg:
        _append_check(
            checks,
            cid="windows_repo_path_config",
            label="caldera-lab.json windows_repo_path",
            ok=False,
            detail="atomic_red_team.windows_repo_path is empty",
        )
        return {"vm": vm, "ok": False, "checks": checks, "remote": None, "transport": picked}

    _append_check(
        checks,
        cid="windows_repo_path_config",
        label="caldera-lab.json windows_repo_path",
        ok=True,
        detail=repo_cfg,
    )

    if picked != "ssh" or not w.get("ssh_ok"):
        _append_check(
            checks,
            cid="windows_ssh_for_remote_probe",
            label="Windows SSH for remote probe",
            ok=False,
            detail=f"no SSH channel (picked={picked}) — cannot auto-check guest paths/modules",
        )
        return {"vm": vm, "ok": False, "checks": checks, "remote": None, "transport": picked}

    ps1 = windows_atomic_probe_ps1(repo_cfg)
    rc, out, err, reason = ssh_powershell_stdin_windows_victim(vm, lab, cfg, ps1)
    remote_obj = _try_parse_json_object(out) or _try_parse_json_object(err)
    tail = ((err or "") + (out or ""))[-1400:]
    _append_check(
        checks,
        cid="remote_probe_rc",
        label="Guest remote probe (SSH+PowerShell) succeeded",
        ok=(rc == 0 and reason == "ok" and isinstance(remote_obj, dict)),
        detail=f"rc={rc}; reason={reason}; tail={tail.strip()[:400]}"
        if rc != 0 or not remote_obj
        else "json_ok",
    )
    if rc != 0 or not isinstance(remote_obj, dict):
        return {"vm": vm, "ok": False, "checks": checks, "remote": None, "transport": picked}

    rl = {str(k).lower(): v for k, v in remote_obj.items()}
    rd = bool(rl.get("repo_dir"))
    ad = bool(rl.get("atomics_dir"))
    mc = rl.get("invoke_mod_count")
    try:
        mc_int = int(mc) if mc is not None else 0
    except (TypeError, ValueError):
        mc_int = 0
    iat = bool(rl.get("invoke_atomictest_cmd"))

    _append_check(
        checks,
        cid="guest_art_repo_path",
        label="Guest ART repo path",
        ok=rd,
        detail=f"path exists: {repo_cfg}" if rd else f"missing: {repo_cfg}",
    )
    _append_check(
        checks,
        cid="guest_art_atomics",
        label="Guest atomics/ directory",
        ok=ad,
        detail="atomics present" if ad else "atomics missing",
    )
    _append_check(
        checks,
        cid="powershell_invoke_atomic_windows",
        label="PowerShell Invoke-AtomicRedTeam module",
        ok=mc_int > 0 and iat,
        detail=f"module_count={mc_int}; Invoke-AtomicTest_cmd={iat}",
    )

    appliance_ok = sh_art.is_file() and ps1_art.is_file()
    ok_all = appliance_ok and rd and ad and mc_int > 0 and iat
    return {
        "vm": vm,
        "ok": ok_all,
        "checks": checks,
        "remote": remote_obj,
        "transport": picked,
    }


def build_atomic_validate_remediations(vm_reports: list[dict[str, Any]]) -> list[dict[str, str]]:
    hints: list[dict[str, str]] = []

    def add(code: str, message: str, action: str) -> None:
        hints.append({"code": code, "message": message, "action": action})

    for block in vm_reports:
        if not isinstance(block, dict):
            continue
        vm = str(block.get("vm") or "?")
        if not block.get("ok"):
            add(
                f"atomic_validate_failed:{vm}",
                f"{vm}: Atomic Red Team guest validation failed.",
                "Inspect checks and remote fields from `scenario atomic validate --json`, then follow the detailed hints below.",
            )
        for c in block.get("checks") or []:
            if not isinstance(c, dict) or c.get("ok"):
                continue
            cid = str(c.get("id") or "")
            if cid == "vm_running":
                add(
                    f"{vm}:vm_not_running",
                    f"{vm} is not in running state in libvirt.",
                    "Start the VM with `aella_cli lab start victim-linux` or `windows-victim` as appropriate.",
                )
            elif cid == "ssh_reachable" and vm == "victim-linux":
                add(
                    "victim-linux:ssh_unreachable",
                    "Cannot reach victim-linux over the SSH deploy channel.",
                    "Check SSH keys, `VICTIM_LINUX_SSH_USER`, NAT, and ports via `lab access`.",
                )
            elif cid == "vm_transport_reachable" and vm == "windows-victim":
                add(
                    "windows-victim:transport_unreachable",
                    "No reachable SSH/WinRM/RDP channel on windows-victim.",
                    "Review `lab-vms.json` external_nat_port_mapping, VM firewall, and OpenSSH/WinRM services.",
                )
            elif cid == "windows_ssh_for_remote_probe":
                add(
                    "windows-victim:ssh_required",
                    "Windows guest atomic validation needs an automated SSH channel.",
                    "Install OpenSSH Server on the guest, set `caldera-lab.json` ssh_user and NAT SSH port, or validate manually over RDP.",
                )
            elif cid in ("linux_repo_path_config", "windows_repo_path_config"):
                add(
                    "atomic_red_team_paths_incomplete",
                    "`atomic_red_team.linux_repo_path` / `windows_repo_path` in caldera-lab.json are empty.",
                    "Fill them to match the guest clone paths using `config/caldera-lab.json.example` as a guide.",
                )
            elif cid == "guest_art_repo_path":
                add(
                    f"{vm}:art_repo_missing",
                    f"{vm}: configured ART repository directory is missing on the guest.",
                    f"Clone with `bootstrap/atomic-red-team-{'linux' if vm == 'victim-linux' else 'windows'}.{'sh' if vm == 'victim-linux' else 'ps1'}` or fix the path.",
                )
            elif cid == "guest_art_atomics":
                add(
                    f"{vm}:art_atomics_missing",
                    f"{vm}: ART `atomics/` directory is missing.",
                    "Re-clone the repository or reinstall if the tree is damaged.",
                )
            elif cid == "guest_art_atomics_yaml":
                add(
                    "victim-linux:art_atomics_empty",
                    "victim-linux: no YAML found under atomics/.",
                    "Confirm the ART repository cloned correctly.",
                )
            elif cid == "linux_exec_method":
                add(
                    "victim-linux:exec_prereq",
                    "victim-linux: bash or python3 is missing; Linux atomics baseline is insufficient.",
                    "Install with e.g. `apt install bash python3`.",
                )
            elif cid == "powershell_invoke_atomic_linux":
                add(
                    "victim-linux:pwsh_invoke_missing",
                    "victim-linux: pwsh is present but Invoke-AtomicRedTeam / Invoke-AtomicTest is not ready.",
                    "Install modules with `sudo WITH_PWSH=1 ./bootstrap/atomic-red-team-linux.sh --with-pwsh`, or remove pwsh to use the bash-only path.",
                )
            elif cid == "powershell_invoke_atomic_windows":
                add(
                    "windows-victim:invoke_module_missing",
                    "windows-victim: Invoke-AtomicRedTeam module or Invoke-AtomicTest command is missing.",
                    "From an elevated PowerShell run `Install-Module invoke-atomicredteam` or `bootstrap/atomic-red-team-windows.ps1 -InstallModule`.",
                )
            elif cid == "remote_probe_rc":
                add(
                    f"{vm}:remote_probe_failed",
                    f"{vm}: remote probe script failed.",
                    "Check the SSH session, guest shell errors, and timeouts.",
                )
            elif cid == "appliance_bootstrap_scripts":
                add(
                    "atomic_bootstrap_scripts_missing",
                    "Appliance repo is missing `bootstrap/atomic-red-team-linux.sh` or the `.ps1` counterpart.",
                    "Restore the xdr-lab-appliance tree or recover those files.",
                )
    return hints


def run_atomic_red_team_validate(
    xdr_root: Path,
    cfg: dict[str, Any],
    log_path: Path | None,
) -> dict[str, Any]:
    lab = load_lab_vms_json(xdr_root)
    vms: list[dict[str, Any]] = []
    for role in ATOMIC_VALIDATE_VM_ROLES:
        if role == "victim-linux":
            vms.append(validate_linux_server_atomic(xdr_root, cfg, lab))
        elif role == "windows-victim":
            vms.append(validate_windows_victim_atomic(xdr_root, cfg, lab))
    ok_all = all(bool(v.get("ok")) for v in vms)
    hints = build_atomic_validate_remediations(vms)
    art = cfg.get("atomic_red_team") if isinstance(cfg.get("atomic_red_team"), dict) else {}
    return {
        "ok": ok_all,
        "vms": vms,
        "remediation_hints": hints,
        "atomic_red_team_paths": {
            "linux_repo_path": str(art.get("linux_repo_path") or "").strip(),
            "windows_repo_path": str(art.get("windows_repo_path") or "").strip(),
        },
    }


def print_atomic_validate_human(report: dict[str, Any]) -> None:
    print("=== Atomic Red Team — VM validate (victim-linux / windows-victim) ===")
    print("")
    for block in report.get("vms") or []:
        if not isinstance(block, dict):
            continue
        vm = str(block.get("vm") or "?")
        st = "OK" if block.get("ok") else "FAIL"
        print(f"[{vm}] overall: {st}")
        if block.get("host"):
            print(f"  SSH host: {block.get('host')} user={block.get('ssh_user', '')}")
        if block.get("transport"):
            print(f"  Windows transport: {block.get('transport')}")
        w_label, w_stat, w_detail = 30, 8, 44
        print(f"  {'Check':<{w_label}} {'Status':<{w_stat}} Detail")
        print(f"  {'-' * (w_label + w_stat + w_detail + 2)}")
        for c in block.get("checks") or []:
            if not isinstance(c, dict):
                continue
            label = str(c.get("label") or c.get("id") or "?")
            ok = bool(c.get("ok"))
            st2 = "OK" if ok else "FAIL"
            detail = str(c.get("detail") or "")
            if len(detail) > w_detail:
                detail = detail[: w_detail - 1] + "…"
            print(f"  {label:<{w_label}} {st2:<{w_stat}} {detail}")
        rem = block.get("remote")
        if isinstance(rem, dict) and rem:
            print("  [Guest remote summary]")
            try:
                print("   " + json.dumps(rem, ensure_ascii=False)[:500])
            except (TypeError, ValueError):
                print(f"   {rem!r}")
        print("")
    hints = report.get("remediation_hints") or []
    if hints:
        print("[Remediation]")
        for h in hints:
            if not isinstance(h, dict):
                continue
            print(f"  - [{h.get('code', '?')}] {h.get('message', '')}")
            act = str(h.get("action") or "").strip()
            if act:
                print(f"    → {act}")
        print("")


def cmd_atomic_validate(
    xdr_root: Path,
    stated: Path,
    cfg: dict[str, Any],
    log_path: Path | None,
    *,
    json_out: bool = False,
) -> int:
    report = run_atomic_red_team_validate(xdr_root, cfg, log_path)
    all_ok = bool(report.get("ok"))
    ts = utc_now()
    summary = (
        f"atomic validate passed ({ts})" if all_ok else f"atomic validate failed — see remediation_hints ({ts})"
    )

    caldera_path = stated / "caldera.json"
    caldera_doc = load_json(caldera_path, default_caldera_doc(cfg))
    if not isinstance(caldera_doc, dict):
        caldera_doc = default_caldera_doc(cfg)

    last_block: dict[str, Any] = {
        "utc": ts,
        "ok": all_ok,
        "summary": summary,
        "vms": report.get("vms") or [],
        "remediation_hints": report.get("remediation_hints") or [],
        "atomic_red_team_paths": report.get("atomic_red_team_paths") or {},
    }
    caldera_doc["atomic_red_team_validate_last"] = last_block
    save_json_atomic(caldera_path, caldera_doc)

    if log_path:
        log_jsonl(
            log_path,
            "caldera_atomic_validate_finished",
            ok=all_ok,
            vms=[v.get("vm") for v in report.get("vms") or [] if isinstance(v, dict)],
        )

    if json_out:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_atomic_validate_human(report)
        if all_ok:
            print(f"runtime/state/caldera.json atomic_red_team_validate_last updated ({ts})")
    return 0 if all_ok else 1


def build_bootstrap_validate_remediations(checks: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Operator-facing remediation hints for failed bootstrap checks."""
    by_id = {str(c.get("id") or ""): c for c in checks if isinstance(c, dict)}
    hints: list[dict[str, str]] = []

    def add(code: str, message: str, action: str) -> None:
        hints.append({"code": code, "message": message, "action": action})

    c_url = by_id.get("caldera_base_url")
    if c_url and not c_url.get("ok"):
        add(
            "caldera_unreachable",
            "CALDERA base_url HTTP probe from the appliance failed.",
            "Start CALDERA, verify base_url, TLS, firewall, and routing.",
        )
    c_auth = by_id.get("caldera_api_authenticated")
    if c_auth and not c_auth.get("ok"):
        add(
            "caldera_api_auth_required",
            "CALDERA HTTP is reachable but GET /api/agents is not authenticated (302→/login or HTML login page).",
            "Set XDR_CALDERA_API_KEY or api_key_file to match CALDERA conf/default.yml api_key_red; "
            "see docs/caldera-integration.md §3.",
        )
    c_key = by_id.get("api_key")
    if c_key and not c_key.get("ok"):
        add(
            "api_key_missing",
            "CALDERA API key is empty.",
            "Set XDR_CALDERA_API_KEY, api_key_file in caldera-lab.json, or an env var named by api_key_env.",
        )
    c_atomic = by_id.get("atomic_plugin")
    if c_atomic and not c_atomic.get("ok"):
        add(
            "atomic_plugin_missing",
            "plugins in caldera-lab.json does not list atomic.",
            "Align with CALDERA conf/default.yml plugins and include atomic (see CALDERA_PLUGINS in bootstrap/caldera-server-bootstrap.sh).",
        )
    c_art = by_id.get("atomic_red_team_paths")
    if c_art and not c_art.get("ok"):
        add(
            "atomic_red_team_paths_incomplete",
            "atomic_red_team.linux_repo_path or windows_repo_path is empty.",
            "Fill the atomic_red_team block in config/caldera-lab.json with Linux/Windows ART paths.",
        )
    c_bs = by_id.get("atomic_bootstrap_scripts")
    if c_bs and not c_bs.get("ok"):
        add(
            "atomic_bootstrap_scripts_missing",
            "bootstrap/atomic-red-team-* installer scripts are missing from the repo.",
            "Restore bootstrap/atomic-red-team-linux.sh and .ps1 in the xdr-lab-appliance tree.",
        )
    return hints


def run_bootstrap_validation(
    xdr_root: Path,
    cfg: dict[str, Any],
    log_path: Path | None,
) -> dict[str, Any]:
    """Pre-flight checks for CALDERA, API key, plugins, ART paths, and repo bootstrap scripts."""
    base_url = str(cfg.get("base_url") or "http://127.0.0.1:8888").strip()
    api_key = resolve_api_key(cfg, xdr_root=xdr_root)
    api_key_ok = bool(api_key)

    pl = cfg.get("plugins")
    plugins_list = [str(p).strip() for p in pl] if isinstance(pl, list) else []
    plugins_norm = [p.lower() for p in plugins_list if p]
    atomic_ok = "atomic" in plugins_norm

    art = cfg.get("atomic_red_team") if isinstance(cfg.get("atomic_red_team"), dict) else {}
    linux_path = str(art.get("linux_repo_path") or "").strip()
    win_path = str(art.get("windows_repo_path") or "").strip()
    art_paths_ok = bool(linux_path and win_path)

    sh_art, ps1_art = atomic_red_team_bootstrap_paths(xdr_root)
    scripts_ok = sh_art.is_file() and ps1_art.is_file()

    caldera_up = probe_http_reachable(base_url, api_key, log_path)
    client = make_caldera_client(cfg, timeout_sec=4.0)
    api_auth_ok = probe_api_authenticated(client, log_path) if caldera_up else False

    checks: list[dict[str, Any]] = [
        {
            "id": "caldera_base_url",
            "label": "CALDERA base_url HTTP reachability",
            "ok": caldera_up,
            "detail": base_url if caldera_up else f"HTTP probe failed (base_url={base_url})",
        },
        {
            "id": "caldera_api_authenticated",
            "label": "CALDERA REST API authenticated (GET /api/agents → JSON)",
            "ok": api_auth_ok,
            "detail": (
                "GET /api/agents returned JSON array"
                if api_auth_ok
                else (
                    "not authenticated — configure KEY header (§3) "
                    f"(last http_code from probe; 302→/login means missing/invalid api key)"
                )
            ),
        },
        {
            "id": "api_key",
            "label": "API key present",
            "ok": api_key_ok,
            "detail": (
                f"from {caldera_api_key_file_path(cfg)} via resolve_api_key"
                if api_key_ok
                else "api_key_file unreadable and env empty"
            ),
        },
        {
            "id": "plugins_snapshot",
            "label": "caldera-lab.json plugins snapshot",
            "ok": True,
            "detail": ", ".join(plugins_list) if plugins_list else "(empty list)",
        },
        {
            "id": "atomic_plugin",
            "label": "atomic plugin listed",
            "ok": atomic_ok,
            "detail": "plugins includes atomic" if atomic_ok else "plugins does not include atomic",
        },
        {
            "id": "atomic_red_team_paths",
            "label": "Atomic Red Team path settings",
            "ok": art_paths_ok,
            "detail": f"linux_repo_path={linux_path or '(empty)'}; windows_repo_path={win_path or '(empty)'}",
        },
        {
            "id": "atomic_bootstrap_scripts",
            "label": "bootstrap/atomic-red-team-(linux|windows) present",
            "ok": scripts_ok,
            "detail": f"{sh_art.name}: {'present' if sh_art.is_file() else 'missing'}; {ps1_art.name}: {'present' if ps1_art.is_file() else 'missing'}",
        },
    ]

    gate = frozenset(
        {
            "caldera_base_url",
            "caldera_api_authenticated",
            "api_key",
            "atomic_plugin",
            "atomic_red_team_paths",
            "atomic_bootstrap_scripts",
        }
    )
    all_ok = all(bool(c.get("ok")) for c in checks if str(c.get("id") or "") in gate)
    remediations = build_bootstrap_validate_remediations(checks)
    return {
        "ok": all_ok,
        "base_url": base_url,
        "checks": checks,
        "remediation_hints": remediations,
    }


def print_bootstrap_validate_human(report: dict[str, Any]) -> None:
    print("=== CALDERA / Atomic bootstrap validate ===")
    print(f"base_url: {report.get('base_url', '-')}")
    print("")
    w_label, w_stat, w_detail = 34, 8, 48
    print(f"{'Check':<{w_label}} {'Status':<{w_stat}} Detail")
    print("-" * (w_label + w_stat + w_detail + 2))
    for c in report.get("checks") or []:
        if not isinstance(c, dict):
            continue
        label = str(c.get("label") or c.get("id") or "?")
        ok = bool(c.get("ok"))
        cid = str(c.get("id") or "")
        if cid == "plugins_snapshot":
            st = "OK"
        else:
            st = "OK" if ok else "FAIL"
        detail = str(c.get("detail") or "")
        if len(detail) > w_detail:
            detail = detail[: w_detail - 1] + "…"
        print(f"{label:<{w_label}} {st:<{w_stat}} {detail}")
    hints = report.get("remediation_hints") or []
    if hints:
        print("")
        print("[Remediation]")
        for h in hints:
            if not isinstance(h, dict):
                continue
            print(f"  - [{h.get('code', '?')}] {h.get('message', '')}")
            act = str(h.get("action") or "").strip()
            if act:
                print(f"    → {act}")


def cmd_bootstrap_validate(
    xdr_root: Path,
    stated: Path,
    cfg: dict[str, Any],
    log_path: Path | None,
    *,
    json_out: bool = False,
) -> int:
    report = run_bootstrap_validation(xdr_root, cfg, log_path)
    all_ok = bool(report.get("ok"))
    ts = utc_now()
    summary = (
        f"bootstrap validate passed ({ts})"
        if all_ok
        else f"bootstrap validate failed — see remediation_hints ({ts})"
    )

    caldera_path = stated / "caldera.json"
    caldera_doc = load_json(caldera_path, default_caldera_doc(cfg))
    if not isinstance(caldera_doc, dict):
        caldera_doc = default_caldera_doc(cfg)

    sb = server_bootstrap_block_from_cfg(cfg, preserve=None)
    sb["bootstrap_install_status"] = "ok" if all_ok else "failed"
    sb["bootstrap_install_detail"] = summary
    sb["last_bootstrap_validate_utc"] = ts
    sb["bootstrap_validate_ok"] = all_ok
    sb["bootstrap_validate_checks"] = report.get("checks") or []
    caldera_doc["server_bootstrap"] = sb
    save_json_atomic(caldera_path, caldera_doc)

    if log_path:
        log_jsonl(
            log_path,
            "caldera_bootstrap_validate_finished",
            ok=all_ok,
            base_url=report.get("base_url"),
        )

    if json_out:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_bootstrap_validate_human(report)
        if all_ok:
            print("")
            print(f"runtime/state/caldera.json server_bootstrap.bootstrap_install_status=ok ({ts})")
    return 0 if all_ok else 1


# ---------------------------------------------------------------------------
# Live runtime visibility / inspection / evidence (read-only; additive helpers)
# ---------------------------------------------------------------------------

STALE_ARTIFACT_HOURS_DEFAULT = 72.0


def timestamp_age_hours(ts: Any) -> float | None:
    dt = _parse_iso_utc(ts)
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 3600.0)


def read_jsonl_tail(log_path: Path, *, lines: int = 20) -> list[dict[str, Any]]:
    if not log_path.is_file() or lines <= 0:
        return []
    try:
        with log_path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            chunk = min(size, max(65536, lines * 4096))
            f.seek(max(0, size - chunk))
            raw = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out[-lines:]


def filter_jsonl_rows(rows: list[dict[str, Any]], pattern: str | None) -> list[dict[str, Any]]:
    if not pattern:
        return rows
    try:
        rx = re.compile(pattern)
    except re.error:
        return rows
    filtered: list[dict[str, Any]] = []
    for row in rows:
        blob = json.dumps(row, ensure_ascii=False)
        if rx.search(blob) or rx.search(str(row.get("event") or "")):
            filtered.append(row)
    return filtered


def summarize_last_jsonl_event(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    last = rows[-1]
    return {
        "ts": last.get("ts"),
        "event": last.get("event"),
        "summary": last.get("summary"),
        "scenario": last.get("scenario"),
        "caldera_operation_id": last.get("caldera_operation_id"),
        "phase": last.get("phase"),
    }


def build_mirror_summary(stated: Path) -> dict[str, Any]:
    mir = load_mirror_doc(stated)
    path = stated / "mirror.json"
    age = timestamp_age_hours(mir.get("last_verified_time") or mir.get("last_applied_time"))
    return {
        "path": str(path),
        "present": path.is_file(),
        "consistent": mir.get("consistent"),
        "mirror_exists": mir.get("mirror_exists"),
        "output_port_matches_sensor": mir.get("output_port_matches_sensor"),
        "bridge": mir.get("bridge"),
        "mirror_name": mir.get("mirror_name"),
        "sensor_vm": mir.get("sensor_vm"),
        "sensor_interface": mir.get("sensor_interface"),
        "output_port_name": mir.get("output_port_name"),
        "last_verified_time": mir.get("last_verified_time"),
        "age_hours": round(age, 2) if age is not None else None,
    }


def build_snapshot_summary(stated: Path, scenario: dict[str, Any]) -> dict[str, Any]:
    snap = load_snapshots_catalog_doc(stated)
    per_vm = snap.get("per_vm") if isinstance(snap.get("per_vm"), dict) else {}
    total_snaps = 0
    vm_rows: list[dict[str, Any]] = []
    for vm, row in sorted(per_vm.items()):
        if not isinstance(row, dict):
            continue
        cnt = int(row.get("snapshot_count") or 0)
        total_snaps += cnt
        vm_rows.append(
            {
                "vm": vm,
                "domain_defined": row.get("domain_defined"),
                "snapshot_count": cnt,
            }
        )
    return {
        "path": str(stated / "snapshots.json"),
        "present": (stated / "snapshots.json").is_file(),
        "updated_utc": snap.get("updated_utc"),
        "last_batch": snap.get("last_batch"),
        "per_vm": vm_rows,
        "total_snapshot_count": total_snaps,
        "scenario_snapshot_before_name": scenario.get("snapshot_before_name"),
        "scenario_snapshot_before_result": scenario.get("snapshot_before_result"),
    }


def build_active_agent_summary(
    scenario: dict[str, Any], caldera: dict[str, Any], cfg: dict[str, Any]
) -> dict[str, Any]:
    agents = scenario.get("agents") if isinstance(scenario.get("agents"), dict) else {}
    matrix_last = caldera.get("agent_matrix_last")
    if isinstance(matrix_last, dict) and matrix_last:
        agents = matrix_last
    roles = agent_vm_roles(cfg)
    connected = [vm for vm in roles if bool(agents.get(vm))]
    disconnected = [vm for vm in roles if not bool(agents.get(vm))]
    dep = caldera.get("agent_deploy_last") if isinstance(caldera.get("agent_deploy_last"), dict) else {}
    return {
        "roles": roles,
        "connected": connected,
        "disconnected": disconnected,
        "matrix": {str(k): bool(v) for k, v in agents.items()},
        "last_deploy_utc": dep.get("utc"),
        "last_deploy_exit_code": dep.get("exit_code"),
        "last_deploy_fatal_reason": dep.get("fatal_reason"),
    }


def detect_stale_runtime_warnings(
    scenario: dict[str, Any],
    caldera: dict[str, Any],
    stated: Path,
    *,
    stale_hours: float = STALE_ARTIFACT_HOURS_DEFAULT,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    st = str(scenario.get("status") or "").strip().lower()

    op_id = str(caldera.get("active_caldera_operation_id") or "").strip()
    if op_id and st not in ("running", "starting"):
        warnings.append(
            {
                "code": "orphan_operation_id",
                "message": (
                    f"caldera.json still echoes active_caldera_operation_id={op_id!r} while "
                    f"scenario status={st!r}. Run `lab scenario stop` or finish in CALDERA UI."
                ),
            }
        )

    mir = load_mirror_doc(stated)
    if (stated / "mirror.json").is_file():
        age = timestamp_age_hours(mir.get("last_verified_time") or mir.get("last_applied_time"))
        if age is not None and age > stale_hours:
            warnings.append(
                {
                    "code": "stale_mirror_json",
                    "message": (
                        f"mirror.json last verified/applied {age:.1f}h ago — refresh with "
                        "`xdr-lab-vm-manager.sh mirror status` and `lab mirror verify`."
                    ),
                }
            )
        if mir.get("consistent") is False:
            warnings.append(
                {
                    "code": "mirror_inconsistent",
                    "message": "mirror.json consistent=false — run `lab mirror verify` before live capture.",
                }
            )

    nat = load_nat_state_doc(stated)
    if (stated / "nat.json").is_file():
        nat_age = timestamp_age_hours(nat.get("ts") or nat.get("updated_utc"))
        if nat_age is not None and nat_age > stale_hours:
            warnings.append(
                {
                    "code": "stale_nat_json",
                    "message": (
                        f"nat.json timestamp is {nat_age:.1f}h old — run `lab nat verify` before guest access checks."
                    ),
                }
            )
        if nat.get("consistent") is False:
            warnings.append(
                {
                    "code": "nat_inconsistent",
                    "message": "nat.json consistent=false — reverse NAT contract drift; run `lab nat verify`.",
                }
            )

    snap_age = timestamp_age_hours(load_snapshots_catalog_doc(stated).get("updated_utc"))
    if snap_age is not None and snap_age > stale_hours:
        warnings.append(
            {
                "code": "stale_snapshots_catalog",
                "message": (
                    f"snapshots.json updated_utc is {snap_age:.1f}h old — run `lab snapshot list` to refresh catalog."
                ),
            }
        )

    err = str(scenario.get("last_error") or "").strip()
    if err and st in ("failed", "blocked"):
        warnings.append(
            {
                "code": "unresolved_last_error",
                "message": f"scenario.json last_error is still set ({err[:180]}). Review before repeating a live run.",
            }
        )

    probe_age = timestamp_age_hours(caldera.get("last_probe_utc"))
    if probe_age is not None and probe_age > stale_hours and not bool(caldera.get("http_reachable")):
        warnings.append(
            {
                "code": "stale_unreachable_probe",
                "message": (
                    f"CALDERA last_probe_utc is {probe_age:.1f}h old and http_reachable=false — "
                    "run `lab scenario bootstrap validate`."
                ),
            }
        )

    return warnings


def build_runtime_quick_summary(
    xdr_root: Path,
    stated: Path,
    cfg: dict[str, Any],
    log_path: Path | None,
    *,
    refresh: bool = True,
) -> dict[str, Any]:
    if refresh:
        scenario_doc, caldera_doc = refresh_state(xdr_root, stated, cfg, log_path=log_path)
    else:
        scenario_doc = load_json(stated / "scenario.json", default_scenario_doc())
        caldera_doc = load_json(stated / "caldera.json", default_caldera_doc(cfg))
        if not isinstance(scenario_doc, dict):
            scenario_doc = default_scenario_doc()
        if not isinstance(caldera_doc, dict):
            caldera_doc = default_caldera_doc(cfg)

    tail_rows = read_jsonl_tail(log_path, lines=1) if log_path else []
    op_block = scenario_doc.get("caldera") if isinstance(scenario_doc.get("caldera"), dict) else {}
    operation_id = (
        str(op_block.get("operation_id") or caldera_doc.get("active_caldera_operation_id") or "").strip() or None
    )
    llr = scenario_doc.get("last_live_run") if isinstance(scenario_doc.get("last_live_run"), dict) else {}
    if not operation_id and isinstance(llr.get("caldera_operation"), dict):
        operation_id = str(llr["caldera_operation"].get("operation_id") or "").strip() or None

    state_files = {}
    for name in ("scenario.json", "caldera.json", "mirror.json", "nat.json", "snapshots.json"):
        p = stated / name
        state_files[name] = {"present": p.is_file(), "path": str(p)}

    return {
        "generated_utc": utc_now(),
        "scenario_status": scenario_doc.get("status"),
        "scenario_name": scenario_doc.get("scenario_name") or scenario_doc.get("current_operation"),
        "run_id": scenario_doc.get("run_id"),
        "operation_id": operation_id,
        "operation_name": op_block.get("operation_name") or caldera_doc.get("active_caldera_operation_name"),
        "http_reachable": bool(caldera_doc.get("http_reachable")),
        "base_url": caldera_doc.get("base_url") or cfg.get("base_url"),
        "agents": build_active_agent_summary(scenario_doc, caldera_doc, cfg),
        "mirror": build_mirror_summary(stated),
        "snapshots": build_snapshot_summary(stated, scenario_doc),
        "state_files": state_files,
        "stale_warnings": detect_stale_runtime_warnings(scenario_doc, caldera_doc, stated),
        "last_jsonl_event": summarize_last_jsonl_event(tail_rows),
        "last_error": scenario_doc.get("last_error"),
    }


def build_runtime_inspect_report(
    xdr_root: Path, stated: Path, cfg: dict[str, Any], log_path: Path | None
) -> dict[str, Any]:
    summary = build_runtime_quick_summary(xdr_root, stated, cfg, log_path, refresh=True)
    scenario_doc = load_json(stated / "scenario.json", default_scenario_doc())
    caldera_doc = load_json(stated / "caldera.json", default_caldera_doc(cfg))
    nat_doc = load_nat_state_doc(stated)
    return {
        "summary": summary,
        "scenario_json": scenario_doc if isinstance(scenario_doc, dict) else {},
        "caldera_json": caldera_doc if isinstance(caldera_doc, dict) else {},
        "mirror_json": load_mirror_doc(stated),
        "nat_json": nat_doc,
        "snapshots_json": load_snapshots_catalog_doc(stated),
        "troubleshooting_hints": build_operator_troubleshooting_hints_for_status(
            scenario_doc if isinstance(scenario_doc, dict) else {},
            caldera_doc if isinstance(caldera_doc, dict) else {},
            stated,
            cfg,
        ),
        "jsonl_tail_10": read_jsonl_tail(log_path, lines=10) if log_path else [],
    }


def build_operation_status_report(
    xdr_root: Path,
    stated: Path,
    cfg: dict[str, Any],
    log_path: Path | None,
) -> dict[str, Any]:
    scenario_doc, caldera_doc = refresh_state(xdr_root, stated, cfg, log_path=log_path)
    op_id = str(caldera_doc.get("active_caldera_operation_id") or "").strip()
    server_state = None
    base_url = str(cfg.get("base_url") or "http://127.0.0.1:8888")
    api_key = resolve_api_key(cfg)
    if op_id and api_key.strip() and bool(caldera_doc.get("http_reachable")):
        client = CalderaClient(base_url, api_key)
        server_state, _row = find_operation_row_by_id(client, op_id, log_path)
    cal = scenario_doc.get("caldera") if isinstance(scenario_doc.get("caldera"), dict) else {}
    llr = scenario_doc.get("last_live_run") if isinstance(scenario_doc.get("last_live_run"), dict) else {}
    llr_op = llr.get("caldera_operation") if isinstance(llr.get("caldera_operation"), dict) else {}
    recent_jsonl = filter_jsonl_rows(
        read_jsonl_tail(log_path, lines=80) if log_path else [],
        r"scenario_live_run|scenario_operation|snapshot_before|preflight",
    )
    return {
        "generated_utc": utc_now(),
        "scenario_status": scenario_doc.get("status"),
        "active_operation_id": op_id or cal.get("operation_id") or llr_op.get("operation_id"),
        "active_operation_name": caldera_doc.get("active_caldera_operation_name") or cal.get("operation_name"),
        "server_reported_state": server_state or cal.get("server_reported_state") or llr_op.get("server_reported_state"),
        "last_live_run": llr,
        "last_history": scenario_doc.get("last_history"),
        "recent_jsonl_events": [r.get("event") for r in recent_jsonl[-15:]],
        "stale_warnings": detect_stale_runtime_warnings(scenario_doc, caldera_doc, stated),
    }


def build_repeat_run_validation_report(
    xdr_root: Path, stated: Path, cfg: dict[str, Any], log_path: Path | None
) -> dict[str, Any]:
    summary = build_runtime_quick_summary(xdr_root, stated, cfg, log_path, refresh=True)
    checks: list[dict[str, Any]] = []

    def add_check(cid: str, ok: bool | None, detail: str) -> None:
        checks.append({"id": cid, "ok": ok, "detail": detail})

    add_check(
        "caldera_http_reachable",
        bool(summary.get("http_reachable")),
        f"http_reachable={summary.get('http_reachable')} base_url={summary.get('base_url')}",
    )
    agents = summary.get("agents") if isinstance(summary.get("agents"), dict) else {}
    disconnected = agents.get("disconnected") if isinstance(agents.get("disconnected"), list) else []
    add_check(
        "sandcat_matrix",
        len(disconnected) == 0 if agents else None,
        f"connected={agents.get('connected')} disconnected={disconnected}",
    )
    mir = summary.get("mirror") if isinstance(summary.get("mirror"), dict) else {}
    add_check(
        "mirror_consistent",
        bool(mir.get("consistent")) if mir.get("present") else None,
        f"mirror.json present={mir.get('present')} consistent={mir.get('consistent')}",
    )
    nat = load_nat_state_doc(stated)
    add_check(
        "nat_consistent",
        bool(nat.get("consistent")) if (stated / "nat.json").is_file() else None,
        f"nat.json consistent={nat.get('consistent')}",
    )
    stale = summary.get("stale_warnings") if isinstance(summary.get("stale_warnings"), list) else []
    add_check("no_stale_warnings", len(stale) == 0, f"stale_warning_count={len(stale)}")
    st = str(summary.get("scenario_status") or "").lower()
    add_check(
        "scenario_not_blocked",
        st not in ("blocked", "failed"),
        f"scenario_status={summary.get('scenario_status')} last_error={summary.get('last_error')}",
    )
    ok_flags = [c.get("ok") for c in checks if c.get("ok") is not None]
    return {
        "generated_utc": utc_now(),
        "ok": all(ok_flags) if ok_flags else False,
        "checks": checks,
        "stale_warnings": stale,
        "guidance": [
            "Re-run `lab scenario run <id> --snapshot-before --dry-run` before a second live run.",
            "Archive JSONL + runtime/state per docs/runtime-evidence-collection.md between runs.",
        ],
    }


def build_cleanup_verification_report(
    scenario: dict[str, Any], caldera: dict[str, Any], stated: Path
) -> dict[str, Any]:
    st = str(scenario.get("status") or "").strip().lower()
    op_id = str(caldera.get("active_caldera_operation_id") or "").strip()
    agents = scenario.get("agents") if isinstance(scenario.get("agents"), dict) else {}
    still_connected = [k for k, v in agents.items() if v]
    items = [
        {
            "id": "scenario_terminal",
            "ok": st in ("idle", "stopped", "dry_run") and not op_id,
            "detail": f"status={st!r} active_caldera_operation_id={op_id or '(empty)'}",
        },
        {
            "id": "cleanup_recommended_flag",
            "ok": scenario.get("cleanup_recommended") is not True,
            "detail": f"cleanup_recommended={scenario.get('cleanup_recommended')}",
        },
        {
            "id": "agents_still_matched",
            "ok": len(still_connected) == 0,
            "detail": f"connected_roles={still_connected or '(none)'}",
        },
    ]
    ok_flags = [bool(x.get("ok")) for x in items]
    return {
        "generated_utc": utc_now(),
        "ok": all(ok_flags),
        "items": items,
        "hints": [
            "Run `lab scenario stop` if an operation id is still active.",
            "Optional: `lab scenario agent remove` when the next exercise needs a clean CALDERA matrix.",
        ],
    }


def build_mirror_snapshot_consistency_report(stated: Path, scenario: dict[str, Any]) -> dict[str, Any]:
    mir = load_mirror_doc(stated)
    snap = load_snapshots_catalog_doc(stated)
    snap_name = str(scenario.get("snapshot_before_name") or "").strip()
    name_in_catalog = False
    if snap_name and isinstance(snap.get("per_vm"), dict):
        for row in snap["per_vm"].values():
            if not isinstance(row, dict):
                continue
            names = row.get("snapshots") if isinstance(row.get("snapshots"), list) else row.get("names")
            if isinstance(names, list) and snap_name in names:
                name_in_catalog = True
                break
            if isinstance(row.get("snapshot_names"), list) and snap_name in row["snapshot_names"]:
                name_in_catalog = True
                break
    return {
        "generated_utc": utc_now(),
        "mirror": {
            "present": (stated / "mirror.json").is_file(),
            "consistent": mir.get("consistent"),
            "mirror_exists": mir.get("mirror_exists"),
            "output_port_matches_sensor": mir.get("output_port_matches_sensor"),
        },
        "snapshots": {
            "catalog_present": (stated / "snapshots.json").is_file(),
            "scenario_snapshot_before_name": snap_name or None,
            "snapshot_name_seen_in_catalog": name_in_catalog if snap_name else None,
            "updated_utc": snap.get("updated_utc"),
        },
        "ok": (
            mir.get("consistent") is not False
            and ((not snap_name) or name_in_catalog or not (stated / "snapshots.json").is_file())
        ),
    }


def operator_capture_guidance_lines() -> list[str]:
    return [
        "Capture UTC window start/stop next to every PCAP or screenshot.",
        "Redact API keys before attaching logs to external tickets.",
        "Copy logs/caldera-orchestration.jsonl before rotation (copy before truncate).",
        "Include CALDERA UI Operations + Agents screenshots with operation id visible.",
        "Run `lab runtime evidence bundle` to assemble a starter directory tree.",
        "See docs/runtime-evidence-collection.md for the full operator workflow.",
    ]


def generate_evidence_bundle(xdr_root: Path, stated: Path, out_dir: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    import shutil

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bundle_root = out_dir / f"xdr-lab-evidence-{ts}"
    bundle_root.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []

    def _copy_if_exists(src: Path, dest_name: str | None = None) -> None:
        if not src.is_file():
            return
        dest = bundle_root / (dest_name or src.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(str(dest.relative_to(bundle_root)))

    log_path = xdr_root / "logs" / "caldera-orchestration.jsonl"
    _copy_if_exists(log_path)
    _copy_if_exists(xdr_root / "logs" / "vm-manager.log")
    state_dest = bundle_root / "runtime-state"
    state_dest.mkdir(parents=True, exist_ok=True)
    for name in ("scenario.json", "caldera.json", "mirror.json", "nat.json", "snapshots.json"):
        _copy_if_exists(stated / name, f"runtime-state/{name}")

    guidance_path = bundle_root / "operator-capture-guidance.txt"
    guidance_path.write_text("\n".join(operator_capture_guidance_lines()) + "\n", encoding="utf-8")
    copied.append("operator-capture-guidance.txt")

    summary = build_runtime_quick_summary(xdr_root, stated, cfg, log_path, refresh=False)
    manifest_path = bundle_root / "bundle-manifest.json"
    manifest = {
        "created_utc": utc_now(),
        "bundle_dir": str(bundle_root),
        "xdr_root": str(xdr_root),
        "files_copied": copied,
        "runtime_summary": summary,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "bundle_dir": str(bundle_root),
        "files_copied": copied,
        "manifest": str(manifest_path),
    }


def export_jsonl_helper(
    log_path: Path,
    out_path: Path | None,
    *,
    lines: int = 500,
    pattern: str | None = None,
) -> dict[str, Any]:
    rows = read_jsonl_tail(log_path, lines=lines)
    rows = filter_jsonl_rows(rows, pattern)
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        dest = str(out_path)
    else:
        dest = "(stdout)"
        sys.stdout.write(text)
    return {
        "ok": True,
        "source": str(log_path),
        "destination": dest,
        "line_count": len(rows),
        "filter": pattern,
    }


def print_runtime_summary_human(report: dict[str, Any]) -> None:
    print("=== lab runtime summary ===")
    print(f"generated_utc: {report.get('generated_utc')}")
    print(f"scenario_status: {report.get('scenario_status')}  scenario: {report.get('scenario_name') or '-'}")
    print(f"run_id: {report.get('run_id') or '-'}")
    print(f"operation_id: {report.get('operation_id') or '-'}  name: {report.get('operation_name') or '-'}")
    print(
        f"CALDERA http_reachable: {'yes' if report.get('http_reachable') else 'no'}  "
        f"base_url: {report.get('base_url') or '-'}"
    )
    agents = report.get("agents") if isinstance(report.get("agents"), dict) else {}
    print(
        "Sandcat matrix: "
        + ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in (agents.get("matrix") or {}).items())
    )
    mir = report.get("mirror") if isinstance(report.get("mirror"), dict) else {}
    print(
        f"mirror: present={mir.get('present')} consistent={mir.get('consistent')} "
        f"mirror_exists={mir.get('mirror_exists')} sensor={mir.get('sensor_vm')!r}"
    )
    snap = report.get("snapshots") if isinstance(report.get("snapshots"), dict) else {}
    print(
        f"snapshots: catalog_present={snap.get('present')} total_count={snap.get('total_snapshot_count')} "
        f"last_batch_name={snap.get('scenario_snapshot_before_name') or '-'}"
    )
    last = report.get("last_jsonl_event")
    if isinstance(last, dict):
        print(
            f"last JSONL: ts={last.get('ts')} event={last.get('event')} "
            f"summary={str(last.get('summary') or '')[:120]}"
        )
    else:
        print("last JSONL: (no events)")
    stale = report.get("stale_warnings") if isinstance(report.get("stale_warnings"), list) else []
    if stale:
        print("")
        print("[stale runtime warnings]")
        for w in stale:
            if isinstance(w, dict):
                print(f"  - [{w.get('code')}] {w.get('message')}")
    if report.get("last_error"):
        print("")
        print(f"last_error: {report.get('last_error')}")


def print_dry_run_runtime_preview(
    *,
    rs: ResolvedScenario,
    target_vms: list[str],
    snapshot_before: bool,
    snap_name: str | None,
    op_name: str,
    adversary_id: Any,
    pf: dict[str, Any],
) -> None:
    """Additive dry-run block: expected on-disk artifacts without mutation."""
    print("")
    print("=== DRY-RUN: expected runtime/state preview (not written) ===")
    preview_state = {
        "status": "dry_run",
        "scenario_name": rs.scenario_id,
        "current_operation": rs.scenario_id,
        "target_vms": target_vms,
        "snapshot_before": snapshot_before,
        "snapshot_before_name": snap_name if snapshot_before else None,
        "snapshot_before_result": "dry_run_skipped" if snapshot_before else "skipped",
        "caldera": {
            "operation_name": op_name,
            "operation_id": None,
            "adversary_id": str(adversary_id),
        },
    }
    print(json.dumps(preview_state, indent=2, ensure_ascii=False))
    print("")
    print("=== DRY-RUN: expected JSONL events (illustrative sequence) ===")
    for ev in (
        "scenario_preflight_started",
        "scenario_preflight_completed",
        "scenario_run_ready",
        "snapshot_before_requested",
        "scenario_operation_started",
        "scenario_operation_completed",
    ):
        summ = jsonl_event_summary(ev, {"scenario": rs.scenario_id, "dry_run": True})
        print(f"  - {ev}: {summ or '(no summary)'}")
    print("")
    print("=== DRY-RUN: expected CALDERA actions preview ===")
    print("  live run would: PUT /api/rest index=operations (skipped in dry-run)")
    print("  snapshot-before would: vm-manager snapshot create (skipped in dry-run)")
    blocks = pf.get("blocking") if isinstance(pf.get("blocking"), list) else []
    if blocks:
        print("")
        print("[dry-run preflight blocks that would stop a live run]")
        for b in blocks:
            if isinstance(b, dict):
                print(f"  - [{b.get('code')}] {b.get('message')}")


def cmd_runtime_summary(
    xdr_root: Path, stated: Path, cfg: dict[str, Any], log_path: Path | None, *, json_out: bool
) -> int:
    report = build_runtime_quick_summary(xdr_root, stated, cfg, log_path, refresh=True)
    if json_out:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_runtime_summary_human(report)
    return 0


def cmd_runtime_inspect(
    xdr_root: Path, stated: Path, cfg: dict[str, Any], log_path: Path | None, *, json_out: bool
) -> int:
    report = build_runtime_inspect_report(xdr_root, stated, cfg, log_path)
    if json_out:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_runtime_summary_human(report.get("summary") or {})
        hints = report.get("troubleshooting_hints") or []
        if hints:
            print("")
            print("[troubleshooting hints]")
            for h in hints:
                print(f"  - {h}")
    return 0


def cmd_runtime_jsonl_tail(
    log_path: Path | None, *, lines: int, pattern: str | None, json_out: bool
) -> int:
    if not log_path or not log_path.is_file():
        print("caldera-orchestration.jsonl not found — run a scenario command first.", file=sys.stderr)
        return 1
    rows = filter_jsonl_rows(read_jsonl_tail(log_path, lines=lines), pattern)
    if json_out:
        print(json.dumps({"events": rows, "count": len(rows)}, indent=2, ensure_ascii=False))
        return 0
    for row in rows:
        ev = row.get("event")
        ts = row.get("ts")
        summ = row.get("summary") or jsonl_event_summary(str(ev or ""), row) or ""
        print(f"{ts}  {ev}  {summ}")
    return 0


def cmd_runtime_operation(
    xdr_root: Path, stated: Path, cfg: dict[str, Any], log_path: Path | None, *, json_out: bool
) -> int:
    report = build_operation_status_report(xdr_root, stated, cfg, log_path)
    if json_out:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    print("=== lab runtime operation ===")
    print(f"scenario_status: {report.get('scenario_status')}")
    print(f"active_operation_id: {report.get('active_operation_id') or '-'}")
    print(f"active_operation_name: {report.get('active_operation_name') or '-'}")
    print(f"server_reported_state: {report.get('server_reported_state') or '-'}")
    evs = report.get("recent_jsonl_events") or []
    if evs:
        print("recent JSONL events: " + ", ".join(str(x) for x in evs))
    return 0


def cmd_runtime_mirror(stated: Path, *, json_out: bool) -> int:
    report = build_mirror_summary(stated)
    if json_out:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    print("=== lab runtime mirror ===")
    for k in (
        "present",
        "consistent",
        "mirror_exists",
        "output_port_matches_sensor",
        "bridge",
        "mirror_name",
        "sensor_vm",
        "sensor_interface",
        "output_port_name",
        "last_verified_time",
        "age_hours",
    ):
        print(f"  {k}: {report.get(k)}")
    return 0


def cmd_runtime_snapshots(stated: Path, scenario: dict[str, Any] | None = None, *, json_out: bool) -> int:
    scen = scenario if isinstance(scenario, dict) else load_json(stated / "scenario.json", default_scenario_doc())
    report = build_snapshot_summary(stated, scen if isinstance(scen, dict) else {})
    if json_out:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    print("=== lab runtime snapshots (inventory) ===")
    print(f"catalog_present: {report.get('present')}  updated_utc: {report.get('updated_utc')}")
    for row in report.get("per_vm") or []:
        if isinstance(row, dict):
            print(f"  - {row.get('vm')}: snapshots={row.get('snapshot_count')}")
    print(f"scenario snapshot_before_name: {report.get('scenario_snapshot_before_name') or '-'}")
    return 0


def cmd_runtime_evidence_bundle(
    xdr_root: Path, stated: Path, cfg: dict[str, Any], out_dir: Path
) -> int:
    result = generate_evidence_bundle(xdr_root, stated, out_dir, cfg)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("")
    print("Operator capture guidance:")
    for line in operator_capture_guidance_lines():
        print(f"  - {line}")
    return 0


def cmd_runtime_evidence_export_jsonl(
    log_path: Path | None, out_path: Path | None, *, lines: int, pattern: str | None
) -> int:
    if not log_path or not log_path.is_file():
        print("caldera-orchestration.jsonl not found.", file=sys.stderr)
        return 1
    result = export_jsonl_helper(log_path, out_path, lines=lines, pattern=pattern)
    if out_path is None:
        return 0
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_runtime_validate(
    xdr_root: Path,
    stated: Path,
    cfg: dict[str, Any],
    log_path: Path | None,
    kind: str,
    *,
    json_out: bool,
) -> int:
    scenario_doc = load_json(stated / "scenario.json", default_scenario_doc())
    caldera_doc = load_json(stated / "caldera.json", default_caldera_doc(cfg))
    if kind == "repeat":
        report = build_repeat_run_validation_report(xdr_root, stated, cfg, log_path)
    elif kind == "stale":
        warnings = detect_stale_runtime_warnings(
            scenario_doc if isinstance(scenario_doc, dict) else {},
            caldera_doc if isinstance(caldera_doc, dict) else {},
            stated,
        )
        report = {"generated_utc": utc_now(), "stale_warnings": warnings, "ok": len(warnings) == 0}
    elif kind == "cleanup":
        report = build_cleanup_verification_report(
            scenario_doc if isinstance(scenario_doc, dict) else {},
            caldera_doc if isinstance(caldera_doc, dict) else {},
            stated,
        )
    elif kind == "consistency":
        report = build_mirror_snapshot_consistency_report(
            stated, scenario_doc if isinstance(scenario_doc, dict) else {}
        )
    else:
        print(f"Unknown runtime validate kind: {kind!r}", file=sys.stderr)
        return 2
    if json_out:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if bool(report.get("ok", True)) else 1


def cmd_runtime_preview(
    xdr_root: Path,
    stated: Path,
    cfg: dict[str, Any],
    log_path: Path | None,
    scenario_name: str | None,
    *,
    snapshot_before: bool,
    json_out: bool,
) -> int:
    reg, warns = build_scenario_registry(xdr_root, cfg)
    for w in warns:
        print(f"[warn] {w}", file=sys.stderr)
    name = scenario_name or str(
        load_json(stated / "scenario.json", {}).get("current_operation")
        or load_json(stated / "scenario.json", {}).get("scenario_name")
        or "recon"
    )
    if name not in reg:
        print(f"Unknown scenario {name!r}. Use `scenario list`.", file=sys.stderr)
        return 2
    rs = reg[name]
    target_vms = rs.target_vms if rs.target_vms else agent_vm_roles(cfg)
    pf = collect_scenario_run_preflight(
        xdr_root,
        stated,
        cfg,
        scenario_name=name,
        run_id="preview",
        rs=rs,
        target_vms=target_vms,
        snapshot_before=snapshot_before,
        is_dry=True,
        log_path=None,
    )
    op_name = format_scenario_operation_name(name)
    adv = rs.adversary_id or "DRY-RUN-PLACEHOLDER"
    snap_nm = proposed_snapshot_before_name() if snapshot_before else None
    if json_out:
        print(
            json.dumps(
                {
                    "preflight": pf,
                    "expected_state": {
                        "status": "dry_run",
                        "scenario_name": name,
                        "snapshot_before_name": snap_nm,
                    },
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    print_scenario_run_preflight_stdout(
        pf,
        operation_name=op_name,
        adversary_id=adv,
        group=rs.group,
        planner=rs.planner,
        target_vms=target_vms,
        snapshot_before=snapshot_before,
        snapshot_name=snap_nm,
        rs=rs,
        is_dry=True,
    )
    print_dry_run_runtime_preview(
        rs=rs,
        target_vms=target_vms,
        snapshot_before=snapshot_before,
        snap_name=snap_nm,
        op_name=op_name,
        adversary_id=adv,
        pf=pf,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="MITRE CALDERA lab orchestration.")
    p.add_argument("--xdr-root", default=os.environ.get("XDR_BASE") or os.environ.get("XDR_ROOT") or "/opt/xdr-lab")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List configured scenarios + refresh state")
    pst_sc = sub.add_parser(
        "status",
        help="Print scenario.json + caldera.json (JSON). --human adds post-run review + last_live_run when present",
    )
    pst_sc.add_argument(
        "--human",
        action="store_true",
        help="Human-readable operator summary (does not emit JSON)",
    )

    pr = sub.add_parser(
        "run",
        help="Start CALDERA operation; live path persists last_live_run + scenario_live_run_* JSONL (see docs)",
    )
    pr.add_argument(
        "scenario",
        metavar="NAME",
        help="Scenario id (scenarios/*.json pack scenario_id or caldera-lab.json key)",
    )
    pr.add_argument(
        "--snapshot-before",
        action="store_true",
        help="Run libvirt batch snapshot on lab VMs before CALDERA operation (see runtime/state/scenario.json snapshot_before_*)",
    )
    pr.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip CALDERA PUT and libvirt snapshot (same effect as XDR_LAB_DRY_RUN=1 for this command)",
    )

    sub.add_parser(
        "stop",
        help="POST CALDERA operation finished; stderr summary; updates last_live_run.completed_at when run_id matches",
    )

    ptel = sub.add_parser(
        "telemetry",
        help="Operator telemetry review: expected_telemetry + log-source hints (no auto-verdict)",
    )
    ptel.add_argument(
        "ref",
        metavar="NAME|last|verify",
        help="'last' = scenario.json::last_history; 'verify' = future auto-correlation placeholder (unless scenario_id=verify exists); else scenario_id",
    )
    ptel.add_argument(
        "--json",
        action="store_true",
        help="Emit structured telemetry review JSON",
    )
    ptel.add_argument(
        "--dry-run",
        action="store_true",
        help="For `telemetry verify` only: annotate placeholder output; no-op for checklist (`telemetry <id|last>`)",
    )

    ppack = sub.add_parser("pack", help="Scenario pack file utilities")
    ppack_sub = ppack.add_subparsers(dest="pack_cmd", required=True)
    pval = ppack_sub.add_parser("validate", help="Validate scenario pack files (schema + lab-vms + telemetry fields)")
    pval.add_argument(
        "--json",
        action="store_true",
        help="Emit validation report as JSON (stdout only)",
    )

    pboot = sub.add_parser("bootstrap", help="CALDERA + Atomic Red Team bootstrap preflight")
    pboot_sub = pboot.add_subparsers(dest="bootstrap_cmd", required=True)
    pbval = pboot_sub.add_parser(
        "validate",
        help="Probe CALDERA base_url, API key, plugins/atomic, ART paths, repo bootstrap scripts",
    )
    pbval.add_argument(
        "--json",
        action="store_true",
        help="Emit validation report as JSON (stdout only)",
    )

    pat = sub.add_parser("atomic", help="Atomic Red Team guest readiness (victim-linux / windows-victim)")
    pat_sub = pat.add_subparsers(dest="atomic_cmd", required=True)
    paval = pat_sub.add_parser(
        "validate",
        help="SSH checks on VMs: ART repo, atomics, Linux bash/python3, Windows PowerShell+Invoke-AtomicRedTeam",
    )
    paval.add_argument(
        "--json",
        action="store_true",
        help="Emit validation report as JSON (stdout only)",
    )

    pag = sub.add_parser("agent", help="CALDERA Sandcat agent helpers")
    pas = pag.add_subparsers(dest="agent_cmd", required=True)
    pstat = pas.add_parser("status", help="Show CALDERA agent matrix (human-friendly; use --json for legacy)")
    pstat.add_argument("--json", action="store_true", help="Emit scenario agents JSON only")
    pver = pas.add_parser("verify", help="Verify every configured lab role has a visible Sandcat agent")
    pver.add_argument("--json", action="store_true", help="Emit verification JSON")
    pade = pas.add_parser("deploy", help="Write bootstrap scripts and deploy to lab VMs (SSH / Windows paths)")
    pade.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate + write bootstrap; skip remote execution (also respects XDR_LAB_DRY_RUN)",
    )
    pas.add_parser("remove", help="DELETE agents matched to lab VM roles")

    prt = sub.add_parser("runtime", help="Live runtime visibility, inspection, evidence (read-only)")
    prt_sub = prt.add_subparsers(dest="runtime_cmd", required=True)
    prt_sum = prt_sub.add_parser("summary", help="Quick live runtime summary (operation, agents, mirror, JSONL)")
    prt_sum.add_argument("--json", action="store_true", help="Emit JSON summary")
    prt_ins = prt_sub.add_parser("inspect", help="Runtime state inspection with troubleshooting hints")
    prt_ins.add_argument("--json", action="store_true", help="Emit full inspect JSON")
    prt_j = prt_sub.add_parser("jsonl", help="JSONL tail helpers")
    prt_j_sub = prt_j.add_subparsers(dest="jsonl_cmd", required=True)
    prt_tail = prt_j_sub.add_parser("tail", help="Tail caldera-orchestration.jsonl")
    prt_tail.add_argument("--lines", type=int, default=30, help="Number of trailing lines (default 30)")
    prt_tail.add_argument("--filter", default=None, help="Regex filter across event JSON")
    prt_tail.add_argument("--json", action="store_true", help="Emit JSON array")
    prt_op = prt_sub.add_parser("operation", help="Active CALDERA operation status helper")
    prt_op.add_argument("--json", action="store_true")
    prt_mir = prt_sub.add_parser("mirror", help="Active mirror inspection (mirror.json)")
    prt_mir.add_argument("--json", action="store_true")
    prt_snap = prt_sub.add_parser("snapshots", help="Snapshot inventory inspection (snapshots.json)")
    prt_snap.add_argument("--json", action="store_true")
    prt_ev = prt_sub.add_parser("evidence", help="Runtime evidence helpers")
    prt_ev_sub = prt_ev.add_subparsers(dest="evidence_cmd", required=True)
    prt_bun = prt_ev_sub.add_parser("bundle", help="Generate troubleshooting/evidence bundle directory")
    prt_bun.add_argument(
        "--out",
        default=None,
        help="Parent output directory (default: ~/xdr-lab-evidence)",
    )
    prt_exp = prt_ev_sub.add_parser("export-jsonl", help="Export JSONL tail slice")
    prt_exp.add_argument("--out", default=None, help="Output file (default: stdout)")
    prt_exp.add_argument("--lines", type=int, default=500)
    prt_exp.add_argument("--filter", default=None, help="Regex filter")
    prt_val = prt_sub.add_parser("validate", help="Repeatability / stale / cleanup / consistency checks")
    prt_val_sub = prt_val.add_subparsers(dest="validate_cmd", required=True)
    for vk, help_txt in (
        ("repeat", "Repeat-run validation gates before a second live run"),
        ("stale", "Stale runtime artifact detection"),
        ("cleanup", "Post-run cleanup verification"),
        ("consistency", "Mirror + snapshot consistency checks"),
    ):
        pvk = prt_val_sub.add_parser(vk, help=help_txt)
        pvk.add_argument("--json", action="store_true")
    prt_prev = prt_sub.add_parser(
        "preview",
        help="Dry-run style preview of expected runtime/state + JSONL + CALDERA actions",
    )
    prt_prev.add_argument("scenario", nargs="?", default=None, help="scenario_id (default: last or recon)")
    prt_prev.add_argument("--snapshot-before", action="store_true")
    prt_prev.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    xdr_root = Path(args.xdr_root).resolve()
    stated = xdr_root / "runtime" / "state"
    stated.mkdir(parents=True, exist_ok=True)
    log_path = xdr_root / "logs" / "caldera-orchestration.jsonl"
    cfg = load_lab_config(xdr_root)

    cmd = args.cmd
    if cmd == "list":
        return cmd_list(cfg, stated, log_path)
    if cmd == "status":
        return cmd_status(cfg, stated, log_path, human=bool(getattr(args, "human", False)))
    if cmd == "run":
        return cmd_run(
            xdr_root,
            stated,
            cfg,
            args.scenario,
            bool(args.snapshot_before),
            log_path,
            cli_scenario_dry=bool(getattr(args, "dry_run", False)),
        )
    if cmd == "stop":
        return cmd_stop(xdr_root, stated, cfg, log_path)
    if cmd == "telemetry":
        return cmd_telemetry(
            xdr_root,
            stated,
            cfg,
            log_path,
            args.ref,
            json_out=bool(getattr(args, "json", False)),
            dry_run=bool(getattr(args, "dry_run", False)),
        )
    if cmd == "pack":
        if args.pack_cmd == "validate":
            return cmd_pack_validate(xdr_root, cfg, json_out=bool(getattr(args, "json", False)))
        return 2
    if cmd == "bootstrap":
        if args.bootstrap_cmd == "validate":
            return cmd_bootstrap_validate(
                xdr_root,
                stated,
                cfg,
                log_path,
                json_out=bool(getattr(args, "json", False)),
            )
        return 2
    if cmd == "atomic":
        if args.atomic_cmd == "validate":
            return cmd_atomic_validate(
                xdr_root,
                stated,
                cfg,
                log_path,
                json_out=bool(getattr(args, "json", False)),
            )
        return 2
    if cmd == "agent":
        ac = args.agent_cmd
        if ac == "status":
            return cmd_agent_status(
                cfg, stated, log_path, json_only=bool(getattr(args, "json", False))
            )
        if ac == "verify":
            return cmd_agent_verify(
                cfg, stated, log_path, json_only=bool(getattr(args, "json", False))
            )
        if ac == "deploy":
            return cmd_agent_deploy(
                xdr_root,
                cfg,
                stated,
                log_path,
                cli_dry_run=bool(getattr(args, "dry_run", False)),
            )
        if ac == "remove":
            return cmd_agent_remove(cfg, stated, log_path)
    if cmd == "runtime":
        rcmd = args.runtime_cmd
        if rcmd == "summary":
            return cmd_runtime_summary(
                xdr_root, stated, cfg, log_path, json_out=bool(getattr(args, "json", False))
            )
        if rcmd == "inspect":
            return cmd_runtime_inspect(
                xdr_root, stated, cfg, log_path, json_out=bool(getattr(args, "json", False))
            )
        if rcmd == "jsonl":
            if args.jsonl_cmd == "tail":
                return cmd_runtime_jsonl_tail(
                    log_path,
                    lines=int(getattr(args, "lines", 30) or 30),
                    pattern=getattr(args, "filter", None),
                    json_out=bool(getattr(args, "json", False)),
                )
            return 2
        if rcmd == "operation":
            return cmd_runtime_operation(
                xdr_root, stated, cfg, log_path, json_out=bool(getattr(args, "json", False))
            )
        if rcmd == "mirror":
            return cmd_runtime_mirror(stated, json_out=bool(getattr(args, "json", False)))
        if rcmd == "snapshots":
            return cmd_runtime_snapshots(stated, json_out=bool(getattr(args, "json", False)))
        if rcmd == "evidence":
            if args.evidence_cmd == "bundle":
                out_raw = getattr(args, "out", None)
                out_dir = Path(out_raw).expanduser() if out_raw else Path.home() / "xdr-lab-evidence"
                return cmd_runtime_evidence_bundle(xdr_root, stated, cfg, out_dir)
            if args.evidence_cmd == "export-jsonl":
                out_raw = getattr(args, "out", None)
                out_path = Path(out_raw).expanduser() if out_raw else None
                return cmd_runtime_evidence_export_jsonl(
                    log_path,
                    out_path,
                    lines=int(getattr(args, "lines", 500) or 500),
                    pattern=getattr(args, "filter", None),
                )
            return 2
        if rcmd == "validate":
            return cmd_runtime_validate(
                xdr_root,
                stated,
                cfg,
                log_path,
                str(args.validate_cmd),
                json_out=bool(getattr(args, "json", False)),
            )
        if rcmd == "preview":
            return cmd_runtime_preview(
                xdr_root,
                stated,
                cfg,
                log_path,
                getattr(args, "scenario", None),
                snapshot_before=bool(getattr(args, "snapshot_before", False)),
                json_out=bool(getattr(args, "json", False)),
            )
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
