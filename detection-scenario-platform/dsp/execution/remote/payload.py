"""Remote scenario command payload encoding."""

from __future__ import annotations

import base64
import json
from typing import Any

from dsp.execution.providers.runtime.command import CommandRequest
from dsp.execution.remote.models import ScenarioExecutionRequest

REMOTE_SCENARIO_COMMAND = "dsp-remote-scenario"


def encode_scenario_payload(payload: dict[str, Any]) -> str:
    """Encode scenario JSON for webshell-safe command delivery (base64)."""
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


def decode_scenario_payload(argument: str) -> dict[str, Any]:
    """Decode a scenario payload from base64 or legacy raw JSON."""
    stripped = argument.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)
    return json.loads(base64.b64decode(stripped.encode("ascii")))


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
    encoded_payload = encode_scenario_payload(payload)
    return CommandRequest.new(
        REMOTE_SCENARIO_COMMAND,
        arguments=[encoded_payload],
        timeout_seconds=timeout_seconds,
    )
