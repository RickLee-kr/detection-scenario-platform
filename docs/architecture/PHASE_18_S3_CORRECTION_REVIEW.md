# Phase 18 — S3 Architecture Correction Review

**Phase:** 18  
**Status:** Complete  
**Date:** 2026-06-06

---

## 1. What Was Corrected

| Area | Before (Phase 7–12 overreach) | After (Phase 18) |
|------|-------------------------------|------------------|
| Default `--confirm-detection` | Mock Stellar client → auto `S3_CONFIRMED` | Manual evidence templates → `S3_INCONCLUSIVE` / `manual_review_required` |
| Operator docs | API tokens in primary quickstart/runbook | Manual UI workflow default; tokens only in experimental doc |
| Evidence output | `evidence/<run_id>/stellar/` implied primary | `evidence/<run_id>/manual/` is default |
| CLI default | `--stellar-client mock` | `--stellar-client manual` |
| Architecture narrative | DSP appeared to require Stellar API | DSP clearly standalone-first |

---

## 2. What Remains Standalone

These layers require **no Stellar configuration**:

- Scenario execution (`dsp run --scenarios <id>`)
- Event Store (SQLite SOT)
- S2 validation and exit codes
- Report generation (`report.md`, `report.json`)
- Manual S3 evidence pack (`--confirm-detection` default)

```bash
source .venv/bin/activate
dsp run --scenarios dns_tunnel
dsp run --scenarios dns_tunnel --confirm-detection
```

---

## 3. What Is Experimental

| Feature | Invocation | Document |
|---------|------------|----------|
| Stellar HTTP API polling | `--confirm-detection --detection-provider stellar --stellar-client http` | `docs/experimental/STELLAR_HTTP_API_MODE.md` |
| Mock Stellar responses | `--confirm-detection --stellar-client mock` | CI/demo only |

HTTP mode requires `DSP_STELLAR_BASE_URL` and `DSP_STELLAR_API_TOKEN`.  
Missing credentials in HTTP mode does **not** affect S2 exit codes.

---

## 4. Operator Impact

### No action required for S2-only users

Existing `dsp run --scenarios <id>` workflows unchanged.

### S3 operators — new default workflow

1. Run with `--confirm-detection` (no API setup)
2. Open `evidence/<run_id>/manual/s3_manual_checklist.md`
3. Validate in Stellar UI using pre-filled time window and IPs
4. Complete `correlation_notes.md` with alert IDs
5. Mark S3 outcome manually in operator records

### Teams using HTTP automation

Must now **explicitly** pass `--stellar-client http` and configure env vars.  
See experimental documentation — not part of normal operator guides.

---

## 5. Recommended Validation Workflow

```
┌─────────────────┐
│  dsp run        │  Scenario execution
└────────┬────────┘
         ▼
┌─────────────────┐
│  Event Store    │  SOT — authoritative
└────────┬────────┘
         ▼
┌─────────────────┐
│  S2 Validation  │  Exit code source
└────────┬────────┘
         ▼
┌─────────────────┐
│  Report         │  Customer-facing S2 summary
└────────┬────────┘
         ▼ (optional)
┌─────────────────┐
│  S3 Manual      │  Operator + Stellar UI (DEFAULT)
└─────────────────┘

         OR (explicit opt-in)

┌─────────────────┐
│  S3 HTTP API    │  Experimental automation
└─────────────────┘
```

---

## 6. Code Changes Summary

| Component | Change |
|-----------|--------|
| `dsp/detection/providers/manual/manual_adapter.py` | New manual S3 adapter |
| `dsp/detection/factory.py` | Default mode `manual`; HTTP/mock explicit |
| `dsp/runner/cli.py` | Updated defaults and help text |
| `dsp/runner/run_manager.py` | Evidence path follows adapter vendor_id |
| `dsp/detection/manager.py` | `s3_result_manual.json` for manual vendor |
| Tests | Manual evidence, no-env-vars, HTTP explicit |
| Docs | Architecture correction, experimental HTTP doc, catalog cleanup |

---

## 7. Unchanged (Non-Negotiable)

- Scenario execution behavior
- Event Store schema
- S2 validation rules and thresholds
- Report pass/fail semantics
- Stellar HTTP/mock adapter code (preserved, demoted)

---

## 8. Related Documents

- [S3_ARCHITECTURE_CORRECTION.md](./S3_ARCHITECTURE_CORRECTION.md)
- [../experimental/STELLAR_HTTP_API_MODE.md](../experimental/STELLAR_HTTP_API_MODE.md)
- [../runtime/EXECUTION_GUIDE.md](../runtime/EXECUTION_GUIDE.md)
