# Phase 12 — Production Hardening of Detection Validation

**Phase:** 12  
**Status:** COMPLETE  
**Date:** 2026-06-06

---

## Goals Achieved

| Goal | Status |
|------|--------|
| Stellar pagination (alerts, analytics, entities, timeline) | Done |
| Query throttling with retry backoff | Done |
| Evidence size protection with safe truncation | Done |
| Per-run detection query cache | Done |
| Enhanced `detection.log` observability | Done |
| Integration tests for hardening behaviors | Done |
| S2 authority preserved | Done |
| S3 optionality preserved | Done |
| No API token leakage | Done |

---

## 1. Pagination Design

`StellarHttpClient._search()` follows `next_page_token` until exhausted.

### Request fields

| Field | Source | Purpose |
|-------|--------|---------|
| `page_size` | `DSP_STELLAR_PAGE_SIZE` (default 100) | Items per page |
| `page_token` | prior response `next_page_token` | Next page cursor |

Applied to both GET query strings and POST JSON bodies.

### Response fields

Accepted token locations (first non-empty wins):

- Top-level: `next_page_token`, `nextPageToken`, `page_token`, `cursor`
- Nested: `pagination.next_page_token`, etc.

### Aggregation rules

1. Append `items` from every page into one result.
2. Stop when `next_page_token` is absent or empty.
3. Empty final pages are valid terminal pages.
4. `StellarSearchResult.page_count` and `total_fetched` reflect the full collection.

Evidence collection always receives the aggregated list; normalization and S3 scoring are unchanged.

---

## 2. Throttling Design

Implemented in `query_throttle.py` and wired into `http_client.py`.

| Setting | Env Variable | Default |
|---------|--------------|---------|
| Inter-request delay | `DSP_STELLAR_REQUEST_DELAY_SECONDS` | `0.0` |
| Max requests per run | `DSP_STELLAR_MAX_REQUESTS_PER_RUN` | `200` |
| Retry attempts | `DSP_STELLAR_MAX_RETRIES` | `2` |
| Retry backoff base | `DSP_STELLAR_RETRY_BACKOFF_SECONDS` | `0.05` |

### Behavior

- `QueryThrottle.before_request()` runs before every HTTP call (including pagination pages).
- Delay is enforced between consecutive requests when configured.
- When the request budget is exhausted, `StellarRateLimitError` is returned — the run does not crash.
- Retryable 5xx and timeouts use linear backoff: `backoff * (attempt + 1)`.

`StellarHttpClient.reset_run_state()` clears the per-run counter at the start of each `collect_evidence()` call.

---

## 3. Cache Design

Implemented in `detection_cache.py` and used by `StellarAdapter._search()`.

### Cache key

| Component | Source |
|-----------|--------|
| `scenario_id` | correlation context |
| `run_id` | correlation context |
| `provider` | adapter `vendor_id` (`stellar`) |
| `evidence_type` | alert / analytics / entity / timeline |
| query window | `time_window_start` + `time_window_end` |
| query fingerprint | SHA-256 of normalized query payload |

### Lifetime

- Scope: **single detection run only**
- Cleared at the start of every `collect_evidence()` call
- Not persisted to disk

### Cache hit behavior

- Skips HTTP transport
- Logs `query_response` with `cache_hit: true`
- Returns cached `StellarSearchResult` items

---

## 4. Evidence Limits

Implemented in `evidence_limits.py`.

| Category | Env Variable | Default |
|----------|--------------|---------|
| Alerts | `DSP_STELLAR_MAX_ALERTS` | `500` |
| Analytics | `DSP_STELLAR_MAX_ANALYTICS` | `500` |
| Entities | `DSP_STELLAR_MAX_ENTITIES` | `500` |
| Timeline | `DSP_STELLAR_MAX_TIMELINE` | `1000` |

### Truncation rules

1. Applied after all pages are aggregated, before normalization.
2. Retains the first N items (stable ordering).
3. Never raises — oversized responses are trimmed safely.
4. `evidence.md` records per-category truncation when applicable.
5. `detection.log` emits `evidence_truncated` with counts.

HTTP mode loads limits from `StellarConfig`; tests may inject `EvidenceLimitConfig` directly.

---

## 5. Observability (`detection.log`)

JSON-lines events (secrets redacted automatically):

| Event | Fields |
|-------|--------|
| `provider_selected` | provider, client_mode |
| `query_executed` | evidence_type, http_method, api_path, cache_hit=false |
| `query_response` | response_count, total_fetched, page_count, execution_time_ms, cache_hit, http_status |
| `evidence_truncated` | truncation summary |
| `normalization_complete` | raw_response_counts, pagination_counts, normalization_counts, evidence_counts |
| `s3_decision` | status, correlation_score, reason, evidence_count |

**Never logged:** API tokens, credentials, authorization headers.

---

## 6. New / Updated Artifacts

| File | Role |
|------|------|
| `query_throttle.py` | Per-run delay, budget, retry backoff |
| `detection_cache.py` | Single-run query deduplication |
| `evidence_limits.py` | Safe truncation and metadata |
| `http_client.py` | Pagination loop, throttle integration |
| `stellar_config.py` | Phase 12 env configuration |
| `stellar_adapter.py` | Cache, limits, enhanced logging |
| `client_base.py` | Extended `StellarSearchResult` metadata |
| `tests/detection/test_stellar_phase12.py` | Hardening integration tests |

---

## 7. Operational Guidance

### Recommended live settings

```bash
export DSP_STELLAR_BASE_URL=https://stellar.lab.example
export DSP_STELLAR_API_TOKEN=<token>
export DSP_STELLAR_PAGE_SIZE=100
export DSP_STELLAR_REQUEST_DELAY_SECONDS=0.25
export DSP_STELLAR_MAX_REQUESTS_PER_RUN=200
export DSP_STELLAR_MAX_ALERTS=500
export DSP_STELLAR_MAX_ANALYTICS=500
export DSP_STELLAR_MAX_ENTITIES=500
export DSP_STELLAR_MAX_TIMELINE=1000

dsp run --scenarios dns_tunnel --confirm-detection --stellar-client http
```

### Tuning tips

- **Large tenants:** Lower `DSP_STELLAR_PAGE_SIZE` if responses are slow; raise `DSP_STELLAR_REQUEST_DELAY_SECONDS` to avoid rate limits.
- **Noisy scenarios:** Reduce evidence caps to keep artifacts small; truncation is recorded in `evidence.md`.
- **Repeated evidence types in one run:** Cache prevents duplicate identical queries automatically.
- **Partial failures:** A failed page after successful pages returns partial items plus error; adapter marks S3 as `S3_INCONCLUSIVE`.

### Troubleshooting

| Symptom | Check |
|---------|-------|
| `max request limit reached` | Raise `DSP_STELLAR_MAX_REQUESTS_PER_RUN` or narrow search window |
| Truncation in `evidence.md` | Raise category caps or tighten contract dimensions |
| High `page_count` in `detection.log` | Expected for large result sets; verify pagination tokens in Stellar responses |
| `cache_hit: true` | Duplicate query within same run — expected, not a Stellar API call |

---

## 8. Unchanged by Design

Per Phase 12 constraints, the following were **not** modified:

- Event Store schema
- Validation Engine (S2)
- Reporting Engine
- Scenario implementations
- Detection scoring model (`correlation.py`)

S2 remains authoritative. S3 remains optional (`--confirm-detection`).

---

## 9. Related Documentation

- [STELLAR_API_CONTRACT.md](./STELLAR_API_CONTRACT.md)
- [PHASE_11_REVIEW.md](./PHASE_11_REVIEW.md)
- [STELLAR_CORRELATION_RULES.md](./STELLAR_CORRELATION_RULES.md)
