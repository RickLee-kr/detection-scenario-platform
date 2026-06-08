# Stellar Correlation Rules

**Phase:** 10 — Stellar Detection Contract Layer  
**Status:** Correlation contract (no live API)  
**Implementation:** `dsp/detection/correlation.py`

---

## 1. Purpose

Define how vendor-neutral evidence is scored and mapped to S3 status. Correlation is **evidence-based**: run identity, time window, IP entities, and scenario type — not alert title strings.

---

## 2. Correlation Dimensions

| Dimension | Weight | Signal |
|-----------|--------|--------|
| `run_id` | 0.30 | Evidence item `run_id` matches `CorrelationContext.run_id` |
| `time_window` | 0.25 | `observed_at` within `[time_window_start, time_window_end]` |
| `source_ip` | 0.15 | Entity or alert `entity_refs` matches context source IP |
| `destination_ip` | 0.15 | Entity or alert `entity_refs` matches context destination IP |
| `scenario_type` | 0.15 | `detection_model_id` suffix or `scenario_id` matches context |

**Maximum score:** 1.0 (capped per item)

**Aggregate score:** `max(individual item scores)` across the evidence pack

---

## 3. Thresholds and S3 Status

| Status | Condition |
|--------|-----------|
| **S3_CONFIRMED** | S2 success AND evidence_count > 0 AND aggregate_score ≥ **0.70** |
| **S3_INCONCLUSIVE** | S2 ≠ success OR (evidence present AND 0.40 ≤ score < 0.70) |
| **S3_NOT_OBSERVED** | evidence_count = 0 OR score < **0.40** |

Constants (from `correlation.py`):

```python
CONFIRMED_THRESHOLD = 0.70
INCONCLUSIVE_THRESHOLD = 0.40
```

---

## 4. Why Alert Name Matching Alone Is Insufficient

### 4.1 Alert names are not stable

Stellar alert titles may change across:

- Product version upgrades
- Localization
- Custom detection rule renames
- Tenant-specific rule naming

A query or correlation rule like `alert_name == "DNS Tunnel Detected"` will silently break when the vendor renames the alert to `"Suspicious DNS Exfiltration"`.

### 4.2 False positives from name-only matching

Generic alert titles (e.g. `"Suspicious Network Activity"`) may match unrelated traffic from other lab runs or background noise.

### 4.3 Evidence-based correlation is auditable

Scoring on `run_id`, time window, IP entities, and `detection_model_id` produces reproducible, explainable S3 reasons:

```
correlation_score=0.85 meets confirmed threshold
```

versus opaque name matches that cannot be validated against Event Store ground truth.

---

## 5. Worked Examples

### Example A — S3_CONFIRMED (`dns_tunnel`)

**Context:**

- run_id: `20260605_stellar01`
- source_ip: `10.10.10.5`
- destination_ip: `10.10.10.53`
- time window: run start − 2 min → run end + 30 min

**Evidence item (Alert):**

- run_id: `20260605_stellar01` → +0.30
- observed_at: within window → +0.25
- entity_refs: `["10.10.10.5"]` → +0.15 (source_ip)
- detection_model_id: `stellar.dns_tunnel` → +0.15 (scenario_type)

**Score:** 0.85 → **S3_CONFIRMED**

Alert name `"DNS Exfiltration Alert v3"` is irrelevant to the score.

---

### Example B — S3_NOT_OBSERVED (empty vendor response)

**Context:** Valid S2 success, mock client returns zero items.

**Evidence pack:** evidence_count = 0

**Status:** **S3_NOT_OBSERVED**  
**Reason:** `no vendor evidence returned`

---

### Example C — S3_INCONCLUSIVE (wrong time window)

**Context:**

- run_id matches
- source_ip matches via entity
- observed_at: **outside** time window

**Score:** 0.30 (run_id) + 0.15 (source_ip) = 0.45

**Status:** **S3_INCONCLUSIVE** (0.40 ≤ 0.45 < 0.70)

---

### Example D — S3_INCONCLUSIVE (S2 failure)

**Context:** S2 decision = `fail_fast`

**Status:** **S3_INCONCLUSIVE** regardless of vendor evidence  
**Reason:** `s2_decision=fail_fast; detection poll skipped`

---

### Example E — Alert name match would mislead

Two alerts in the search window:

| Alert Name | source_ip ref | run_id | Score |
|------------|---------------|--------|-------|
| `"DNS Tunnel Detected"` | unrelated IP | different run | 0.25 (time only) |
| `"Generic Anomaly"` | `10.10.10.5` | matching run | 0.85 |

Name-based selection picks the wrong alert. Evidence-based scoring selects the second item via aggregate max.

---

## 6. Contract Integration

`scenario_contracts.yaml` defines:

- **Required evidence types** — informs completeness expectations, not hard S3 gates in Phase 10
- **Confidence** — documents expected confirmation reliability when dimensions align
- **Search window** — feeds time_range construction for queries (Phase 11)

Phase 11 may add contract-aware weight adjustments (e.g. boost analytics match for `dga`) without changing core dimension weights.

---

## 7. Non-Goals

- No alert title regex matching
- No modification of S2 ValidationResult
- No Event Store writes from correlation layer

---

## 8. Related Files

| File | Role |
|------|------|
| `correlation.py` | Scoring and status determination |
| `models.py` | `CorrelationContext`, `S3Status`, `EvidencePack` |
| `contracts/scenario_contracts.yaml` | Per-scenario evidence expectations |
| `STELLAR_DETECTION_CONTRACT.md` | Scenario-level detection categories |
