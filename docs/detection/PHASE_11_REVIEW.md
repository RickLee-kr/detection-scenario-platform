# Phase 11 Review — Real Stellar API Integration

**Phase:** 11  
**Status:** COMPLETE  
**Date:** 2026-06-05

---

## Goals Achieved

| Goal | Status |
|------|--------|
| Real HTTP integration via `StellarHttpClient` | Done |
| Contract-driven query generation | Done |
| Evidence collection to `evidence/<run_id>/stellar/` | Done |
| Normalization with `stellar_aliases.yaml` | Done |
| Correlation-based S3 (unchanged scoring) | Done |
| `detection.log` observability (no tokens) | Done |
| Mock mode backward compatible | Done |
| S2 authority preserved | Done |

---

## New / Updated Artifacts

| File | Role |
|------|------|
| `query_builder.py` | Contract → API query builder |
| `stellar_aliases.yaml` | Vendor field aliases |
| `detection_logger.py` | Structured detection logging |
| `STELLAR_API_CONTRACT.md` | HTTP endpoint contract |
| `http_client.py` | GET/POST, retry, parse |
| `stellar_adapter.py` | Contract-driven collection |
| `normalization.py` | Alias-aware normalization |
| `tests/detection/test_stellar_integration.py` | Integration tests |

---

## Usage

```bash
# Mock (offline, default)
dsp run --scenarios dns_tunnel --confirm-detection

# Live Stellar API
export DSP_STELLAR_BASE_URL=https://stellar.lab.example
export DSP_STELLAR_API_TOKEN=<token>
dsp run --scenarios dns_tunnel --confirm-detection --stellar-client http
```

---

## Phase 12 Candidates

- Live lab validation against real Stellar appliance
- Consolidate `scenario_mapping.yaml` and `scenario_contracts.yaml`
- Optional evidence polling toggle via CLI
- Query result pagination
