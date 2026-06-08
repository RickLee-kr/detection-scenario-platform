"""Webshell execution provider configuration — no global config system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dsp.execution.exceptions import WebshellExecutionConfigError
from dsp.execution.providers.webshell.provider_models import VALID_TRANSPORT_TYPES
from dsp.execution.webshell.transport.retry import RetryPolicy

SUPPORTED_WEBSHELL_FAMILIES = frozenset({"jsp", "php", "aspx"})


@dataclass
class WebshellExecutionConfig:
    """Declarative config for ``WebshellExecutionProvider`` instantiation."""

    provider_type: str
    webshell_url: str
    transport_type: str = "https"
    verify_tls: bool = True
    max_retries: int = 0
    enable_healthcheck_on_connect: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.provider_type = self.provider_type.strip().lower()
        self.transport_type = self.transport_type.strip().lower()
        if self.provider_type not in SUPPORTED_WEBSHELL_FAMILIES:
            raise WebshellExecutionConfigError(
                f"unsupported webshell family provider_type: {self.provider_type!r}",
                field="provider_type",
            )
        if not self.webshell_url:
            raise WebshellExecutionConfigError(
                "webshell_url is required",
                field="webshell_url",
            )
        if self.transport_type not in VALID_TRANSPORT_TYPES:
            raise WebshellExecutionConfigError(
                f"unsupported transport_type: {self.transport_type!r}",
                field="transport_type",
            )

    @property
    def retry_policy(self) -> RetryPolicy:
        return RetryPolicy(max_retries=self.max_retries)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebshellExecutionConfig:
        normalized = dict(data)
        if "provider_type" not in normalized and "webshell_family" in normalized:
            normalized["provider_type"] = normalized["webshell_family"]
        known = {
            "provider_type",
            "webshell_family",
            "webshell_url",
            "transport_type",
            "verify_tls",
            "max_retries",
            "enable_healthcheck_on_connect",
        }
        extra = {key: value for key, value in normalized.items() if key not in known}
        return cls(
            provider_type=str(normalized["provider_type"]),
            webshell_url=str(normalized["webshell_url"]),
            transport_type=str(normalized.get("transport_type", "https")),
            verify_tls=bool(normalized.get("verify_tls", True)),
            max_retries=int(normalized.get("max_retries", 0)),
            enable_healthcheck_on_connect=bool(
                normalized.get("enable_healthcheck_on_connect", False)
            ),
            extra=extra,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "provider_type": self.provider_type,
            "webshell_url": self.webshell_url,
            "transport_type": self.transport_type,
            "verify_tls": self.verify_tls,
            "max_retries": self.max_retries,
            "enable_healthcheck_on_connect": self.enable_healthcheck_on_connect,
        }
        payload.update(self.extra)
        return payload
