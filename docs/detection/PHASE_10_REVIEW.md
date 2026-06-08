# Phase 10 Review — Stellar Detection Contract Layer

**Phase:** 10  
**Status:** COMPLETE (contract definition)  
**Date:** 2026-06-05

---

## 1. Goals

Phase 10 establishes a formal **Stellar Detection Contract Layer** that defines how DSP scenarios map to Stellar detections without implementing live API integration.

| Goal | Status |
|------|--------|
| Detection contract per scenario | Done |
| Query strategy and dimension mapping | Done |
| Evidence normalization contract | Done |
| Correlation rules documentation | Done |
| Configuration-driven YAML contracts | Done |
| Contract validation tests | Done |
| No changes to Event Store / Validation / Reporting / S2 | Verified |
| No real Stellar API calls | Verified |

---

## 2. Deliverables

### Documentation (`docs/detection/`)

| File | Description |
|------|-------------|
| `STELLAR_DETECTION_CONTRACT.md` | Per-scenario detection categories, evidence sources, entity/analytics types |
| `STELLAR_QUERY_MAPPING.md` | Search dimensions, windows, fallback behavior |
| `STELLAR_EVIDENCE_MODEL.md` | Stellar → DSP evidence field mapping |
| `STELLAR_CORRELATION_RULES.md` | Scoring weights, thresholds, S3 status rules |
| `PHASE_10_REVIEW.md` | This document |

### Configuration

| File | Description |
|------|-------------|
| `dsp/detection/providers/stellar/contracts/scenario_contracts.yaml` | Machine-readable scenario contracts |
| `dsp/detection/providers/stellar/contracts/contract_loader.py` | YAML loader and validator |

### Tests

| File | Coverage |
|------|----------|
| `tests/detection/test_stellar_contracts.py` | Load, completeness, required fields, malformed YAML, confidence enum |

---

## 3. Architecture Summary

```
DSP Scenario (manifest id)
        ↓
scenario_contracts.yaml     ← category, confidence, search window, required evidence
        ↓
Query Strategy              ← dimensions + fallback (STELLAR_QUERY_MAPPING.md)
        ↓
Stellar Client (mock/http)  ← Phase 7–9 scaffold; Phase 11 live
        ↓
normalization.py            ← vendor JSON → EvidencePack
        ↓
correlation.py              ← evidence-based S3 scoring
        ↓
S3Result                    ← S3_CONFIRMED | S3_NOT_OBSERVED | S3_INCONCLUSIVE
```

---

## 4. Scenarios Covered

| Scenario ID | Detection Model ID | Search Window | Confidence |
|-------------|-------------------|---------------|------------|
| `dns_tunnel` | `stellar.dns_tunnel` | 30 min | HIGH |
| `dga` | `stellar.dga` | 30 min | HIGH |
| `http_followup` | `stellar.http_recon` | 15 min | HIGH |
| `ssh_failure` | `stellar.ssh_login_failure` | 30 min | HIGH |
| `sql_injection` | `stellar.sql_injection` | 15 min | HIGH |

---

## 5. Risks

| Risk | Mitigation |
|------|------------|
| Stellar API field names differ from mock schema | Phase 11 alias map in normalization; contracts unchanged |
| Alert families in YAML become stale | Treat as hints; correlation remains evidence-based |
| Search window mismatch with vendor detection latency | Tunable per scenario in `scenario_contracts.yaml` |
| Dual mapping files (`scenario_mapping.yaml` + `scenario_contracts.yaml`) | Phase 11 may consolidate; contracts are canonical for Phase 10+ |
| Contract loader not yet wired into adapter query path | Intentional — Phase 11 integrates loader with HTTP client |

---

## 6. Unknowns (Require Stellar API Discovery in Phase 11)

| Unknown | Impact |
|---------|--------|
| Exact REST query parameter names for alerts/analytics/entities/timeline | HTTP client query builder |
| Pagination and rate limits | Polling strategy |
| Auth token refresh semantics | Client retry behavior |
| Whether `detection_model_id` is a filterable API field | Query strategy |
| Live analytics type identifiers vs. mock values | Normalization aliases |
| Entity role vocabulary (`source_ip` vs. `src`) | Entity correlation accuracy |
| Timeline API availability and schema | Optional evidence collection |
| Detection latency (time from scenario end to alert visibility) | Search window tuning |

---

## 7. Required Stellar API Information (Phase 11 Checklist)

- [ ] Base URL and authentication method (Bearer token confirmed in scaffold)
- [ ] Alert search endpoint: supported filters (IP, time, protocol, model ID)
- [ ] Analytics search endpoint: filter by `analytic_type`
- [ ] Entity search endpoint: filter by `entity_type` and `role`
- [ ] Timeline search endpoint: availability and filters
- [ ] Response JSON schemas (sample payloads from lab appliance)
- [ ] Error response format and retry guidance
- [ ] Maximum query time range per request
- [ ] Detection model ID registry (stable identifiers)

---

## 8. Readiness for Phase 11

| Prerequisite | Ready |
|--------------|-------|
| Scenario → detection contract defined | Yes |
| Query dimensions documented | Yes |
| Evidence model mapping documented | Yes |
| Correlation rules documented and implemented | Yes |
| YAML contracts loadable and validated | Yes |
| Mock client for offline development | Yes (Phase 7–9) |
| HTTP client scaffold | Yes (Phase 8–9) |
| Live API query implementation | No — Phase 11 scope |
| Contract loader integrated into adapter | No — Phase 11 scope |

**Recommendation:** Phase 11 should begin by collecting live API response samples from the Stellar lab appliance, then wire `load_scenario_contracts()` into `StellarHttpClient` query construction while preserving existing correlation and normalization interfaces.

---

## 9. Out of Scope (Confirmed)

- Event Store modifications
- Validation Engine modifications
- Reporting Engine modifications
- Existing scenario executor logic changes
- S2 behavior changes
- Production Stellar API calls
- Alert name–based correlation

---

## 10. Version

| Component | Version |
|-----------|---------|
| Contract schema | 1.0.0 |
| Implemented scenarios | 5 |
| Prior phases complete | 0–9 |
