# Stellar Evidence Model

**Phase:** 10 — Stellar Detection Contract Layer  
**Status:** Normalization contract (no live API)  
**Implementation:** `dsp/detection/providers/stellar/normalization.py`  
**DSP Models:** `dsp/detection/models.py`

---

## 1. Purpose

Define the mapping from Stellar vendor responses to DSP vendor-neutral evidence. Normalization is the boundary between vendor-specific JSON and S3 correlation.

```
Stellar API Response (raw JSON)
        ↓
  sanitize_raw_record()     ← redact secrets before persistence
        ↓
  normalize_*()               ← field mapping
        ↓
  AlertEvidence | AnalyticsEvidence | EntityEvidence | TimelineEvidence
        ↓
  EvidencePack                ← aggregate for correlation
```

---

## 2. Evidence Type Mapping

### 2.1 Stellar Alert → `AlertEvidence`

| Stellar Field | DSP Field | Required | Missing-Field Behavior |
|---------------|-----------|----------|--------------------------|
| `id` or `alert_id` | `evidence_id` | Yes | Skip record (no evidence item) |
| `name` or `alert_name` | `alert_name` | No | Empty string; **not used for correlation** |
| `severity` | `severity` | No | Empty string |
| `observed_at` | `observed_at` | No | `None`; time_window score not applied |
| `entity_refs[]` | `entity_refs` | No | Empty list; IP correlation via refs skipped |
| `detection_model_id` | `attributes.detection_model_id` | No | Used for scenario_type scoring if present |
| — | `vendor` | Yes | `"stellar"` |
| — | `run_id`, `scenario_id` | Yes | From `CorrelationContext` |
| — | `collected_at` | Yes | Query timestamp (UTC) |

**Notes:**

- Alert display name is informational only. Correlation uses `entity_refs`, `observed_at`, and `detection_model_id`.
- Records without `id`/`alert_id` are dropped silently.

---

### 2.2 Stellar Analytics → `AnalyticsEvidence`

| Stellar Field | DSP Field | Required | Missing-Field Behavior |
|---------------|-----------|----------|--------------------------|
| `id` or `incident_id` | `evidence_id`, `incident_id` | Yes | Skip record |
| `analytic_type` or `type` | `analytic_type` | No | Empty string |
| `observed_at` | `observed_at` | No | `None` |
| `summary` | `summary` | No | Empty string |
| `detection_model_id` | `attributes.detection_model_id` | No | Used for scenario_type scoring |

**Contract alignment:** `analytic_type` should match contract `analytics_types` when present, but mismatch does not invalidate the record.

---

### 2.3 Stellar Entity → `EntityEvidence`

| Stellar Field | DSP Field | Required | Missing-Field Behavior |
|---------------|-----------|----------|--------------------------|
| `id` or `entity_id` | `evidence_id` | Yes | Skip record |
| `entity_type` or `type` | `entity_type` | No | Empty string |
| `entity_value` or `value` | `entity_value` | No | Empty string |
| `role` | `role` | No | Empty string |

**IP correlation:** When `entity_type` ∈ `{ip, host, endpoint}` and `entity_value` matches `CorrelationContext.source_ip` or `destination_ip`, IP dimension scores apply.

---

### 2.4 Stellar Timeline → `TimelineEvidence`

| Stellar Field | DSP Field | Required | Missing-Field Behavior |
|---------------|-----------|----------|--------------------------|
| `id` or `event_id` | `evidence_id` | Yes | Skip record |
| `event_type` or `type` | `event_type` | No | Empty string |
| `observed_at` | `observed_at` | No | `None` |
| `description` | `description` | No | Empty string |

Timeline evidence supports narrative confirmation but is optional for all scenarios.

---

## 3. Common Base Fields (`EvidenceBase`)

All evidence types inherit:

| Field | Required | Description |
|-------|----------|-------------|
| `evidence_id` | Yes | Stable vendor identifier |
| `vendor` | Yes | `"stellar"` |
| `collected_at` | Yes | Normalization timestamp |
| `run_id` | Yes | DSP run identifier |
| `scenario_id` | Yes | DSP scenario identifier |
| `correlation_score` | No | Set by `correlation.py` (default 0.0) |
| `raw_ref` | No | Pointer to sanitized raw JSON |
| `attributes` | No | Vendor extensions (e.g. `detection_model_id`) |

---

## 4. EvidencePack Assembly

`build_evidence_pack()` aggregates normalized lists:

```python
EvidencePack(
    run_id=context.run_id,
    scenario_id=context.scenario_id,
    vendor="stellar",
    alerts=[...],
    analytics=[...],
    entities=[...],
    timeline=[...],
)
```

| Property | Rule |
|----------|------|
| `evidence_count` | Sum of all list lengths |
| Required evidence types | Defined per scenario in `scenario_contracts.yaml` |
| Missing required type | Does not block pack creation; affects S3 status via correlation |

---

## 5. Required Evidence by Scenario

| Scenario | Required | Optional |
|----------|----------|----------|
| `dns_tunnel` | alert, analytics, entity | timeline |
| `dga` | alert, analytics | entity, timeline |
| `http_followup` | alert, analytics | entity, timeline |
| `ssh_failure` | alert, analytics, entity | timeline |
| `sql_injection` | alert, analytics | entity, timeline |

**Missing required evidence behavior (Phase 10 contract):**

- Pack is still produced with available types
- Correlation score may fall below `CONFIRMED_THRESHOLD` (0.70)
- Status likely `S3_INCONCLUSIVE` unless remaining evidence scores highly on time/IP dimensions

---

## 6. Raw Persistence

Sanitized raw JSON is written to:

```
<run_dir>/evidence/<run_id>/stellar/raw/{alerts,analytics,entities,timeline}.json
```

`sanitize_raw_record()` redacts keys matching `(token|secret|password|authorization|api_key|apikey)`.

---

## 7. Phase 11 Considerations

Live Stellar API responses may use different field names. Phase 11 will extend normalization with alias maps **without** changing DSP evidence models or correlation logic.

---

## 8. Related Files

| File | Role |
|------|------|
| `normalization.py` | Normalization implementation |
| `models.py` | Vendor-neutral evidence dataclasses |
| `contracts/scenario_contracts.yaml` | Required evidence per scenario |
| `STELLAR_CORRELATION_RULES.md` | How evidence scores map to S3 status |
