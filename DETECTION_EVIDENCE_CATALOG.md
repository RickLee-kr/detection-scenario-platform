# Detection Evidence Catalog — Phase 6.5

**문서 버전:** 1.0.0  
**상태:** Documentation only  
**목적:** 시나리오별 S2·S3 증거 아티팩트 카탈로그 — lab evidence pack 표준

---

## 1. Evidence Pack Structure

Each lab validation run produces a **Evidence Pack** per `run_id`:

```
<run_id>/
├── dsp/                    # S2 authoritative
│   ├── events.db
│   ├── events.jsonl
│   ├── validation.json
│   ├── report.md
│   ├── report.json
│   └── run.json
├── stellar/                # S3 authoritative
│   ├── alerts_export.json  # or CSV
│   ├── analytics_screenshots/
│   └── entity_timeline.png
└── correlation_notes.md    # run_id ↔ alert_id mapping
```

---

## 2. DNS Tunnel (`dns_tunnel`)

### 2.1 Expected DSP Logs / Artifacts (S2)

| Artifact | Content |
|----------|---------|
| `events.jsonl` | `dns_tunnel_started`, `dns_tunnel_chunk_created`, `dns_tunnel_query_sent`, `dns_tunnel_completed` |
| `validation.json` | `dns_tunnel_query_sent_count`, `dns_tunnel_chunk_created_count` |
| `report.md` | § DNS Tunnel Details — targets, sample FQDNs, duration |
| Key metrics | `dns_tunnel_query_sent_count ≥ 1` |

### 2.2 Expected Stellar Alerts (S3)

| Alert name (primary) | Alternates |
|---------------------|------------|
| DNS Tunnel | DNS Exfiltration, Anomalous DNS Query |

### 2.3 Expected Stellar Analytics

- DNS query volume spike
- Long subdomain / high entropy labels
- `idx-######-` pattern in query names

### 2.4 Expected Screenshots

1. Stellar Alert detail — DNS Tunnel with FQDN excerpt
2. Analytics → DNS — source IP query timeline
3. DSP `report.md` primary table (S2 success)

### 2.5 Expected Report Artifacts

| File | Required for customer pack |
|------|---------------------------|
| `validation.json` | Yes |
| `report.md` | Yes |
| Stellar alert screenshot | Yes |
| `events.jsonl` (excerpt) | Optional |

---

## 3. DGA (`dga`)

### 3.1 Expected DSP Logs / Artifacts (S2)

| Artifact | Content |
|----------|---------|
| `events.jsonl` | `dga_started`, `dga_domain_generated`, `dga_nxdomain_observed`, `dga_resolved_observed`, `dga_completed` |
| `validation.json` | `dga_nxdomain_observed_count`, `dga_resolved_observed_count`, `dga_domain_generated_count` |
| `report.md` | § DGA Details — NXDOMAIN/resolvable counts, base domain |
| Key evidence | `base_domain=xdr.ooo` in completed event |

### 3.2 Expected Stellar Alerts (S3)

| Alert name (primary) | Alternates |
|---------------------|------------|
| DGA | DNS Anomaly, Algorithmically Generated Domain |

### 3.3 Expected Stellar Analytics

- NXDOMAIN ratio anomaly
- Rare/new domain lookups
- `*.xdr.ooo` / `*.live.xdr.ooo` domain family

### 3.4 Expected Screenshots

1. DGA alert with domain examples
2. DNS analytics NXDOMAIN timeline
3. DSP metrics showing phase1 + phase2 counts

### 3.5 Expected Report Artifacts

| File | Required |
|------|----------|
| `validation.json` | Yes |
| `report.md` | Yes |
| Stellar DGA alert screenshot | Yes |
| Domain list excerpt from `events.jsonl` | Recommended |

---

## 4. HTTP Follow-up (`http_followup`)

### 4.1 Expected DSP Logs / Artifacts (S2)

| Artifact | Content |
|----------|---------|
| `events.jsonl` | `http_followup_started`, `http_request_sent`, `http_response_received` / `http_request_error`, `http_followup_completed` |
| `validation.json` | `http_request_sent_count`, `http_response_received_count` |
| `report.md` | § HTTP Follow-up Details — sample URLs, ports |
| Key URLs | `https://<host>/login`, `/admin`, `/api`, … |

### 4.2 Expected Stellar Alerts (S3)

| Alert name (primary) | Alternates |
|---------------------|------------|
| HTTP Recon | HTTPS Recon, Web Exploit Recon |

### 4.3 Expected Stellar Analytics

- Sequential GET to multiple paths
- Multi-port web access (443, 80, 8080)
- Destination = lab web host

### 4.4 Expected Screenshots

1. HTTP/HTTPS Recon alert
2. Web analytics — URL path list
3. DSP report sample URLs section

### 4.5 Expected Report Artifacts

| File | Required |
|------|----------|
| `validation.json` | Yes |
| `report.md` with sample URLs | Yes |
| Stellar web recon alert | Yes |
| Optional WAF log | If WAF in path |

---

## 5. SSH Login Failure (`ssh_failure`)

### 5.1 Expected DSP Logs / Artifacts (S2)

| Artifact | Content |
|----------|---------|
| `events.jsonl` | `ssh_failure_started`, `ssh_auth_attempt`, `ssh_auth_failed`, `ssh_failure_completed` |
| `validation.json` | `ssh_auth_attempt_count`, `ssh_auth_failed_count` |
| `report.md` | § SSH Login Failure Details — sample usernames, failure count |
| Key evidence | Usernames: admin, root, test, ubuntu, user |

### 5.2 Expected Stellar Alerts (S3)

| Alert name (primary) | Alternates |
|---------------------|------------|
| Failed SSH Login | Brute-force-like Activity, Multiple SSH Authentication Failures |

### 5.3 Expected Stellar Analytics

- SSH port 22 connection burst
- Multiple failed authentication attempts
- No successful SSH session

### 5.4 Expected Screenshots

1. Failed SSH Login alert
2. Identity/Network analytics — SSH failure timeline
3. DSP report — attempt/failure counts

### 5.5 Expected Report Artifacts

| File | Required |
|------|----------|
| `validation.json` | Yes |
| `report.md` | Yes |
| Stellar SSH alert screenshot | Yes |
| Target auth.log excerpt | Optional (out-of-band) |

---

## 6. SQL Injection (`sql_injection`)

### 6.1 Expected DSP Logs / Artifacts (S2)

| Artifact | Content |
|----------|---------|
| `events.jsonl` | `sql_injection_started`, `sql_payload_generated`, `sql_request_sent`, `sql_response_received` / `sql_request_error`, `sql_injection_completed` |
| `validation.json` | `sql_payload_generated_count`, `sql_request_sent_count` |
| `report.md` | § SQL Injection Details — sample payloads, sample URLs |
| Key payloads | `id=1' OR '1'='1`, `UNION SELECT`, `admin'--`, etc. |

### 6.2 Expected Stellar Alerts (S3)

| Alert name (primary) | Alternates |
|---------------------|------------|
| SQL Injection | Web Application Attack, SQLi Attempt |

### 6.3 Expected Stellar Analytics

- HTTP GET with SQL metacharacters in query string
- Web attack / exploit signature match
- Paths `/login`, `/admin`, `/api`, `/search`

### 6.4 Expected Screenshots

1. SQL Injection alert with query string visible
2. HTTP analytics — suspicious parameter detail
3. DSP report — sample payloads section

### 6.5 Expected Report Artifacts

| File | Required |
|------|----------|
| `validation.json` | Yes |
| `report.md` with sample payloads | Yes |
| Stellar SQLi alert screenshot | Yes |
| WAF block log | Optional |

---

## 7. Master Evidence Checklist (Per Run)

| # | Item | S2 | S3 |
|---|------|----|----|
| 1 | `run.json` archived | ✓ | |
| 2 | `validation.json` decision=success | ✓ | |
| 3 | `report.md` generated | ✓ | |
| 4 | `events.jsonl` exported | ✓ | |
| 5 | Stellar alert ID recorded | | ✓ |
| 6 | Stellar alert screenshot | | ✓ |
| 7 | Analytics screenshot | | ✓ |
| 8 | `correlation_notes.md` completed | | ✓ |
| 9 | Entity IP match documented | | ✓ |
| 10 | Timeline match documented | | ✓ |

---

## 8. Evidence Retention

| Policy | Value |
|--------|-------|
| Retention | Minimum 90 days for customer validation packs |
| PII | No real credentials in evidence — DSP uses dummy payloads only |
| Sharing | Evidence pack = S2 DSP artifacts + S3 Stellar screenshots; no secrets |

---

## 9. Related Documents

- [LAB_VALIDATION_PROCEDURE.md](./LAB_VALIDATION_PROCEDURE.md)
- [DETECTION_VALIDATION_PLAN.md](./DETECTION_VALIDATION_PLAN.md)
- [S3_CONFIRMATION_MATRIX.md](./S3_CONFIRMATION_MATRIX.md)
