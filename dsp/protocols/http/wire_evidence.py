"""Optional wire-level HTTP evidence — exact bytes/fields sent, no detection inference."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from dsp.protocols.types import HttpRequest

_BODY_PREVIEW_LIMIT = 512


def body_preview(body: bytes | None, *, limit: int = _BODY_PREVIEW_LIMIT) -> str:
    """Return a UTF-8 preview of request body (empty when absent)."""
    if not body:
        return ""
    return body[:limit].decode("utf-8", errors="replace")


def build_wire_record(
    *,
    method: str,
    full_url: str,
    headers: dict[str, str] | None,
    body: bytes | None = None,
    content_type: str | None = None,
    response_code: int | None = None,
    target: str = "",
) -> dict[str, Any]:
    """Build one wire evidence line — exactly what was sent on the wire."""
    return {
        "method": method.upper(),
        "full_url": full_url,
        "headers": dict(headers) if headers else {},
        "body_preview": body_preview(body),
        "content_type": content_type or "",
        "response_code": response_code,
        "target": target,
    }


def build_wire_record_from_request(
    request: HttpRequest,
    *,
    response_code: int | None = None,
    target: str = "",
) -> dict[str, Any]:
    """Build wire evidence from an HttpRequest."""
    target_key = target or f"{request.host}:{request.port}"
    return build_wire_record(
        method=request.method,
        full_url=request.url,
        headers=request.headers,
        body=request.body,
        content_type=request.content_type,
        response_code=response_code,
        target=target_key,
    )


def write_wire_evidence_jsonl(path: Path, records: list[dict[str, Any]]) -> Path:
    """Write wire evidence records as JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def reconstruct_sqli_body(
    *,
    transport: str,
    parameter: str,
    payload: str,
) -> tuple[bytes | None, str | None]:
    """Reconstruct POST body for wire evidence when only transport metadata exists."""
    if transport == "form":
        return urlencode({parameter: payload}).encode("utf-8"), "application/x-www-form-urlencoded"
    if transport == "json":
        body = json.dumps({parameter: payload}).encode("utf-8")
        return body, "application/json"
    return None, None
