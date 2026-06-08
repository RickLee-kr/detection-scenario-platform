"""Remote scenario command payload encoding."""

from __future__ import annotations

import json

from dsp.execution.providers.runtime.command import CommandRequest
from dsp.execution.remote.models import ScenarioExecutionRequest

REMOTE_SCENARIO_COMMAND = "dsp-remote-scenario"


def build_scenario_command(
    request: ScenarioExecutionRequest,
    *,
    timeout_seconds: int = 300,
) -> CommandRequest:
    """Encode a scenario execution request as a remote command delivery payload."""
    payload = {
        "scenario_id": request.scenario_id,
        "scenario_params": request.scenario_params,
        "execution_metadata": request.execution_metadata,
        "run_id": request.run_id,
        "target_net": request.target_net,
        "dry_run": request.dry_run,
    }
    encoded_payload = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return CommandRequest.new(
        REMOTE_SCENARIO_COMMAND,
        arguments=[encoded_payload],
        timeout_seconds=timeout_seconds,
    )
