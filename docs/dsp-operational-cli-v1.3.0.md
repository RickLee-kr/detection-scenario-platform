# DSP v1.3.0 — Operational CLI Simplification

**Version:** 1.3.0  
**Status:** Released  
**Package:** `detection-scenario-platform` (`dsp`)

---

## Purpose

DSP v1.3.0 treats DSP as an operator-facing product. Users make three decisions; everything else is internal.

| Decision | Option |
|----------|--------|
| Where to run | `local` (default) or `webshell` |
| Target network | `--target-net <CIDR>` |
| Intensity | `--profile low \| normal \| high` |

Discovery, host selection, protocol coverage, follow-up, and scenario ordering are handled by DSP.

---

## Default CLI

### Local

```bash
dsp run --target-net 221.139.249.0/24 --profile low
dsp run --target-net 221.139.249.0/24 --profile normal
dsp run --target-net 221.139.249.0/24 --profile high
```

When `--profile` is omitted and `--scenarios` is not set, **`normal`** is used.

### Webshell (JSP / PHP / ASPX)

```bash
dsp run \
  --execution-provider webshell \
  --webshell-family jsp \
  --webshell-url http://server/shell.jsp \
  --target-net 221.139.249.0/24 \
  --profile normal
```

Local and webshell share the same progress output and evidence summary format.

---

## Profile Definitions

### LOW

**Goal:** Fast validation (tens of seconds to ~1 minute)

| Aspect | Behavior |
|--------|----------|
| Scenarios | `port_sweep`, `dns_tunnel`, `http_followup` |
| Host limit | 1 per scenario |
| Traffic | Minimal (1–2 actions per protocol where applicable) |
| Use | Install check, sensor connectivity, quick PoC |

### NORMAL

**Goal:** Standard detection validation (minutes)

| Aspect | Behavior |
|--------|----------|
| Scenarios | LOW + `dga`, `sql_injection`, `ldap_enumeration`, `smb_login_failure`, `ssh_failure`, `kerberos_failure` |
| Host limit | Up to 2 per scenario |
| Traffic | Moderate, representative hosts only |
| Use | Customer demo, detection validation |

### HIGH

**Goal:** Maximum coverage (minutes to tens of minutes)

| Aspect | Behavior |
|--------|----------|
| Scenarios | Same set as NORMAL |
| Host limit | All discovered hosts in `--target-net` (subject to `--max-hosts` cap) |
| Traffic | Aggressive volume / follow-up parameters |
| Use | Coverage test, sensor visibility, stress validation |

---

## Large CIDR Guardrail

`high` profile expands `--target-net` across all usable hosts. CIDRs **wider than /24** are blocked by default.

```
ERROR: target-net is larger than /24. Use --allow-large-target and --max-hosts to continue.
```

To run against a large network:

```bash
dsp run \
  --target-net 10.0.0.0/16 \
  --profile high \
  --allow-large-target \
  --max-hosts 10
```

Both flags are required. `--max-hosts` caps discovery expansion and per-scenario host selection.

---

## Internal Scenario Model

Operators do not need to know internal scenario IDs (`dns_tunnel`, `http_followup`, etc.). DSP selects and orders them per profile.

Explicit scenario selection remains available for advanced users:

```bash
dsp run --scenarios dns_tunnel,http_followup --target-net 10.10.10.0/24
```

Optional `--profile` with `--scenarios` applies volume/host limits without changing the scenario list.

---

## Progress Output

Silent runs are disabled by default. Example stdout:

```
DSP Run Started

Provider: webshell
Target Net: 221.139.249.0/24
Profile: normal

Discovery Started
Discovery Completed
Hosts Found: 4

Scenario Execution Started

Port Sweep Completed
  probes_sent=13
  success=2
  failed=11

DNS Tunnel Completed
  queries_sent=100

HTTP Follow-up Completed
  requests_sent=10
  responses_received=0

...

Evidence Generated

Run Completed

Duration: 0:03:12
Events Generated: 517

Traffic Summary

dns_tunnel
  queries_sent=100

http_followup
  requests_sent=10
  responses_received=0

port_sweep
  probes_sent=13
  success=2
  failed=11

Evidence Summary

Run Directory:
/home/user/.dsp/runs/20260610_abc123

Events:
events.jsonl

Report:
report.md

Validation:
validation.json
```

Use `--quiet` to restore minimal one-line status (debug / scripting).

---

## Evidence Summary

After every operational run, DSP prints:

| Artifact | Path (under run directory) |
|----------|----------------------------|
| Run directory | `~/.dsp/runs/<run_id>` |
| Events | `events.jsonl` |
| Report | `report.md` |
| Validation | `validation.json` |

Evidence export and manual verification packages are generated as in v1.2.x.

---

## Implementation Map

| Module | Role |
|--------|------|
| `dsp/runner/cli.py` | `--profile`, optional `--scenarios`, run plan resolution |
| `dsp/runtime/operational_profiles.py` | Profile → scenarios, host limits, params |
| `dsp/runtime/traffic_profiles.py` | Per-scenario volume (`low` / `normal` / `high`) |
| `dsp/runner/console_output.py` | Progress + evidence summary |
| `dsp/runner/run_manager.py` | `on_progress` callback, `operational_profile` metadata |

### Traffic profile aliases

Legacy names are accepted and normalized:

| Legacy | v1.3.0 |
|--------|--------|
| `balanced` | `normal` |
| `burst` | `high` |

---

## Known Gaps (v1.3.0)

| Gap | Detail |
|-----|--------|
| **Large CIDR default cap** | Expansion stops at 32 hosts unless `--max-hosts` lowers it; `/24` and smaller need no extra flags |
| **Live protocol discovery** | Host discovery expands `--target-net` CIDR; per-protocol port/service discovery is scenario-driven, not a separate probe phase |
| **Webshell multi-scenario** | Webshell path runs scenarios sequentially via `RunManager`; remote preflight commands are unchanged from v1.2.x |
| **`operational_runner` CLI** | Lab runner (`--traffic-profile`) still exists alongside `dsp run --profile`; names aligned but separate entry points |
| **S3 / detection** | `--confirm-detection` unchanged; optional, does not affect S2 exit codes |
| **Profile timing SLA** | Duration targets (e.g. “~1 minute” for LOW) depend on network and target responsiveness; not enforced as hard deadlines |

---

## Upgrade

```bash
cd detection-scenario-platform
pip install -e ".[dev]"
dsp --version   # expect: dsp 1.3.0
```

---

*DSP provides execution evidence only. Alert, case, and detection success are operator-verified in the security platform UI.*
