# DSP v1.2.1 Release Notes

**Version:** 1.2.1  
**Date:** 2026-06-09 (UTC)  
**Package:** `detection-scenario-platform` (`dsp`)

---

## Summary

DSP v1.2.1 fixes `--target-net` propagation so live scenario traffic uses the operator-supplied CIDR instead of always falling back to the lab default host `10.10.10.20`. The `10.10.10.20` fallback is now applied only when `target_net` is absent or empty.

### Changed Components

| Component | Change |
|-----------|--------|
| `target_engine.py` | CIDR expansion via `expand_target_net_hosts()`; lab fallback only when `target_net` is empty |
| `scenario_engine.py` | `TargetSet.stub()` delegates to `resolve_targets()` |
| Tests | New `test_target_net_propagation.py` — **838 pytest tests passed** |

### Upgrade

```bash
cd detection-scenario-platform
pip install -e ".[dev]"
dsp --version   # expect: dsp 1.2.1
```

---

# DSP v1.2.0 Release Notes

**Version:** 1.2.0  
**Date:** 2026-06-09 (UTC)  
**Package:** `detection-scenario-platform` (`dsp`)

---

## Summary

DSP v1.2.0 completes the webshell remote execution path on the standard `dsp run` entry point. Operators can run detection scenarios on a remote host via JSP/PHP/ASPX webshell, collect event bundles, import them into the local Event Store, and receive validation, reporting, and evidence packages — without changing S2 exit codes or requiring Stellar API integration.

Live lab validation on `victim-linux` (`10.10.10.20`) confirmed real DNS, HTTP, and TCP traffic generation plus evidence export for the webshell path. See [`docs/remote-live-traffic-validation-report.md`](docs/remote-live-traffic-validation-report.md).

---

## Changed Components

### CLI (`dsp`)

| Change | Detail |
|--------|--------|
| `--execution-provider` | New choice: `local` (default) or `webshell` |
| `--webshell-family` | Required for webshell: `jsp`, `php`, `aspx` |
| `--webshell-url` | Required for webshell: endpoint URL |
| `--remote-work-dir` | Remote bundle directory (default: `/tmp/dsp`) |
| `--verify-tls` | Optional TLS verification for webshell HTTP transport |

### New entry point

| Script | Purpose |
|--------|---------|
| `dsp-remote-scenario` | Runs on the remote webshell target host; executes one scenario and writes `events.jsonl` bundle |

### RunManager

- Webshell provider selection and remote flow orchestration (`RemoteScenarioRunner` → `RemoteEventCollector` → Event Store import).
- Validation, reporting, and evidence export (`EvidenceExporter` + `ManualVerificationPackageGenerator`) on webshell runs (default `export_evidence=True`).

### Webshell runtime

- JSP artifact download fallback via `cat <path>` when `remote_path` GET is unavailable.
- Base64-encoded scenario payload transport (`encode_scenario_payload` / `decode_scenario_payload`) for shell-safe JSON delivery.

### Tests

- New: `test_remote_scenario_cli.py`, `test_remote_end_to_end.py`, `test_runmanager_webshell.py`
- Updated: remote scenario runner, e2e webshell flow, operational runner integration tests
- **Release gate:** 830 pytest tests passed

---

## Upgrade Steps

```bash
cd detection-scenario-platform
pip install -e ".[dev]"    # or: .venv/bin/pip install -e ".[dev]"
dsp --version              # expect: dsp 1.2.0
```

**Remote host prerequisite:** deploy `detection-scenario-platform` tree and install `dsp-remote-scenario` wrapper on the webshell target (see validation report §1).

**Example — local run (unchanged):**

```bash
dsp run --scenarios dns_tunnel --target-net 10.10.10.0/24
```

**Example — webshell remote run:**

```bash
dsp run \
  --scenarios dns_tunnel \
  --execution-provider webshell \
  --webshell-family jsp \
  --webshell-url http://10.10.10.20:8080/shell.jsp \
  --target-net 10.10.10.0/24
```

---

## Known Limitations (v1.2.0)

| Limitation | Detail | Workaround |
|------------|--------|------------|
| **`dsp run --profile low` not supported** | CLI has no `--profile` / `--traffic-profile` flag | Use `operational_runner --traffic-profile low`, or pass `scenario_params=build_scenario_params(id, "low")` programmatically |
| **`ssh_failure` live validation substituted** | Live session used `port_sweep` for TCP connect validation instead of `ssh_failure` | `port_sweep` exercises the same remote TCP transport path; SSH auth negotiation not validated in live report |
| **Remote install prerequisite** | Target host needs `dsp-remote-scenario` + platform tree | Deploy per [`docs/remote-live-traffic-validation-report.md`](docs/remote-live-traffic-validation-report.md) §1 |
| **JSP download fallback** | Lab JSP webshell lacks `remote_path` GET; bundle retrieved via `cat` | Automatic in `JspWebshellRuntime.download_artifact()` |
| **Detection confirmation (S3)** | Optional; does not affect S2 exit codes | `--confirm-detection` unchanged from v1.1.0 |

Additional gap analysis: [`docs/release-gap-analysis-v1.2.0.md`](docs/release-gap-analysis-v1.2.0.md).

---

## Validation References

- Live traffic report: [`docs/remote-live-traffic-validation-report.md`](docs/remote-live-traffic-validation-report.md)
- Release readiness revalidation: [`docs/release-readiness-revalidation.md`](docs/release-readiness-revalidation.md)
- Remote execution design: [`docs/remote-execution-completion-plan.md`](docs/remote-execution-completion-plan.md)

---

*DSP provides execution evidence only. Alert, case, and detection success are operator-verified in Stellar UI.*
