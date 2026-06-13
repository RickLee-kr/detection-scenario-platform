"""DSP CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dsp import __version__
from dsp.plugins import PluginLoader
from dsp.runner.run_manager import RunManager
from dsp.runtime.traffic_profiles import (
    PARITY_SCENARIO_BUNDLE,
    build_scenario_params_for_bundle,
    parse_traffic_profile,
)

def _print_http_followup_console(summary_path: Path) -> None:
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    http = summary.get("scenarios", {}).get("http_followup")
    if not http:
        return
    reason = http.get("selected_http_target_reason")
    if reason:
        print(f"HTTP selected_http_target_reason: {reason}")
    dist = http.get("response_code_distribution") or {}
    if dist:
        dist_text = ", ".join(f"{code}={count}" for code, count in sorted(dist.items()))
        print(f"HTTP response_code_distribution: {dist_text}")
    if http.get("redirect_only_warning"):
        print(
            "WARN: HTTP URL scan responses are redirect-only — "
            "target may be unsuitable for URL/User-Agent detection parity"
        )
    abnormal = http.get("abnormal_user_agents")
    normal = http.get("normal_user_agents")
    if abnormal is not None and normal is not None:
        ratio = http.get("abnormal_user_agent_ratio", 0.0)
        print(
            f"HTTP UA mix: abnormal_user_agents={abnormal} "
            f"normal_user_agents={normal} abnormal_user_agent_ratio={ratio}"
        )
    concentrated = http.get("concentrated_target")
    if concentrated:
        print(f"HTTP concentrated_target: {concentrated}")
    target_dist = http.get("target_distribution") or {}
    if target_dist:
        print(f"HTTP target_distribution: {target_dist}")


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
    run_parser.add_argument(
        "--scenarios",
        help="Comma-separated scenario IDs (default: parity bundle when --profile is set)",
    )
    run_parser.add_argument("--dry-run", action="store_true", help="Dry-run mode (no network)")
    run_parser.add_argument("--target-net", default="10.10.10.0/24", help="Target CIDR")
    run_parser.add_argument(
        "--profile",
        default="balanced",
        help="Traffic profile: low, normal, balanced, burst (default: balanced)",
    )
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
    run_parser.add_argument(
        "--execution-provider",
        default="local",
        choices=["local", "webshell"],
        help="Execution provider: local (in-process) or webshell (remote host).",
    )
    run_parser.add_argument(
        "--webshell-family",
        choices=["jsp", "php", "aspx"],
        help="Webshell family (required when --execution-provider=webshell).",
    )
    run_parser.add_argument(
        "--webshell-url",
        help="Webshell endpoint URL (required when --execution-provider=webshell).",
    )
    run_parser.add_argument(
        "--remote-work-dir",
        default="/tmp/dsp",
        help="Remote working directory for webshell bundle output (default: /tmp/dsp).",
    )
    run_parser.add_argument(
        "--verify-tls",
        action="store_true",
        help="Verify TLS certificates for webshell HTTP transport.",
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
        profile = parse_traffic_profile(args.profile)
        if args.scenarios:
            scenario_ids = [s.strip() for s in args.scenarios.split(",") if s.strip()]
        else:
            scenario_ids = list(PARITY_SCENARIO_BUNDLE)
        scenario_params = build_scenario_params_for_bundle(scenario_ids, profile)

        manager = RunManager()
        run, run_dir, exit_code = manager.run(
            scenario_ids=scenario_ids,
            target_net=args.target_net,
            dry_run=args.dry_run,
            scenario_params=scenario_params,
            traffic_profile=profile,
            confirm_detection=args.confirm_detection,
            detection_provider=args.detection_provider,
            stellar_client=args.stellar_client,
            execution_provider=args.execution_provider,
            webshell_family=args.webshell_family,
            webshell_url=args.webshell_url,
            remote_work_dir=args.remote_work_dir,
            verify_tls=args.verify_tls,
        )
        print(f"Run {run.run_id} status={run.status.value} dir={run_dir}")
        summary_path = run_dir / "traffic_summary.json"
        if summary_path.exists():
            print(f"Traffic summary: {summary_path}")
            _print_http_followup_console(summary_path)
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
