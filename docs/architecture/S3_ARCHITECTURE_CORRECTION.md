# S3 Architecture Correction

**Phase:** 18  
**Status:** Architecture correction — standalone-first S3 design  
**Audience:** Platform engineers, lab operators, validation leads

---

## 1. Problem Statement

Phases 7–12 introduced Stellar HTTP API integration into the primary DSP runtime path:

- `DSP_STELLAR_BASE_URL` / `DSP_STELLAR_API_TOKEN` environment variables
- Automatic Stellar API polling during `--confirm-detection`
- S3 auto-confirmation semantics that implied DSP directly manages Stellar detection state

This was **architectural overreach**.

DSP is intended to be a **mostly standalone Detection Scenario Platform**. Its core responsibility is:

```
Scenario Execution → Event Store → S2 Validation → Report / Evidence Pack
```

S3 (Detection Confirmed) is an **optional consumer layer** — not a hard dependency on vendor API access.

---

## 2. Why Automatic Stellar API Polling Was Overreach

| Concern | Explanation |
|---------|-------------|
| **Standalone mandate** | DSP must run without Stellar credentials, network paths, or tenant-specific API contracts |
| **Operator reality** | Many Stellar deployments expose UI-first validation; API availability and schema vary by tenant |
| **Separation of concerns** | S2 is DSP-authoritative (Event Store). S3 is vendor-observation — often best confirmed by a human with UI context |
| **False impression** | Default API polling suggested DSP *requires* Stellar API access for normal operation |
| **Security surface** | Requiring API tokens in operator guides increases credential sprawl for a platform that should not need them |

Automatic polling remains **useful for experimentation and CI mock paths**, but must not be the default operational workflow.

---

## 3. Standalone-First Principle

DSP normal usage:

```bash
source .venv/bin/activate
dsp run --scenarios dns_tunnel
dsp run --scenarios dns_tunnel --confirm-detection
```

**No Stellar API configuration required.**

| Layer | Authority | Requires Stellar API? |
|-------|-----------|----------------------|
| S1 Scenario Execution | DSP | No |
| Event Store | DSP | No |
| S2 Validation | DSP | No |
| Report | DSP | No |
| S3 Manual | Operator + DSP templates | No |
| S3 API (experimental) | Stellar HTTP client | Yes (explicit opt-in) |

S2 exit codes and `ValidationResult` are **never** affected by S3 outcomes.

---

## 4. Correct Role of S3

S3 answers: *"Did the target detection platform observe this scenario's traffic as a detection?"*

It does **not** re-validate traffic (that is S2). It correlates external detection evidence against the DSP run context:

- `run_id`
- time window
- source / destination IPs
- scenario type
- operator notes, alert IDs, screenshots

---

## 5. Three S3 Modes

### 5.1 S2 — DSP-Authoritative Validation

- Source: Event Store metrics and validation rules
- Output: `validation.json`, report pass/fail
- Exit code: derived from S2 only
- **Always runs** (unless scenario skipped)

### 5.2 S3 Manual — Operator-Confirmed Detection Evidence (Default)

- Trigger: `dsp run --confirm-detection` (default `--stellar-client manual`)
- Source: DSP-generated templates + operator Stellar UI review
- Output: `evidence/<run_id>/manual/`
  - `s3_manual_checklist.md`
  - `correlation_notes.md`
  - `stellar_ui_evidence_template.md`
  - `s3_result_manual.json`
- Status: `S3_INCONCLUSIVE` with reason `manual_review_required`
- **No API calls. No tokens.**

### 5.3 S3 API — Optional Experimental Automation

- Trigger: explicit flags only:
  ```bash
  dsp run --scenarios dns_tunnel --confirm-detection \
    --detection-provider stellar --stellar-client http
  ```
- Requires: `DSP_STELLAR_BASE_URL`, `DSP_STELLAR_API_TOKEN`
- Output: `evidence/<run_id>/stellar/` (API JSON, detection.log)
- Documented in: `docs/experimental/STELLAR_HTTP_API_MODE.md`
- **Not required for normal DSP operation**

Additional offline mode:

- `--stellar-client mock` — deterministic local responses for CI/demo (not operator workflow)

---

## 6. Recommended Operator Workflow

1. Run DSP scenario: `dsp run --scenarios dns_tunnel`
2. Review S2 in `report.md` / `validation.json`
3. Optional: `dsp run --scenarios dns_tunnel --confirm-detection` for manual S3 templates
4. Open Stellar UI; search by time window, source IP, destination IP
5. Capture alert ID and screenshot
6. Complete `correlation_notes.md`
7. Mark S3 outcome manually in operator records

---

## 7. What Did Not Change

Per Phase 18 non-negotiable rules:

- Scenario execution behavior
- Event Store schema
- S2 validation behavior
- Report pass/fail behavior
- Existing HTTP/mock adapter code (demoted, not deleted)

---

## 8. Related Documents

- [PHASE_18_S3_CORRECTION_REVIEW.md](./PHASE_18_S3_CORRECTION_REVIEW.md)
- [../experimental/STELLAR_HTTP_API_MODE.md](../experimental/STELLAR_HTTP_API_MODE.md)
- [../../DETECTION_ADAPTER_LAYER.md](../../DETECTION_ADAPTER_LAYER.md)
- [../../S3_CONFIRMATION_MATRIX.md](../../S3_CONFIRMATION_MATRIX.md)
