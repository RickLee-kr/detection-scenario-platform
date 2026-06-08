"""Webshell capability declarations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class WebshellCapabilities:
    """Transport and feature capabilities declared by a webshell family adapter."""

    supports_execute: bool = False
    supports_upload: bool = False
    supports_download: bool = False
    supports_chunked_upload: bool = False
    supports_get: bool = False
    supports_post: bool = False
    supports_authentication: bool = False
    family: str | None = None  # "jsp" | "php" | "aspx" | "generic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "supports_execute": self.supports_execute,
            "supports_upload": self.supports_upload,
            "supports_download": self.supports_download,
            "supports_chunked_upload": self.supports_chunked_upload,
            "supports_get": self.supports_get,
            "supports_post": self.supports_post,
            "supports_authentication": self.supports_authentication,
            "family": self.family,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebshellCapabilities:
        return cls(
            supports_execute=bool(data.get("supports_execute", False)),
            supports_upload=bool(data.get("supports_upload", False)),
            supports_download=bool(data.get("supports_download", False)),
            supports_chunked_upload=bool(data.get("supports_chunked_upload", False)),
            supports_get=bool(data.get("supports_get", False)),
            supports_post=bool(data.get("supports_post", False)),
            supports_authentication=bool(data.get("supports_authentication", False)),
            family=data.get("family"),
        )
