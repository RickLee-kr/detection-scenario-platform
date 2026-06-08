"""Minimal Target Provider stub for Phase 1A."""

from __future__ import annotations

from dsp.engine.scenario_engine import TargetSet


def resolve_targets(target_net: str, required_capabilities: list[str] | None = None) -> TargetSet:
    """Return a stub TargetSet without network probing."""
    caps = {cap: True for cap in (required_capabilities or [])}
    caps.setdefault("alive_host", True)
    return TargetSet.stub(target_net=target_net)
