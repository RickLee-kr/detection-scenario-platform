# S3 Confirmation Matrix — Phase 6.5

**문서 버전:** 1.0.0  
**상태:** Documentation only  
**목적:** S1 / S2 / S3 상태 정의 및 시나리오별 Stellar 확인 요건

---

## 1. Three-State Model (Frozen)

| State | Question | Source | DSP Authority | Customer Demo |
|-------|----------|--------|---------------|---------------|
| **S1 — Traffic Generated** | Executor가 크래시 없이 완료되었는가? | Executor logs (non-SOT) | No | Debug only |
| **S2 — Traffic Validated** | Event Store가 트래픽을 증명하는가? | `events.db` → ValidationEngine | **Yes — primary** | **Yes — always show** |
| **S3 — Detection Confirmed** | Stellar에서 탐지가 관측되었는가? | Stellar UI / API poll | Separate appendix | **Yes — when available** |

### 1.1 What Constitutes Each State

```
S1 Generated
  → Executor completed; operational belief only
  → NOT sufficient for pass/fail

S2 Validated
  → validation.json decision = success
  → Event Store metrics meet manifest validation_profile.success
  → Path Equality: Execution = Validation = Reporting

S3 Confirmed
  → Stellar Alert OR Analytics incident observed
  → Matches scenario detection_model (name family + entity + timeline)
  → Recorded as DetectionConfirmation (manual or adapter)
  → Does NOT downgrade S2 if absent
```

### 1.2 S3 Sub-States (Future Adapter)

| Sub-state | Meaning | Report label |
|-----------|---------|--------------|
| `confirmed` | Match found in Stellar | Detection ✅ |
| `not_observed` | Poll OK, no match | Detection ⚠ not observed |
| `error` | API/timeout failure | Detection ❌ poll error |
| `not_run` | S2 failed/skipped or adapter disabled | Detection — not polled |

---

## 2. Global S3 Confirmation Criteria

### 2.1 Required for S3 Confirmed (All Scenarios)

| Criterion | Requirement |
|-----------|-------------|
| **S2 prerequisite** | `ValidationResult.decision == success` |
| **Time window** | Stellar event time ∈ `[run.started_at - 2m, run.ended_at + 30m]` |
| **Entity match** | Source IP = DSP runner (or documented egress IP) |
| **Alert OR Analytics** | At least one named detection (see §3–§7) |
| **Evidence link** | Manual note: Stellar alert ID + DSP `run_id` |

### 2.2 Explicit Non-Criteria (Forbidden)

- stdout / grep / legacy PoC counters
- S3 alone without S2
- Synthetic detection score (0–100)
- S3 `not_observed` → S2 downgrade

---

## 3. Per-Scenario S3 Matrix

### 3.1 DNS Tunnel

| Requirement | Detail |
|-------------|--------|
| **Required Alert** | `DNS Tunnel` (or documented alternate: DNS Exfiltration) |
| **Required Analytics** | DNS query volume anomaly; long subdomain / idx-pattern labels |
| **Required Timeline Evidence** | Alert timestamp within 30 min of DSP run end; UDP/53 burst aligned with `dns_tunnel_query_sent` events |
| **Required Entity Evidence** | Source IP = runner; resolver IP = target; FQDN artifact contains `idx-` prefix |

| S2 Metric Gate | S3 Stellar Gate |
|----------------|-----------------|
| `dns_tunnel_query_sent_count ≥ 1` | Alert name ∈ {DNS Tunnel, …} + idx FQDN in evidence |

---

### 3.2 DGA

| Requirement | Detail |
|-------------|--------|
| **Required Alert** | `DGA` or `DNS Anomaly` |
| **Required Analytics** | NXDOMAIN spike; rare domain lookups; dual-phase NX + resolvable pattern |
| **Required Timeline Evidence** | Phase 1 burst then Phase 2 resolvable within run window |
| **Required Entity Evidence** | Domains under `*.xdr.ooo` / `*.live.xdr.ooo`; source IP = runner |

| S2 Metric Gate | S3 Stellar Gate |
|----------------|-----------------|
| `dga_nxdomain_observed_count ≥ 1` AND `dga_resolved_observed_count ≥ 1` | Alert + `xdr.ooo` domain family in evidence |

---

### 3.3 HTTP Follow-up

| Requirement | Detail |
|-------------|--------|
| **Required Alert** | `HTTP Recon` OR `HTTPS Recon` OR `Web Exploit Recon` |
| **Required Analytics** | Multi-path GET sequence; web port access pattern |
| **Required Timeline Evidence** | Requests spread across run duration; ≤20 requests |
| **Required Entity Evidence** | Dest host ∈ DSP `targets`; paths ∈ {`/login`, `/admin`, `/api`, …} |

| S2 Metric Gate | S3 Stellar Gate |
|----------------|-----------------|
| `http_request_sent_count ≥ 1` | Alert family HTTP/HTTPS Recon + matching dest host |

---

### 3.4 SSH Login Failure

| Requirement | Detail |
|-------------|--------|
| **Required Alert** | `Failed SSH Login` (preferred) OR `Brute-force-like Activity` |
| **Required Analytics** | Repeated SSH auth failures; multiple usernames; port 22 |
| **Required Timeline Evidence** | Failure burst duration ≈ DSP `duration_sec` in completed event |
| **Required Entity Evidence** | Dest:22; usernames from DSP `sample_usernames` |

| S2 Metric Gate | S3 Stellar Gate |
|----------------|-----------------|
| `ssh_auth_attempt_count ≥ 1` AND `ssh_auth_failed_count ≥ 1` | SSH failure alert + dest port 22 |

---

### 3.5 SQL Injection

| Requirement | Detail |
|-------------|--------|
| **Required Alert** | `SQL Injection` OR `Web Application Attack` |
| **Required Analytics** | SQLi signature in HTTP query string; suspicious GET parameters |
| **Required Timeline Evidence** | Payload-bearing requests within run window |
| **Required Entity Evidence** | URL contains payload substring (`UNION`, `OR '1'`, `--`); paths `/login`, `/api`, etc. |

| S2 Metric Gate | S3 Stellar Gate |
|----------------|-----------------|
| `sql_payload_generated_count ≥ 1` AND `sql_request_sent_count ≥ 1` | SQLi alert + query string match |

---

## 4. Combined Status Matrix

| S2 | S3 | DSP Exit (Phase 1–3) | Customer Label | Action |
|----|-----|----------------------|----------------|--------|
| success | confirmed | 0 | **High confidence** | Catalog → validated |
| success | not_observed | 0 | Traffic proven; detection unconfirmed | Tune volume/visibility |
| success | error | 0 | Traffic proven; poll failed | Fix Stellar API access |
| failed | any | non-zero | Traffic not proven | Fix DSP execution |
| skipped | any | per policy | Not executed | Fix targets |

---

## 5. Detection Model ID Registry (Adapter Placeholder)

| scenario_id | detection_model_id | vendor |
|-------------|-------------------|--------|
| `dns_tunnel` | `stellar.dns_tunnel` | stellar |
| `dga` | `stellar.dga` | stellar |
| `http_followup` | `stellar.http_recon` | stellar |
| `ssh_failure` | `stellar.ssh_login_failure` | stellar |
| `sql_injection` | `stellar.sql_injection` | stellar |

Informational only — does not affect S2 validation ([SCENARIO_MANIFEST_SPEC.md](./SCENARIO_MANIFEST_SPEC.md) §7).

---

## 6. Related Documents

- [DETECTION_VALIDATION_PLAN.md](./DETECTION_VALIDATION_PLAN.md)
- [DETECTION_CONFIDENCE_MODEL.md](./DETECTION_CONFIDENCE_MODEL.md)
- [LAB_VALIDATION_PROCEDURE.md](./LAB_VALIDATION_PROCEDURE.md)
