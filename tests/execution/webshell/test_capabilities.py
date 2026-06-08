"""WebshellCapabilities tests."""

from __future__ import annotations

from dsp.execution.webshell import WebshellCapabilities


def test_default_capabilities_are_false():
    caps = WebshellCapabilities()
    assert caps.supports_execute is False
    assert caps.supports_upload is False
    assert caps.supports_download is False
    assert caps.supports_chunked_upload is False
    assert caps.supports_get is False
    assert caps.supports_post is False
    assert caps.supports_authentication is False
    assert caps.family is None


def test_capabilities_roundtrip():
    original = WebshellCapabilities(
        supports_execute=True,
        supports_upload=True,
        supports_download=True,
        supports_chunked_upload=True,
        supports_get=True,
        supports_post=True,
        supports_authentication=True,
        family="aspx",
    )
    restored = WebshellCapabilities.from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()


def test_jsp_reference_capabilities():
    caps = WebshellCapabilities(
        supports_execute=True,
        supports_upload=True,
        supports_download=True,
        supports_post=True,
        supports_authentication=True,
        family="jsp",
    )
    assert caps.supports_execute
    assert caps.family == "jsp"
