"""User-Agent burst policy tests — bash url_scan parity."""

from __future__ import annotations

from dsp.protocols.http.user_agents import classify_user_agent, pick_burst_user_agent


def test_pick_burst_user_agent_never_normal_browser():
    samples = [pick_burst_user_agent() for _ in range(200)]
    assert not any(classify_user_agent(ua) == "normal" for ua in samples)


def test_pick_burst_user_agent_includes_bash_rare_strings():
    samples = {pick_burst_user_agent() for _ in range(500)}
    bash_rare = {"TelemetryCollector/9.7", "ReconEngine/5.4", "ThreatHunterAgent/8.2"}
    assert bash_rare & samples
