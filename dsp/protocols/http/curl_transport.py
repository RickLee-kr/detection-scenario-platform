"""Bash-parity HTTP transport via curl subprocess (http_followup only)."""

from __future__ import annotations

import re
import shutil
import subprocess
import uuid
from typing import Any

from dsp.protocols.types import HttpResponseResult

_CURL_WRITE_OUT = "%{http_code}|%{exitcode}"


def curl_available() -> bool:
    return shutil.which("curl") is not None


def build_curl_command(
    url: str,
    *,
    method: str = "GET",
    timeout: float = 2.0,
    headers: dict[str, str] | None = None,
    body: str | bytes | None = None,
    verify_tls: bool = False,
) -> list[str]:
    """
    Build argv for bash-equivalent curl invocation (stellar_poc_followup.sh do_req).

    Matches: curl -s -o /dev/null -w ... --max-time 2 -A ... -H ... URL
    """
    m = method.upper()
    cmd = [
        "curl",
        "-s",
        "-o",
        "/dev/null",
        "-w",
        _CURL_WRITE_OUT,
        "--max-time",
        str(max(1, int(timeout))),
    ]
    if url.lower().startswith("https://") and not verify_tls:
        cmd.append("-k")

    hdrs = dict(headers or {})
    user_agent = hdrs.pop("User-Agent", None)
    if user_agent:
        cmd.extend(["-A", user_agent])

    for key, value in hdrs.items():
        cmd.extend(["-H", f"{key}: {value}"])

    if m == "HEAD":
        cmd.append("-I")
    elif m == "POST":
        cmd.extend(["-X", "POST"])
        if body is not None:
            data = body.decode("utf-8") if isinstance(body, bytes) else body
            cmd.extend(["--data", data])
    elif m != "GET":
        cmd.extend(["-X", m])

    cmd.append(url)
    return cmd


def _parse_curl_output(raw: str) -> tuple[str, int]:
    line = (raw or "").strip().splitlines()[-1] if raw else ""
    parts = line.split("|")
    code = re.sub(r"\D", "", parts[0]) if parts else ""
    exit_code = 0
    if len(parts) > 1:
        try:
            exit_code = int(re.sub(r"\D", "", parts[1]) or "0")
        except ValueError:
            exit_code = 28
    if not code:
        code = "000"
    while len(code) < 3:
        code = f"0{code}"
    return code[:3], exit_code


def _outcome_from_curl(http_code: str, exit_code: int) -> str:
    if http_code != "000":
        return "response"
    if exit_code == 28:
        return "timeout"
    if exit_code == 7:
        return "connection_refused"
    if exit_code == 6:
        return "dns_failure"
    return "error"


def send_request_curl(
    url: str,
    *,
    method: str = "GET",
    timeout: float = 2.0,
    headers: dict[str, str] | None = None,
    body: str | bytes | None = None,
    verify_tls: bool = False,
) -> HttpResponseResult:
    """Execute one HTTP request via curl subprocess (bash parity)."""
    request_id = uuid.uuid4().hex[:8]
    evidence: dict[str, Any] = {
        "url": url,
        "method": method.upper(),
        "transport": "curl",
    }
    argv = build_curl_command(
        url,
        method=method,
        timeout=timeout,
        headers=headers,
        body=body,
        verify_tls=verify_tls,
    )
    evidence["curl_argv"] = argv

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout + 1.0,
            check=False,
        )
        raw = proc.stdout or ""
        http_code, curl_exit = _parse_curl_output(raw)
        if curl_exit == 0 and proc.returncode != 0 and http_code == "000":
            curl_exit = proc.returncode
        outcome = _outcome_from_curl(http_code, curl_exit)
        status_code = int(http_code) if http_code != "000" else None
        return HttpResponseResult(
            url=url,
            method=method.upper(),
            outcome=outcome,
            status_code=status_code,
            response_summary={
                "status_code": status_code,
                "curl_exit_code": curl_exit,
                "transport": "curl",
            },
            request_id=request_id,
            dry_run=False,
            evidence=evidence,
        )
    except subprocess.TimeoutExpired:
        return HttpResponseResult(
            url=url,
            method=method.upper(),
            outcome="timeout",
            response_summary={"message": "curl subprocess timeout"},
            request_id=request_id,
            dry_run=False,
            evidence=evidence,
        )
    except OSError as exc:
        return HttpResponseResult(
            url=url,
            method=method.upper(),
            outcome="error",
            response_summary={"message": str(exc)},
            request_id=request_id,
            dry_run=False,
            evidence=evidence,
        )
