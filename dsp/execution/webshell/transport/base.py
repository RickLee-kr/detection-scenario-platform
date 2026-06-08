"""WebshellTransport ABC and security validation wiring."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import urlparse

from dsp.execution.webshell.security import (
    WebshellSecurityPolicy,
    validate_download_allowed,
    validate_file_size_allowed,
    validate_remote_path_allowed,
    validate_upload_allowed,
)
from dsp.execution.webshell.transport.errors import WebshellTransportValidationError
from dsp.execution.webshell.transport.models import TransportRequest, TransportResponse

DEFAULT_BLOCKED_URL_SCHEMES = frozenset({"file", "gopher", "data"})
DEFAULT_FORBIDDEN_UPLOAD_PATHS = frozenset(
    {
        "/etc/",
        "/root/",
        "/var/www/html/",
        "/proc/",
        "/sys/",
    }
)


class WebshellTransport(ABC):
    """HTTP transport abstraction for webshell providers — no provider logic."""

    @abstractmethod
    def send_get(self, request: TransportRequest) -> TransportResponse:
        """Issue an HTTP GET through the transport layer."""

    @abstractmethod
    def send_post(self, request: TransportRequest) -> TransportResponse:
        """Issue an HTTP POST through the transport layer."""

    @abstractmethod
    def send_upload(
        self,
        request: TransportRequest,
        *,
        local_path: Path,
        remote_path: str,
    ) -> TransportResponse:
        """Upload a file via HTTP multipart or family-specific encoding."""

    @abstractmethod
    def download(
        self,
        request: TransportRequest,
        *,
        remote_path: str,
    ) -> TransportResponse:
        """Download remote file content via HTTP."""

    @abstractmethod
    def healthcheck(self, request: TransportRequest) -> TransportResponse:
        """Probe endpoint reachability without command execution."""


def validate_transport_url(
    policy: WebshellSecurityPolicy,
    url: str,
    *,
    blocked_url_patterns: frozenset[str] | None = None,
) -> None:
    """Reject blocked URL schemes and unsafe destinations."""
    parsed = urlparse(url.strip())
    if not parsed.scheme:
        raise WebshellTransportValidationError(
            f"url missing scheme: {url}",
            rule="url_scheme_required",
        )
    scheme = parsed.scheme.lower()
    if scheme in DEFAULT_BLOCKED_URL_SCHEMES:
        raise WebshellTransportValidationError(
            f"blocked url scheme: {scheme}",
            rule="blocked_url_scheme",
        )
    if scheme not in {"http", "https"}:
        raise WebshellTransportValidationError(
            f"unsupported url scheme: {scheme}",
            rule="allowed_url_scheme",
        )
    if policy.safe_mode:
        host = (parsed.hostname or "").lower()
        if host in {"127.0.0.1", "localhost", "::1"}:
            raise WebshellTransportValidationError(
                f"loopback url blocked in safe_mode: {url}",
                rule="safe_mode_loopback",
            )
    patterns = blocked_url_patterns or frozenset()
    lowered = url.lower()
    for pattern in patterns:
        if pattern.lower() in lowered:
            raise WebshellTransportValidationError(
                f"blocked url pattern matched: {pattern}",
                rule="blocked_url_pattern",
            )


def validate_transport_request(
    policy: WebshellSecurityPolicy,
    request: TransportRequest,
    *,
    blocked_url_patterns: frozenset[str] | None = None,
) -> None:
    """Validate a transport request against security policy before dispatch."""
    validate_transport_url(policy, request.url, blocked_url_patterns=blocked_url_patterns)
    if request.timeout_seconds <= 0:
        raise WebshellTransportValidationError(
            "timeout_seconds must be positive",
            rule="timeout_seconds",
        )


def validate_upload_transport(
    policy: WebshellSecurityPolicy,
    request: TransportRequest,
    *,
    local_path: Path,
    remote_path: str,
    forbidden_upload_paths: frozenset[str] | None = None,
    blocked_url_patterns: frozenset[str] | None = None,
) -> None:
    """Validate upload operation against security policy."""
    validate_transport_request(
        policy,
        request,
        blocked_url_patterns=blocked_url_patterns,
    )
    validate_upload_allowed(policy)
    validate_remote_path_allowed(policy, remote_path)
    _validate_forbidden_upload_path(remote_path, forbidden_upload_paths)
    if not local_path.exists():
        raise WebshellTransportValidationError(
            f"local file does not exist: {local_path}",
            rule="local_file_exists",
        )
    validate_file_size_allowed(policy, local_path.stat().st_size)


def validate_download_transport(
    policy: WebshellSecurityPolicy,
    request: TransportRequest,
    *,
    remote_path: str,
    blocked_url_patterns: frozenset[str] | None = None,
) -> None:
    """Validate download operation against security policy."""
    validate_transport_request(
        policy,
        request,
        blocked_url_patterns=blocked_url_patterns,
    )
    validate_download_allowed(policy)
    validate_remote_path_allowed(policy, remote_path)


def _validate_forbidden_upload_path(
    remote_path: str,
    forbidden_paths: frozenset[str] | None,
) -> None:
    normalized = _normalize_remote_path(remote_path)
    paths = forbidden_paths if forbidden_paths is not None else DEFAULT_FORBIDDEN_UPLOAD_PATHS
    for forbidden in paths:
        if normalized.startswith(forbidden):
            raise WebshellTransportValidationError(
                f"forbidden upload path: {remote_path}",
                rule="forbidden_upload_path",
            )


def _normalize_remote_path(remote_path: str) -> str:
    path = remote_path.strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return re.sub(r"/+", "/", path)
