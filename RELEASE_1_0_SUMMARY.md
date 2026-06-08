# DSP Release 1.0 Summary

**Version:** 1.0.0  
**Status:** Release candidate — core platform, execution providers, evidence packaging, E2E harness

---

## Supported Scope

Release 1.0 delivers a self-contained Detection Scenario Platform with:

| Area | Release 1.0 capability |
|------|------------------------|
| **Event Store** | SQLite append-only SOT per run (`events.db`, optional `events.jsonl` export) |
| **Scenario plugins** | 12 discovered scenarios (`dummy`, `dns_tunnel`, `dga`, `http_followup`, `ssh_failure`, `sql_injection`, `port_sweep`, `kerberos_failure`, `smb_login_failure`, `ldap_enumeration`, `dns_dummy`, `dns_transport_dummy`) |
| **Local execution** | `LocalExecutionProvider` integrated with `RunManager` / `dsp run` |
| **Webshell execution** | `WebshellExecutionProvider` (JSP / PHP / ASPX) via API composition |
| **Remote scenario dispatch** | `RemoteScenarioRunner` — command delivery only, no Event Store access |
| **Remote event collection** | `RemoteEventCollector` + `EventSyncBridge` — download `events.jsonl`, import to Event Store |
| **Evidence export** | `EvidenceExporter` — JSON + Markdown from Event Store |
| **Manual verification** | `ManualVerificationPackageGenerator` — checklist, investigation notes, evidence summary templates |
| **Validation / reporting** | `ValidationEngine` + `ReportingEngine` on local runs via `dsp run` |
| **E2E harness** | `tests/e2e/` — local and webshell flows without detection validation |

---

## Local Execution Flow

```
dsp run / RunManager
    ↓
LocalExecutionProvider.prepare()
    ↓
LocalExecutionProvider.execute() → run_scenario()
    ↓
Scenario traffic / event generation
    ↓
Event Store (events.db)
    ↓
ValidationEngine → validation.json
    ↓
ReportingEngine → report.md / report.json
    ↓
events.jsonl export (on run completion)
```

**CLI example:**

```bash
dsp run --scenarios dummy --dry-run
```

Run artifacts: `~/.dsp/runs/<run_id>/` (override with `DSP_RUNS_DIR`).

---

## Webshell Execution Flow

Webshell execution is available through the Python API. It is **not** wired into `dsp run` in Release 1.0.

```
WebshellExecutionProvider.prepare()
    ↓
WebshellExecutionProvider.execute()
    ↓
RemoteScenarioRunner.run() → dsp-remote-scenario command delivery
    ↓
Remote host / lab webshell executes scenario
    ↓
Remote events.jsonl bundle produced (remote side)
```

Supported families: **jsp**, **php**, **aspx**.  
Transport: HTTP GET/POST command delivery, multipart upload, GET download by `remote_path`.

---

## Event Collection Flow

After remote scenario execution, events are imported locally:

```
RemoteEventCollector.collect()
    ↓
WebshellExecutionProvider.download_file(remote_bundle_path)
    ↓
EventSyncBridge.sync_bundle(local_bundle_path, event_store)
    ↓
Event Store (append-only import)
```

**Bundle contract:** JSONL with metadata header row (`_bundle_metadata: true`) followed by event rows.  
`run_id` in bundle metadata must match the open Event Store run.

**Conventional remote path:** `/tmp/dsp/<run_id>/events.jsonl`

---

## Evidence Export Flow

Evidence export reads Event Store rows and writes human-review files. API-only in Release 1.0.

```
EvidenceExporter.export(EvidenceExportRequest)
    ↓
Event Store.list_events(run_id)
    ↓
run_<run_id>.json
run_<run_id>.md
```

---

## Manual Verification Flow

Manual verification generates operator review templates from existing evidence exports. API-only in Release 1.0.

```
EvidenceExporter (prerequisite)
    ↓
ManualVerificationPackageGenerator.generate()
    ↓
verification_checklist.md
investigation_notes.md
evidence_summary_template.md
```

These files are **templates for human review**. They do not assert attack success, detection success, alert creation, or case correlation.

---

## E2E Test Command

```bash
cd detection-scenario-platform
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Release 1.0 E2E harness only
pytest tests/e2e -v

# Full test suite
pytest
```

E2E tests verify:

1. Local path reaches Event Store
2. Webshell path reaches Event Store via downloaded `events.jsonl`
3. Evidence export from imported events
4. Manual verification package generation
5. No detection / attack / alert validation logic in the harness

---

## Known Non-Goals (Release 1.0)

| Non-goal | Notes |
|----------|-------|
| **Webshell in `dsp run`** | No `--execution-provider webshell` CLI flag; compose via Python API |
| **Evidence / manual verification CLI** | No `dsp evidence export` or `dsp verify` commands |
| **RunManager auto-collect** | Remote bundle download not triggered automatically after webshell execute |
| **Detection validation in E2E** | E2E harness excludes `ValidationEngine`, detection adapters, alert/case checks |
| **Attack / detection success inference** | No `execution_success`, `attack_success`, or alert outcome fields |
| **Agent / SSH execution providers** | Local and webshell only |
| **Deployment automation integration** | DSP remains separate from XDR lab appliance tooling |
| **Live SIEM/XDR required for tests** | `pytest` and `tests/e2e` run offline |

---

## Related Documents

| Document | Purpose |
|----------|---------|
| [RELEASE_1_0_LAB_GUIDE.md](./RELEASE_1_0_LAB_GUIDE.md) | Manual lab verification procedure |
| [README.md](./README.md) | Quick start and project overview |
| [ARCHITECTURE_SPEC.md](./ARCHITECTURE_SPEC.md) | Component architecture |
| [EVENT_SCHEMA_FREEZE.md](./EVENT_SCHEMA_FREEZE.md) | Event entity contract v1.0.0 |
