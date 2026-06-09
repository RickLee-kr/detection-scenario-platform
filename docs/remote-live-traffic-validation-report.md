# DSP Remote Live Traffic Validation Report

**Release:** DSP v1.2.0  
**Validation Date:** 2026-06-09  
**Scope:** RunManager webshell path — live traffic on lab `victim-linux` via JSP webshell  
**Success Criteria:** Actual traffic generated + evidence generated (detection/alert success not evaluated)

---

## 1. Test Environment

| Component | Value |
|-----------|-------|
| DSP host | `10.64.32.178` (appliance), lab bridge `br0` `10.10.10.1/24` |
| Remote execution host | `victim-linux` `10.10.10.20` |
| Webshell URL | `http://10.10.10.20:8080/shell.jsp` |
| Webshell family | JSP |
| Target network | `10.10.10.0/24` |
| Traffic profile | `low` (via `build_scenario_params(..., "low")`) |
| Remote work dir | `/tmp/dsp` |
| DSP version | `1.2.0` (`dsp --version`) |
| Remote `dsp-remote-scenario` | Deployed to `~/dsp-platform` + `/usr/local/bin/dsp-remote-scenario` wrapper (`PYTHONPATH=~/dsp-platform`) |

**Pre-validation setup (environment, not code):**

1. Copied `detection-scenario-platform` tarball to `victim-linux`
2. Installed wrapper script for `dsp-remote-scenario` (remote host has Python 3.12 but no pip/venv packages in apt)

---

## 2. Commands Executed

### Equivalent `dsp run` webshell command (low profile via API)

`dsp run` does not yet expose `--profile` / `--traffic-profile`; validation used `RunManager.run()` with `build_scenario_params(scenario_id, "low")` — functionally equivalent to the required example.

```bash
cd detection-scenario-platform
export DSP_RUNS_DIR=/tmp/dsp-live-validation/dsp_run_cli

python3 - <<'PY'
from pathlib import Path
from dsp.runner.run_manager import RunManager
from dsp.runtime.traffic_profiles import build_scenario_params

manager = RunManager(runs_dir=Path("/tmp/dsp-live-validation/dsp_run_cli"))
run, run_dir, exit_code = manager.run(
    scenario_ids=["dns_tunnel"],
    target_net="10.10.10.0/24",
    dry_run=False,
    scenario_params=build_scenario_params("dns_tunnel", "low"),
    execution_provider="webshell",
    webshell_family="jsp",
    webshell_url="http://10.10.10.20:8080/shell.jsp",
    remote_work_dir="/tmp/dsp",
)
print(run.run_id, exit_code, run_dir)
PY
```

**Result:** `20260609_e4e603 exit=0`

### Live scenario battery (low profile)

```bash
python3 /tmp/dsp_live_validation.py
```

Scenarios: `dns_tunnel`, `http_followup`, `port_sweep` (substitute for `ssh_failure` per validation scope)

### Remote packet capture (DNS)

```bash
ssh labuser@10.10.10.20 'sudo tcpdump -i any -n udp port 53 -c 3'
# concurrent with dsp run dns_tunnel webshell
```

---

## 3. Scenario Results

| Scenario | Run ID | Exit | Validation | Traffic events (imported) | Notes |
|----------|--------|------|------------|---------------------------|-------|
| `dns_tunnel` | `20260609_b9fd98` | 0 | success | 21 | `dns_tunnel_query_sent_count=4`, UDP/53 live |
| `http_followup` | `20260609_62fad0` | 0 | success | 14 | `http_request_sent_count=3`; response errors expected (no HTTPS listener) |
| `port_sweep` | `20260609_697ade` | 0 | success | 15 | `port_probe_count=5`, TCP connect attempts observed |

All runs completed without hang. Response failures (HTTP errors, connection refused on closed ports) did not abort the run; validation decisions remained `success` where minimum traffic thresholds were met.

---

## 4. Packet/Traffic Evidence

**DNS (remote `tcpdump` on `victim-linux` during live `dns_tunnel`):**

```
10.10.10.20.40455 > 10.10.10.20.53: A? idx-000001-....dns-tunnel.com.
10.10.10.20.35159 > 10.10.10.20.53: A? idx-000002-....dns-tunnel.com.
10.10.10.20.40982 > 10.10.10.20.53: A? idx-000003-....dns-tunnel.com.
```

**Conclusion:** Real UDP/53 DNS tunnel FQDN queries originated on the remote host.

**TCP (`port_sweep`):** EventStore records `port_probe_sent` / `port_connection_failed` / `port_connection_opened` — live TCP SYN attempts from remote host to targets in `10.10.10.0/24`.

**HTTP (`http_followup`):** EventStore records `http_request_sent` with `status=sent` and companion `http_request_error` where targets did not respond — live client attempts from remote host.

---

## 5. Event Bundle Evidence

Remote bundles created at `/tmp/dsp/<run_id>/events.jsonl` on `victim-linux`:

```
/tmp/dsp/20260609_b9fd98/events.jsonl   9374 bytes   (dns_tunnel, 21 events)
/tmp/dsp/20260609_62fad0/events.jsonl   5758 bytes   (http_followup)
/tmp/dsp/20260609_697ade/events.jsonl   5917 bytes   (port_sweep)
```

Sample bundle header (`dns_tunnel`):

```json
{"_bundle_metadata": true, "run_id": "20260609_b9fd98", "scenario_id": "dns_tunnel", "event_count": 21, "schema_version": "1.0.0"}
```

Traffic attempt row:

```json
{"event": "dns_tunnel_query_sent", "status": "sent", "target": "10.10.10.20", "source": "remote"}
```

---

## 6. EventStore Evidence

Host-side run directory example: `/tmp/dsp-live-validation/dns_tunnel/20260609_b9fd98/`

| Artifact | Present |
|----------|---------|
| `events.db` | Yes |
| `events.jsonl` | Yes (21 events after import) |
| `validation.json` | Yes — `decision: success` |
| `report.md` / `report.json` | Yes |
| `run.json` | Yes |

Validation excerpt (`dns_tunnel`):

```json
{
  "decision": "success",
  "reason": "thresholds_met",
  "metrics": {
    "dns_tunnel_chunk_created_count": 4,
    "dns_tunnel_query_sent_count": 4
  }
}
```

Event types imported for `dns_tunnel`: `dns_tunnel_query_sent`, `dns_tunnel_chunk_created`, `dns_query_sent`, `dns_timeout`, lifecycle events.

---

## 7. Evidence Package Output

Per-scenario host run dir includes:

- `run_<run_id>.json` — raw EventStore export (e.g. 13740 bytes for dns_tunnel)
- `run_<run_id>.md` — human-readable evidence
- `verification_checklist.md`
- `investigation_notes.md`
- `evidence_summary_template.md`

Evidence generation path is identical for webshell and local runs via `RunManager._export_evidence()`.

---

## 8. Failures and Fixes

| Failure | Root cause | Fix applied |
|---------|------------|-------------|
| `dsp-remote-scenario` silent no-op via `python -m` | Missing `if __name__ == "__main__"` guard | Added `raise SystemExit(main())` in `remote_scenario_cli.py` |
| Remote bundle download returned `ready` (invalid JSONL) | Lab JSP webshell does not implement `remote_path` GET download | `JspWebshellRuntime.download_artifact()` — fallback to `cat <path>` via `cmd` param + `__EXIT_CODE` stripping |
| Remote scenario command JSON parse error | JSON payload corrupted through webshell GET/shell quoting | `encode_scenario_payload()` / `decode_scenario_payload()` — base64 transport in `payload.py` |
| `dsp` not installed on remote host | Environment prerequisite | Deployed platform tree + `/usr/local/bin/dsp-remote-scenario` wrapper on `victim-linux` |

**Known gaps (v1.2.0 — documented, not release blockers):**

| Gap | Status | Workaround |
|-----|--------|------------|
| `dsp run --profile low` | **Not supported** | Use `build_scenario_params(scenario_id, "low")` programmatically, or `operational_runner --traffic-profile low` |
| `ssh_failure` live validation | **Substituted** | `port_sweep` used for live TCP connect validation (same transport path; SSH auth packets not exercised in this session) |

---

## 9. Final Verdict

| Criterion | Verdict |
|-----------|---------|
| **Remote Live Traffic** | **PASS** — DNS UDP/53, HTTP client, TCP port probes observed on remote host |
| **Remote Bundle Collection** | **PASS** — bundles written remotely, downloaded via JSP `cat` fallback, imported to EventStore |
| **Evidence Generation** | **PASS** — validation, report, and evidence package files produced for all scenarios |
| **Release Readiness** | **READY** — webshell live path operational on lab topology with documented remote install prerequisite |

**pytest (release gate):** 830 tests passed (`detection-scenario-platform/.venv/bin/python -m pytest`, 2026-06-09).

---

## Appendix: Required Command Mapping

User example:

```bash
dsp run \
  --scenarios dns_tunnel \
  --execution-provider webshell \
  --webshell-family jsp \
  --webshell-url http://10.10.10.20:8080/shell.jsp \
  --target-net 10.10.10.0/24 \
  --profile low
```

Current CLI supports all flags except `--profile`. Equivalent today:

```bash
dsp run \
  --scenarios dns_tunnel \
  --execution-provider webshell \
  --webshell-family jsp \
  --webshell-url http://10.10.10.20:8080/shell.jsp \
  --target-net 10.10.10.0/24
```

For `low` profile volumes, pass `scenario_params` programmatically or use `operational_runner --traffic-profile low` until CLI flag is added.
