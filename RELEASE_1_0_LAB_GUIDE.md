# DSP Release 1.0 — Manual Lab Test Guide

**Audience:** Lab operator, validation engineer  
**Purpose:** Manually verify DSP artifact generation in a lab environment  
**Scope:** Traffic execution, Event Store population, evidence export, manual verification templates

This guide describes **what DSP produces** and **how to inspect it**. It does **not** claim detection success, alert creation, or case validation. External SIEM/XDR review is a separate manual step outside DSP Release 1.0.

---

## 1. Prerequisites

### 1.1 Software

```bash
cd detection-scenario-platform
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

dsp plugins list    # confirm target scenarios are ACTIVE
pytest tests/e2e -v # optional pre-flight harness check
```

### 1.2 Environment variables

| Variable | Purpose |
|----------|---------|
| `DSP_RUNS_DIR` | Writable directory for run artifacts (recommended in lab) |

```bash
export DSP_RUNS_DIR=/path/to/lab-evidence/dsp-runs
mkdir -p "$DSP_RUNS_DIR"
```

### 1.3 Lab topology (minimum)

| Mode | Requirements |
|------|--------------|
| **Local dry-run** | DSP host only — no network targets required |
| **Local live** | Reachable targets within `--target-net` CIDR |
| **Webshell remote** | Lab webshell endpoint (JSP / PHP / ASPX) reachable from DSP host; remote side capable of running `dsp-remote-scenario` and writing `events.jsonl` |

Record for each session: operator name, date, DSP version (`dsp --version`), run ID, scenario ID, execution mode.

---

## 2. Local Execution — Manual Verification

### 2.1 Run a scenario

Dry-run (no network):

```bash
dsp run --scenarios dummy --dry-run
```

Live traffic (example):

```bash
dsp run --scenarios dns_tunnel --target-net 10.10.10.0/24
```

Note the printed run directory: `~/.dsp/runs/<run_id>/` or `$DSP_RUNS_DIR/<run_id>/`.

### 2.2 Inspect run artifacts

| File | What to verify |
|------|----------------|
| `events.db` | Present; SQLite Event Store SOT |
| `run.json` | Run metadata matches session notes |
| `validation.json` | S2 validation results present (traffic path only) |
| `report.md` / `report.json` | Human/machine reports generated |
| `events.jsonl` | Optional JSONL export on completion |
| `manifest.snapshot.<scenario>.json` | Resolved scenario manifest |

### 2.3 Confirm events were recorded

Using Python in the run directory context:

```python
from pathlib import Path
from dsp.event_store import EventStore, EventQuery

run_dir = Path("/path/to/runs/<run_id>")
store = EventStore.open_existing(run_dir / "events.db")
run_id = store.run_id
count = store.count(EventQuery(run_id=run_id))
events = store.list_events(run_id)
print(f"run_id={run_id} event_count={count}")
for event in events[:5]:
    print(event.event, event.status, event.scenario_id)
store.close()
```

**Pass criteria (local):**

- [ ] `events.db` exists and contains events for the run
- [ ] `events.jsonl` exists (if run completed normally)
- [ ] `validation.json` and `report.md` exist
- [ ] Event rows match the executed scenario ID

**Not in scope:** Stellar alert presence, detection rule firing, case creation.

---

## 3. Webshell Remote Execution — Manual Verification

Webshell execution is composed via Python API in Release 1.0. Use a lab script or interactive session.

### 3.1 Configuration

| Setting | Example |
|---------|---------|
| `webshell_family` | `jsp`, `php`, or `aspx` |
| `webshell_url` | `https://lab-victim.example/shell.jsp` |
| `run_id` | Stable ID shared with local Event Store and remote bundle |
| `remote_bundle_path` | `/tmp/dsp/<run_id>/events.jsonl` (lab convention) |

### 3.2 Execute remotely and collect events

Save as `lab_webshell_run.py` and adjust URLs/paths:

```python
#!/usr/bin/env python3
"""Lab webshell execution + event collection — no detection validation."""

from pathlib import Path

from dsp.engine import RunConfig, RunContext, resolve_targets
from dsp.event_store import EventQuery, EventStore
from dsp.execution import ExecutionContext, create_execution_provider
from dsp.execution.remote import RemoteEventCollectionRequest, RemoteEventCollector
from dsp.plugins import PluginLoader

RUN_ID = "20260606_lab_webshell_01"
SCENARIO_ID = "dummy"
TARGET_NET = "10.10.10.0/24"
WEBSHELL_URL = "https://lab-victim.example/shell.jsp"
REMOTE_BUNDLE_PATH = f"/tmp/dsp/{RUN_ID}/events.jsonl"
OUTPUT_DIR = Path("/path/to/lab-evidence/webshell-run-01")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Local Event Store for this lab session
store = EventStore(OUTPUT_DIR / "events.db")
store.open_run(RUN_ID)

loader = PluginLoader()
record = loader.discover_and_load().get(SCENARIO_ID)
assert record is not None

provider = create_execution_provider(
    "webshell",
    webshell_family="jsp",
    webshell_url=WEBSHELL_URL,
    verify_tls=False,  # lab only — use True in production
    enable_healthcheck_on_connect=True,
)

exec_ctx = ExecutionContext(
    run_id=RUN_ID,
    target_net=TARGET_NET,
    dry_run=False,
    provider_type="webshell",
    scenario_id=SCENARIO_ID,
)
run_ctx = RunContext(
    run_id=RUN_ID,
    target_net=TARGET_NET,
    event_store=store,
    config=RunConfig(dry_run=False),
    dry_run=False,
)
targets = resolve_targets(TARGET_NET)

provider.prepare(exec_ctx)
provider.execute(exec_ctx, record, run_ctx, targets)

remote_execution_id = exec_ctx.execution_metadata["remote_execution_id"]
print(f"remote_execution_id={remote_execution_id}")

# Before collection: confirm remote side wrote events.jsonl at REMOTE_BUNDLE_PATH
collector = RemoteEventCollector()
result = collector.collect(
    RemoteEventCollectionRequest(
        remote_execution_id=remote_execution_id,
        remote_bundle_path=REMOTE_BUNDLE_PATH,
    ),
    provider,
    store,
)
provider.cleanup(exec_ctx)

print(f"events_imported={result.events_imported}")
print(f"local_bundle={result.local_bundle_path}")
print(f"event_store_count={store.count(EventQuery(run_id=RUN_ID))}")
store.close()
```

Run:

```bash
python lab_webshell_run.py
```

### 3.3 Remote-side requirement

The lab webshell host must:

1. Accept command delivery via the webshell transport contract (execute / upload / download)
2. Execute `dsp-remote-scenario` with the payload sent by `RemoteScenarioRunner`
3. Write a valid EventSyncBridge JSONL bundle to `/tmp/dsp/<run_id>/events.jsonl`

Bundle format:

- Line 1: metadata with `_bundle_metadata: true`, matching `run_id` and `scenario_id`
- Lines 2+: event records with required fields (`run_id`, `scenario_id`, `timestamp`, `stage`, `event`, `status`)

### 3.4 Pass criteria (webshell)

- [ ] Remote command delivery completed (`remote_execution_id` recorded)
- [ ] `RemoteEventCollector` downloaded the bundle (`local_bundle_path` populated)
- [ ] `events_imported` > 0
- [ ] Local `events.db` contains imported events for `run_id`

**Not in scope:** Remote command stdout interpretation, attack success, remote host compromise confirmation.

---

## 4. events.jsonl Collection — Manual Verification

### 4.1 Local run export

After `dsp run`, inspect:

```bash
head -5 "$DSP_RUNS_DIR/<run_id>/events.jsonl"
```

Each line is one JSON object. Verify `run_id` and `scenario_id` on event rows.

### 4.2 Webshell bundle import

After webshell collection, inspect the downloaded bundle:

```bash
head -5 /path/to/downloaded/events.jsonl
```

Compare bundle `run_id` with local Event Store:

```python
from dsp.event_store import EventStore, EventQuery

store = EventStore.open_existing("events.db")
print(store.count(EventQuery(run_id="<run_id>")))
store.close()
```

**Pass criteria:**

- [ ] Bundle metadata `event_count` matches event rows
- [ ] Imported Event Store count matches `events_imported`
- [ ] No `run_id` mismatch errors during sync

---

## 5. Evidence Export — Manual Verification

Evidence export is API-only. Run after events are in the Event Store.

```python
from pathlib import Path
from dsp.event_store import EventStore
from dsp.evidence import EvidenceExportRequest, EvidenceExporter

run_id = "<run_id>"
output_dir = Path("/path/to/lab-evidence/export")
output_dir.mkdir(parents=True, exist_ok=True)

store = EventStore.open_existing("/path/to/events.db")
result = EvidenceExporter(store).export(
    EvidenceExportRequest(run_id=run_id, output_directory=output_dir)
)
store.close()

print(result.exported_files)
print(result.export_metadata)
```

Expected files:

| File | Content |
|------|---------|
| `run_<run_id>.json` | Structured event export |
| `run_<run_id>.md` | Human-readable event summary |

**Pass criteria:**

- [ ] Both JSON and Markdown files exist and are non-empty
- [ ] `export_metadata["event_count"]` matches Event Store count

---

## 6. Manual Verification Package — Manual Verification

Generate review templates after evidence export:

```python
from pathlib import Path
from dsp.event_store import EventStore
from dsp.manual_verification import (
    ManualVerificationPackageGenerator,
    ManualVerificationRequest,
)

run_id = "<run_id>"
output_dir = Path("/path/to/lab-evidence/export")

store = EventStore.open_existing("/path/to/events.db")
result = ManualVerificationPackageGenerator(store).generate(
    ManualVerificationRequest(run_id=run_id, output_directory=output_dir)
)
store.close()

print(result.generated_files)
print(result.package_metadata)
```

Expected files:

| File | Purpose |
|------|---------|
| `verification_checklist.md` | Operator checklist (unchecked items) |
| `investigation_notes.md` | Blank investigation notes template |
| `evidence_summary_template.md` | Evidence summary scaffold referencing export files |

**Pass criteria:**

- [ ] All three template files exist
- [ ] Checklist references the correct `run_id`
- [ ] Summary template lists evidence export filenames

**Operator action:** Complete the checklist and notes manually. DSP does not auto-fill detection outcomes, alert IDs, or case references.

---

## 7. End-to-End Lab Session Checklist

Use this checklist per lab session:

### Local path

- [ ] `dsp run` completed
- [ ] `events.db` populated
- [ ] `events.jsonl` exported
- [ ] Evidence export generated
- [ ] Manual verification package generated
- [ ] Artifacts archived under `$DSP_RUNS_DIR` or project evidence folder

### Webshell path

- [ ] Webshell connectivity verified (healthcheck / simple command)
- [ ] Remote scenario command delivered
- [ ] Remote `events.jsonl` bundle present at agreed path
- [ ] Bundle downloaded and imported to local Event Store
- [ ] Evidence export generated from imported events
- [ ] Manual verification package generated

### Explicitly out of scope

- [ ] ~~Detection rule fired~~ — verify externally if needed
- [ ] ~~Alert created in SIEM/XDR~~ — verify externally if needed
- [ ] ~~Case opened or correlated~~ — verify externally if needed
- [ ] ~~Attack succeeded~~ — not inferred by DSP

---

## 8. Troubleshooting

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| Empty Event Store after webshell execute | Expected — webshell execute does not write locally | Run `RemoteEventCollector.collect()` |
| `BundleValidationError: run_id` | Bundle metadata run_id ≠ open store run_id | Align `RUN_ID` on both sides |
| `BundleNotFoundError` | Download path wrong or remote bundle missing | Confirm remote path and webshell download contract |
| Manual verification fails | Evidence export not run first | Run `EvidenceExporter` before generator |
| TLS errors to lab webshell | Self-signed cert | Set `verify_tls=False` for lab only |

---

## 9. References

- [RELEASE_1_0_SUMMARY.md](./RELEASE_1_0_SUMMARY.md) — Release scope and flows
- [EVENT_SCHEMA_FREEZE.md](./EVENT_SCHEMA_FREEZE.md) — Event field contract
- [docs/architecture/EVENT_BUNDLE_WIRING_SPEC.md](./docs/architecture/EVENT_BUNDLE_WIRING_SPEC.md) — Bundle sync specification
- `tests/e2e/` — Automated reference implementation (mock webshell server)
