"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture
def tmp_runs_dir(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setenv("DSP_RUNS_DIR", str(runs))
    return runs
