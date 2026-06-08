"""DetectionAdapter interface contract tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from dsp.detection.base import DetectionAdapter
from dsp.detection.models import CorrelationContext, EvidencePack, S3Result, S3Status
from dsp.detection.providers.stellar import StellarAdapter


def test_detection_adapter_is_abstract():
    with pytest.raises(TypeError):
        DetectionAdapter()  # type: ignore[abstract]


def test_stellar_adapter_implements_interface():
    adapter = StellarAdapter()
    assert isinstance(adapter, DetectionAdapter)
    assert adapter.vendor_id == "stellar"
    assert hasattr(adapter, "collect_evidence")
    assert hasattr(adapter, "validate_detection")
    assert hasattr(adapter, "build_evidence_pack")


def test_adapter_methods_return_expected_types(tmp_path: Path):
    now = datetime.now(timezone.utc)
    context = CorrelationContext(
        run_id="20260605_iface01",
        scenario_id="dns_tunnel",
        time_window_start=now,
        time_window_end=now,
        source_ip="10.10.10.5",
        destination_ip="10.10.10.53",
        s2_decision="success",
    )
    adapter = StellarAdapter()

    evidence = adapter.collect_evidence(context)
    assert isinstance(evidence, EvidencePack)

    s3_result = adapter.validate_detection(context, evidence)
    assert isinstance(s3_result, S3Result)
    assert s3_result.status in S3Status

    out = adapter.build_evidence_pack(context, evidence, s3_result, tmp_path)
    assert out.is_dir()
    assert (out / "alerts.json").exists()
    assert (out / "analytics.json").exists()
    assert (out / "entities.json").exists()
    assert (out / "timeline.json").exists()
    assert (out / "evidence.md").exists()
    assert (out / "s3_result.json").exists()
