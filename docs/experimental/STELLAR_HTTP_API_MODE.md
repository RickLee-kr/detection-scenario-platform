# Stellar HTTP API Mode (Experimental)

> **Experimental · Optional · Not required · May not apply to all Stellar deployments**

---

## 1. Overview

DSP includes an **experimental** Stellar HTTP client for automated S3 evidence collection. This mode is **not** part of normal DSP operation.

**Default S3 workflow:** manual operator evidence (`--stellar-client manual`).  
**This document:** opt-in API automation for labs with confirmed API access.

---

## 2. When to Use

| Use HTTP mode when… | Do NOT use HTTP mode when… |
|---------------------|----------------------------|
| Lab has verified Stellar REST API access | Normal customer validation (use manual S3) |
| API schema matches `STELLAR_API_CONTRACT.md` | API tokens cannot be issued |
| Automation experiment / integration test | Stellar tenant is UI-only |
| CI with mock transport (tests) | Operator guide is the SOT |

---

## 3. Prerequisites

```bash
export DSP_STELLAR_BASE_URL=https://stellar.lab.example
export DSP_STELLAR_API_TOKEN=<token>

# Optional tuning (see PHASE_12_PRODUCTION_HARDENING.md)
export DSP_STELLAR_VERIFY_TLS=true
export DSP_STELLAR_TIMEOUT_SECONDS=30
export DSP_STELLAR_PAGE_SIZE=100
export DSP_STELLAR_MAX_REQUESTS_PER_RUN=200
```

**Security:** Never commit tokens. Tokens are not written to run artifacts or `detection.log`.

---

## 4. Explicit Invocation

HTTP mode requires **all** of the following:

```bash
source .venv/bin/activate

dsp run --scenarios dns_tunnel \
  --target-net 10.10.10.0/24 \
  --confirm-detection \
  --detection-provider stellar \
  --stellar-client http
```

Without `--stellar-client http`, DSP does **not** call the Stellar API.

---

## 5. Output Artifacts

```
~/.dsp/runs/<run_id>/evidence/<run_id>/stellar/
├── alerts.json
├── analytics.json
├── entities.json
├── timeline.json
├── s3_result.json
├── evidence.md
├── detection.log
└── raw/
```

---

## 6. Failure Behavior

| Condition | S3 status | S2 exit code |
|-----------|-----------|--------------|
| Missing `DSP_STELLAR_BASE_URL` or token | `S3_INCONCLUSIVE` | Unchanged (S2-based) |
| API 5xx / timeout | `S3_INCONCLUSIVE` | Unchanged |
| Empty API response | `S3_NOT_OBSERVED` | Unchanged |
| Correlated evidence | `S3_CONFIRMED` | Unchanged |

Missing credentials in HTTP mode **never** change S2 exit codes.

---

## 7. Mock Mode (CI / Demo)

Offline deterministic responses without API:

```bash
dsp run --scenarios dns_tunnel --dry-run \
  --confirm-detection --stellar-client mock
```

Mock is for **automated testing**, not operator validation.

---

## 8. Limitations

- No post-run delay polling (immediate query at run completion)
- No UI screenshot capture
- API endpoints may differ across Stellar versions
- Not all deployments expose REST detection APIs

For production validation, prefer **manual S3** workflow in `docs/runtime/EXECUTION_GUIDE.md`.

---

## 9. Related Documents

- [../detection/STELLAR_API_CONTRACT.md](../detection/STELLAR_API_CONTRACT.md)
- [../detection/PHASE_12_PRODUCTION_HARDENING.md](../detection/PHASE_12_PRODUCTION_HARDENING.md)
- [../architecture/S3_ARCHITECTURE_CORRECTION.md](../architecture/S3_ARCHITECTURE_CORRECTION.md)
