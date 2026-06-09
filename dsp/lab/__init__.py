"""DSP lab operational harness — traffic execution without detection validation."""

from dsp.lab.operational_runner import (
    LabRunResult,
    build_parser,
    run_from_args,
    run_local_lab,
    run_webshell_lab,
)

__all__ = [
    "LabRunResult",
    "build_parser",
    "run_from_args",
    "run_local_lab",
    "run_webshell_lab",
]
