"""Documentation CLI example consistency tests."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATHS = [
    REPO_ROOT / "docs" / "runtime" / "EXECUTION_GUIDE.md",
    REPO_ROOT / "docs" / "runtime" / "ENVIRONMENT_VALIDATION.md",
    REPO_ROOT / "docs" / "runtime" / "LIVE_VALIDATION_CHECKLIST.md",
    REPO_ROOT.parent / "docs" / "catalog" / "CUSTOMER_DEMO_GUIDE.md",
    REPO_ROOT.parent / "docs" / "catalog" / "LAB_EXECUTION_RUNBOOK.md",
]


def test_runtime_docs_use_scenarios_flag_not_scenario():
    """Primary docs must use --scenarios (plural), not deprecated --scenario."""
    for doc_path in DOC_PATHS:
        if not doc_path.exists():
            continue
        content = doc_path.read_text(encoding="utf-8")
        assert "--scenario " not in content or "--scenarios" in content
        for line in content.splitlines():
            if "dsp run" in line and "--scenario " in line:
                assert "--scenarios" in line, f"{doc_path}: uses --scenario without --scenarios"


def test_execution_guide_shows_manual_confirm_detection():
    guide = (REPO_ROOT / "docs" / "runtime" / "EXECUTION_GUIDE.md").read_text(
        encoding="utf-8"
    )
    assert "dsp run --scenarios dns_tunnel --confirm-detection" in guide
    assert "manual" in guide.lower()
