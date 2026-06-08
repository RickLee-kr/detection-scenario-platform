# Stellar API Contract

**Phase:** 11 — Real Stellar API Integration  
**Status:** Implemented (HTTP client + mock transport)  
**Base URL:** `DSP_STELLAR_BASE_URL`  
**Authentication:** `Authorization: Bearer <DSP_STELLAR_API_TOKEN>`

---

## 1. Overview

All endpoints return JSON with a top-level `items` array. Non-2xx responses produce `StellarSearchResult.error` without failing the DSP run (S3 → `S3_INCONCLUSIVE`).

| Endpoint | Method | Path |
|----------|--------|------|
| Alerts | GET | `/api/v1/detection/alerts` |
| Analytics | POST | `/api/v1/detection/analytics` |
| Entities | GET | `/api/v1/detection/entities` |
| Timeline | GET | `/api/v1/detection/timeline` |

Query parameters are built by `query_builder.py` from `scenario_contracts.yaml`.

---

## 2. Common Request Fields

| Field | Required | Description |
|-------|----------|-------------|
| `run_id` | Yes | DSP run identifier |
| `scenario_id` | Yes | DSP scenario identifier |
| `start` | Yes | ISO-8601 UTC window start |
| `end` | Yes | ISO-8601 UTC window end |
| `detection_model_id` | Yes | Stable model reference (`stellar.dns_tunnel`, etc.) |
| `category` | Yes | Detection category from contract |
| `source_ip` | Conditional | Required when contract marks dimension required |
| `destination_ip` | Conditional | Per contract query dimensions |
| `hostname` | Conditional | Per contract query dimensions |
| `username` | Conditional | Per contract (e.g. `ssh_failure`) |
| `protocol` | Conditional | `dns`, `http`, `ssh` |
| `port` | Conditional | Service port when required |

**Unknown request fields:** Ignored by Stellar; included in query only when contract dimensions apply.

---

## 3. Alerts Endpoint

### Request

```
GET /api/v1/detection/alerts?run_id=...&scenario_id=...&start=...&end=...
    &detection_model_id=stellar.dns_tunnel&category=DNS+Tunnel
    &source_ip=10.10.10.5&protocol=dns&port=53
    &alert_families=DNS+Tunnel&alert_families=DNS+Exfiltration
```

| Field | Required | Notes |
|-------|----------|-------|
| `alert_families` | Optional | Repeatable; hint only, not sole correlation signal |

### Response

```json
{
  "items": [
    {
      "id": "alert-abc123",
      "name": "DNS Tunnel Detected",
      "severity": "high",
      "observed_at": "2026-06-05T12:00:00Z",
      "entity_refs": ["10.10.10.5", "10.10.10.53"],
      "detection_model_id": "stellar.dns_tunnel"
    }
  ]
}
```

| Field | Required | Normalized To |
|-------|----------|---------------|
| `id` / `alert_id` | Yes | `AlertEvidence.evidence_id` |
| `name` / `alert_name` | No | `AlertEvidence.alert_name` |
| `severity` | No | `AlertEvidence.severity` |
| `observed_at` | No | `AlertEvidence.observed_at` |
| `entity_refs` | No | `AlertEvidence.entity_refs` |
| `detection_model_id` | No | `attributes.detection_model_id` |

**Unknown fields:** Preserved in raw JSON (sanitized); ignored during normalization unless aliased in `stellar_aliases.yaml`.

---

## 4. Analytics Endpoint

### Request

```
POST /api/v1/detection/analytics
Content-Type: application/json

{
  "run_id": "...",
  "scenario_id": "dns_tunnel",
  "start": "2026-06-05T11:58:00Z",
  "end": "2026-06-05T12:30:00Z",
  "detection_model_id": "stellar.dns_tunnel",
  "category": "DNS Tunnel",
  "source_ip": "10.10.10.5",
  "analytics_types": ["dns_query_volume_anomaly", "long_subdomain_pattern"]
}
```

### Response

```json
{
  "items": [
    {
      "id": "incident-xyz",
      "analytic_type": "dns_query_volume_anomaly",
      "observed_at": "2026-06-05T12:01:00Z",
      "summary": "Elevated DNS query volume from 10.10.10.5",
      "detection_model_id": "stellar.dns_tunnel"
    }
  ]
}
```

| Field | Required | Normalized To |
|-------|----------|---------------|
| `id` / `incident_id` | Yes | `AnalyticsEvidence.evidence_id` |
| `analytic_type` / `type` | No | `AnalyticsEvidence.analytic_type` |
| `observed_at` | No | `AnalyticsEvidence.observed_at` |
| `summary` | No | `AnalyticsEvidence.summary` |

---

## 5. Entities Endpoint

### Request

```
GET /api/v1/detection/entities?run_id=...&entity_types=ip&entity_types=domain
    &source_ip=10.10.10.5&detection_model_id=stellar.dns_tunnel
```

### Response

```json
{
  "items": [
    {
      "id": "entity-src-001",
      "entity_type": "ip",
      "entity_value": "10.10.10.5",
      "role": "source_ip"
    }
  ]
}
```

| Field | Required | Normalized To |
|-------|----------|---------------|
| `id` / `entity_id` | Yes | `EntityEvidence.evidence_id` |
| `entity_type` / `type` | No | `EntityEvidence.entity_type` |
| `entity_value` / `value` | No | `EntityEvidence.entity_value` |
| `role` | No | `EntityEvidence.role` |

Vendor aliases (`srcip`, `dstip`) are resolved via `stellar_aliases.yaml` before normalization.

---

## 6. Timeline Endpoint

### Request

```
GET /api/v1/detection/timeline?run_id=...&protocol=dns&start=...&end=...
```

### Response

```json
{
  "items": [
    {
      "id": "timeline-001",
      "event_type": "dns_detection",
      "observed_at": "2026-06-05T12:00:30Z",
      "description": "DNS tunnel pattern observed"
    }
  ]
}
```

| Field | Required | Normalized To |
|-------|----------|---------------|
| `id` / `event_id` | Yes | `TimelineEvidence.evidence_id` |
| `event_type` / `type` | No | `TimelineEvidence.event_type` |
| `observed_at` | No | `TimelineEvidence.observed_at` |
| `description` | No | `TimelineEvidence.description` |

---

## 7. Error Responses

| HTTP Status | Client Error | S3 Impact |
|-------------|--------------|-----------|
| 401, 403 | `StellarAuthError` | `S3_INCONCLUSIVE` |
| 404 | `StellarHttpError` | `S3_INCONCLUSIVE` |
| 400–499 | `StellarHttpError` | `S3_INCONCLUSIVE` |
| 500–504 | `StellarHttpError` (retried) | `S3_INCONCLUSIVE` |
| Timeout | `StellarTimeoutError` (retried) | `S3_INCONCLUSIVE` |
| Invalid JSON | `StellarParseError` | `S3_INCONCLUSIVE` |
| Missing config | `StellarConfigError` | `S3_INCONCLUSIVE` |

**Empty `items`:** Valid response → normalization produces empty lists → `S3_NOT_OBSERVED` if no other evidence.

---

## 8. Security

- API token sent only in `Authorization` header during HTTP requests
- Token never written to evidence files, `detection.log`, or sanitized raw JSON
- `sanitize_raw_record()` redacts secret-like keys before persistence

---

## 9. Related Files

| File | Role |
|------|------|
| `http_client.py` | HTTP transport, retry, parse |
| `query_builder.py` | Contract → request builder |
| `stellar_aliases.yaml` | Vendor field aliases |
| `normalization.py` | Vendor → DSP evidence |
| `scenario_contracts.yaml` | Per-scenario query strategy |
