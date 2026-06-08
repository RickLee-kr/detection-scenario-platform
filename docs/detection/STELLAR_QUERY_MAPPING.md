# Stellar Query Mapping

**Phase:** 10 — Stellar Detection Contract Layer  
**Status:** Query strategy definition (no live API)  
**Configuration:** `dsp/detection/providers/stellar/contracts/scenario_contracts.yaml`

---

## 1. Purpose

Define how DSP builds Stellar search queries from `CorrelationContext` (Event Store–derived run metadata). Queries are **dimension-based**; alert names are hints only and must not be the sole filter.

---

## 2. Search Dimensions

| Dimension | Description | Source |
|-----------|-------------|--------|
| `source_ip` | Client / attacker IP | Event Store evidence |
| `destination_ip` | Target / resolver / server IP | Event Store evidence |
| `hostname` | FQDN, Host header, or domain | Event Store / scenario defaults |
| `username` | SSH or auth username | Event Store (ssh_failure) |
| `protocol` | `dns`, `http`, `ssh` | Scenario contract |
| `port` | Service port (53, 22, 80, 443) | Scenario contract |
| `time_range` | `[window_start, window_end]` | Run timestamps + contract window |

### Priority Levels

| Level | Meaning |
|-------|---------|
| **Required** | Query must include this dimension; missing → fallback or S3_INCONCLUSIVE |
| **Optional** | Include when available; improves precision |
| **Nice-to-have** | Include when trivially available; no fallback if absent |

---

## 3. Default Search Windows

| Scenario | Default Window | Rationale |
|----------|----------------|-----------|
| `dns_tunnel` | 30 min | DNS tunnel queries may span multi-minute transmission |
| `dga` | 30 min | DGA bursts may lag initial queries |
| `http_followup` | 15 min | HTTP recon is typically short-lived |
| `ssh_failure` | 30 min | Brute-force attempts may span many retries |
| `sql_injection` | 15 min | Web attack probes are usually rapid |

**Window construction:**

```
window_start = run.started_at - 2 min (pre-buffer)
window_end   = run.ended_at   + search_window_minutes (from contract)
```

Pre-buffer aligns with `correlation.py` `TIME_WINDOW_PRE_BUFFER`. Post-buffer uses contract `search_window_minutes` instead of the fixed 30-minute default in Phase 7–9 correlation (Phase 11 may unify these).

---

## 4. Per-Scenario Query Strategy

### 4.1 `dns_tunnel`

| Dimension | Priority |
|-----------|----------|
| source_ip | Required |
| destination_ip | Optional |
| hostname | Required |
| username | Nice-to-have |
| protocol | Required (`dns`) |
| port | Required (`53`) |
| time_range | Required |

**Query endpoints:** alerts, analytics, entities, timeline (optional)

**Example query shape (conceptual):**

```
alerts:     source_ip=10.10.10.5, protocol=dns, time=[T0, T1]
analytics:  analytic_type IN (dns_query_volume_anomaly, long_subdomain_pattern)
entities:   entity_type IN (ip, domain), role=source_ip
```

---

### 4.2 `dga`

| Dimension | Priority |
|-----------|----------|
| source_ip | Required |
| destination_ip | Optional |
| hostname | Required |
| username | Nice-to-have |
| protocol | Required (`dns`) |
| port | Required (`53`) |
| time_range | Required |

**Query endpoints:** alerts, analytics; entities optional

---

### 4.3 `http_followup`

| Dimension | Priority |
|-----------|----------|
| source_ip | Required |
| destination_ip | Required |
| hostname | Optional |
| username | Nice-to-have |
| protocol | Required (`http`) |
| port | Optional (`80`, `443`) |
| time_range | Required |

**Query endpoints:** alerts, analytics; entities/timeline optional

---

### 4.4 `ssh_failure`

| Dimension | Priority |
|-----------|----------|
| source_ip | Required |
| destination_ip | Required |
| hostname | Optional |
| username | Required |
| protocol | Required (`ssh`) |
| port | Required (`22`) |
| time_range | Required |

**Query endpoints:** alerts, analytics, entities

---

### 4.5 `sql_injection`

| Dimension | Priority |
|-----------|----------|
| source_ip | Required |
| destination_ip | Required |
| hostname | Optional |
| username | Nice-to-have |
| protocol | Required (`http`) |
| port | Optional (`80`, `443`) |
| time_range | Required |

**Query endpoints:** alerts, analytics; entities/timeline optional

---

## 5. Fallback Behavior

When required dimensions are missing from Event Store evidence, apply contract `fallback` rules before querying Stellar.

| Fallback Key | Behavior |
|--------------|----------|
| `missing_source_ip` | Widen time window; query by protocol + time only; expect lower correlation score |
| `missing_destination_ip` | Query by source_ip + time_range; mark result S3_INCONCLUSIVE if score < 0.70 |
| `missing_hostname` | Use protocol + IP pair filters; rely on analytics types |
| `missing_username` | (ssh_failure) Use IP pair + `ssh_auth_failure_burst` analytics |
| `empty_alerts` | Continue with analytics and/or entities; do not fail query |
| `empty_analytics` | Continue with alerts and entities |

**Global fallback chain:**

1. Attempt full-dimension query per contract
2. Apply scenario-specific fallback from YAML
3. If no evidence returned → `S3_NOT_OBSERVED`
4. If evidence returned but score 0.40–0.69 → `S3_INCONCLUSIVE`
5. If S2 decision ≠ success → `S3_INCONCLUSIVE` (no query in production path)

---

## 6. Phase 11 Integration Notes

Phase 11 will map these dimensions to Stellar HTTP API query parameters. Until live API schemas are confirmed:

- Use `detection_model_id` as primary scenario filter
- Pass `alert_families` and `analytics_types` as hints, not hard filters
- Never filter queries on exact alert title strings

---

## 7. Related Files

| File | Role |
|------|------|
| `contracts/scenario_contracts.yaml` | Per-scenario dimensions and fallback |
| `scenario_mapping.yaml` | Alert family and analytics type hints |
| `client_base.py` | `StellarSearchParams` transport contract |
| `correlation.py` | Time window and IP extraction |
