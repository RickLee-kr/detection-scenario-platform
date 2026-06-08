"""DetectionManager orchestration tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from dsp.detection.manager import DetectionManager
from dsp.detection.models import S3Status
from dsp.detection.providers.stellar import StellarAdapter
from dsp.event_store import Event, EventStore, Run, RunStatus, ValidationDecision, ValidationResult


def _setup_run(store: EventStore, run_id: str, scenario_id: str) -> None:
    now = datetime.now(timezone.utc)
    store.open_run(run_id)
    for event_name in ("scenario_started", "scenario_completed"):
        store.append(
            Event(
                run_id=run_id,
                scenario_id=scenario_id,
                timestamp=now,
                stage="orchestrator",
                event=event_name,
                status="info",
            )
        )
    store.append(
        Event(
            run_id=run_id,
            scenario_id=scenario_id,
            timestamp=now,
            stage="executor",
            event=f"{scenario_id}_query_sent" if scenario_id == "dns_tunnel" else "traffic_sent",
            status="sent",
            target="10.10.10.53",
            evidence={"source_ip": "10.10.10.5", "destination_ip": "10.10.10.53"},
        )
    )


def test_manager_does_not_modify_validation_result(tmp_path: Path):
    run_id = "mgr_run01"
    store = EventStore(":memory:")
    _setup_run(store, run_id, "dns_tunnel")

    run = Run(
        run_id=run_id,
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
        status=RunStatus.COMPLETED,
    )
    vr = ValidationResult(
        run_id=run_id,
        scenario_id="dns_tunnel",
        decision=ValidationDecision.SUCCESS,
        reason="thresholds_met",
        metrics={"dns_tunnel_query_sent_count": 1},
        validated_at=datetime.now(timezone.utc),
    )
    original_decision = vr.decision

    manager = DetectionManager(store, [StellarAdapter()])
    results = manager.confirm_detection(run, [vr], output_dir=tmp_path)

    assert vr.decision == original_decision
    assert len(results) == 1
    assert results[0].status == S3Status.S3_CONFIRMED


def test_manager_skips_poll_when_s2_not_success():
    run_id = "mgr_skip01"
    store = EventStore(":memory:")
    _setup_run(store, run_id, "dga")

    run = Run(run_id=run_id, status=RunStatus.COMPLETED)
    vr = ValidationResult(
        run_id=run_id,
        scenario_id="dga",
        decision=ValidationDecision.FAILED,
        reason="thresholds_not_met",
        metrics={},
        validated_at=datetime.now(timezone.utc),
    )

    manager = DetectionManager(store, [StellarAdapter()])
    results = manager.confirm_detection(run, [vr])

    assert results[0].status == S3Status.S3_INCONCLUSIVE
    assert results[0].evidence_count == 0


def test_manager_writes_s3_result_json(tmp_path: Path):
    run_id = "mgr_write01"
    store = EventStore(":memory:")
    _setup_run(store, run_id, "http_followup")

    run = Run(
        run_id=run_id,
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
        status=RunStatus.COMPLETED,
    )
    vr = ValidationResult(
        run_id=run_id,
        scenario_id="http_followup",
        decision=ValidationDecision.SUCCESS,
        reason="thresholds_met",
        metrics={"http_request_sent_count": 1},
        validated_at=datetime.now(timezone.utc),
    )

    manager = DetectionManager(store, [StellarAdapter()])
    results = manager.confirm_detection(run, [vr], output_dir=tmp_path)
    path = manager.write_s3_results(tmp_path, results)

    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["run_id"] == run_id
    assert payload["vendor"] == "stellar"
    assert len(payload["results"]) == 1
