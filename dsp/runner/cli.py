"""DSP CLI entry point."""

from __future__ import annotations

import argparse
import sys

from dsp import __version__
from dsp.plugins import PluginLoader
from dsp.runner.run_manager import RunManager

_DETECTION_EPILOG = """
Detection confirmation (S3) examples:

  # Manual S3 evidence pack (default — no Stellar API required):
  dsp run --scenarios dns_tunnel --confirm-detection

  # Offline mock Stellar client (CI / demo only):
  dsp run --scenarios dns_tunnel --confirm-detection --stellar-client mock

  # Experimental live Stellar HTTP client (optional, requires env vars):
  # See docs/experimental/STELLAR_HTTP_API_MODE.md
  export DSP_STELLAR_BASE_URL=https://stellar.lab.example
  export DSP_STELLAR_API_TOKEN=<token>
  dsp run --scenarios dns_tunnel --confirm-detection \\
    --detection-provider stellar --stellar-client http

S3 is optional and never changes S2 exit codes or ValidationResult.
Normal DSP operation does not require Stellar API tokens.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dsp", description="Detection Scenario Platform")
    parser.add_argument("--version", action="version", version=f"dsp {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Execute scenarios")
    run_parser.add_argument("--scenarios", required=True, help="Comma-separated scenario IDs")
    run_parser.add_argument("--dry-run", action="store_true", help="Dry-run mode (no network)")
    run_parser.add_argument("--target-net", default="10.10.10.0/24", help="Target CIDR")
    run_parser.add_argument(
        "--confirm-detection",
        action="store_true",
        help=(
            "Optional S3 detection confirmation after S2 validation. "
            "Default: manual evidence templates (no API). "
            "Does not affect exit code or ValidationResult."
        ),
    )
    run_parser.add_argument(
        "--detection-provider",
        default="stellar",
        help="Detection provider for --confirm-detection (default: stellar)",
    )
    run_parser.add_argument(
        "--stellar-client",
        default="manual",
        choices=["manual", "mock", "http"],
        help=(
            "S3 confirmation mode (default: manual). "
            "'manual' writes operator evidence templates (no API); "
            "'mock' uses deterministic local Stellar responses (CI/demo); "
            "'http' queries a live Stellar API (experimental — see docs/experimental/)."
        ),
    )
    run_parser.epilog = _DETECTION_EPILOG
    run_parser.formatter_class = argparse.RawDescriptionHelpFormatter

    plugins_parser = sub.add_parser("plugins", help="Plugin management")
    plugins_sub = plugins_parser.add_subparsers(dest="plugins_command", required=True)
    plugins_sub.add_parser("list", help="List discovered plugins")

    report_parser = sub.add_parser("report", help="Regenerate report from run artifacts")
    report_parser.add_argument("--run-id", required=True, help="Run ID to regenerate")

    args = parser.parse_args(argv)

    if args.command == "run":
        scenario_ids = [s.strip() for s in args.scenarios.split(",") if s.strip()]
        manager = RunManager()
        run, run_dir, exit_code = manager.run(
            scenario_ids=scenario_ids,
            target_net=args.target_net,
            dry_run=args.dry_run,
            confirm_detection=args.confirm_detection,
            detection_provider=args.detection_provider,
            stellar_client=args.stellar_client,
        )
        print(f"Run {run.run_id} status={run.status.value} dir={run_dir}")
        return exit_code

    if args.command == "plugins":
        if args.plugins_command == "list":
            loader = PluginLoader()
            registry = loader.discover_and_load()
            for record in registry.all():
                print(f"{record.id}\t{record.status.value}\t{record.status_reason or ''}")
            return 0

    if args.command == "report":
        manager = RunManager()
        path = manager.regenerate_report(args.run_id)
        print(f"Report regenerated: {path}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
