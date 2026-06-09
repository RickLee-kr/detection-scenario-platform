"""Unit tests for dsp.lab.operational_runner."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dsp.lab import operational_runner
from dsp.runtime.traffic_profiles import build_scenario_params


def test_operational_runner_does_not_import_detection_modules() -> None:
    source = inspect.getsource(operational_runner)
    forbidden = ("detection", "validation", "correlation", "alert")
    for token in forbidden:
        assert f"dsp.{token}" not in source


def test_local_mode_passes_profile_parameters(tmp_path: Path) -> None:
    output_dir = tmp_path / "local-profile"
    scenario_params = build_scenario_params("dummy", "burst")

    with patch.object(operational_runner, "RunManager") as manager_cls:
        run_mock = MagicMock()
        run_mock.run_id = "20260609_abc123"
        run_mock.status.value = "completed"
        manager = manager_cls.return_value
        manager.run.return_value = (run_mock, output_dir / run_mock.run_id, 0)

        run_dir = output_dir / run_mock.run_id
        run_dir.mkdir(parents=True)
        (run_dir / "events.db").write_bytes(b"sqlite")

        with patch.object(operational_runner, "EventStore") as store_cls:
            store = store_cls.open_existing.return_value
            store.count.return_value = 12
            with patch.object(operational_runner, "_export_artifacts") as export:
                export.return_value = ([run_dir / "run_test.json"], {})
                result = operational_runner.run_local_lab(
                    scenario_id="dummy",
                    output_dir=output_dir,
                    target_net="10.10.10.0/24",
                    traffic_profile="burst",
                    dry_run=False,
                )

    manager.run.assert_called_once()
    call_kwargs = manager.run.call_args.kwargs
    assert call_kwargs["dry_run"] is False
    assert call_kwargs["scenario_params"] == scenario_params
    assert result.traffic_profile == "burst"
    assert result.event_count == 12


def test_local_mode_dummy_safe_with_dry_run(tmp_path: Path) -> None:
    output_dir = tmp_path / "local-dry"
    with patch.object(operational_runner, "RunManager") as manager_cls:
        run_mock = MagicMock()
        run_mock.run_id = "20260609_dryrun"
        run_mock.status.value = "completed"
        manager = manager_cls.return_value
        manager.run.return_value = (run_mock, output_dir / run_mock.run_id, 0)
        run_dir = output_dir / run_mock.run_id
        run_dir.mkdir(parents=True)
        (run_dir / "events.db").write_bytes(b"sqlite")

        with patch.object(operational_runner, "EventStore") as store_cls:
            store = store_cls.open_existing.return_value
            store.count.return_value = 3
            with patch.object(operational_runner, "_export_artifacts") as export:
                export.return_value = ([], {})
                operational_runner.run_local_lab(
                    scenario_id="dummy",
                    output_dir=output_dir,
                    target_net="10.10.10.0/24",
                    traffic_profile="low",
                    dry_run=True,
                )

    assert manager.run.call_args.kwargs["dry_run"] is True


def test_webshell_command_includes_profile_parameters() -> None:
    from dsp.execution.remote.payload import REMOTE_SCENARIO_COMMAND, build_scenario_command
    from dsp.execution.remote.models import ScenarioExecutionRequest
    from dsp.runtime.traffic_profiles import scenario_params_for_profile

    params = scenario_params_for_profile("dns_tunnel", "balanced")
    request = ScenarioExecutionRequest(
        scenario_id="dns_tunnel",
        scenario_params=params,
        run_id="dsp_lab_test",
        target_net="10.10.10.0/24",
        dry_run=False,
    )
    command = build_scenario_command(request)
    assert command.command == REMOTE_SCENARIO_COMMAND
    payload = json.loads(command.arguments[0])
    assert payload["scenario_params"]["traffic_profile"] == "balanced"
    assert payload["dry_run"] is False
    assert payload["scenario_id"] == "dns_tunnel"
