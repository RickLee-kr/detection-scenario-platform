"""ExecutionProvider interface contract tests."""

from __future__ import annotations

import pytest

from dsp.execution.base import ExecutionProvider
from dsp.execution.local_provider import LocalExecutionProvider


def test_execution_provider_is_abstract():
    with pytest.raises(TypeError):
        ExecutionProvider()  # type: ignore[abstract]


def test_local_provider_implements_interface():
    provider = LocalExecutionProvider()
    assert isinstance(provider, ExecutionProvider)
    assert provider.provider_type == "local"
    assert hasattr(provider, "prepare")
    assert hasattr(provider, "execute")
    assert hasattr(provider, "cleanup")
    assert hasattr(provider, "capabilities")
