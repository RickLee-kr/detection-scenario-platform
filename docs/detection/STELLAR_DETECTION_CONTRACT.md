# Stellar Detection Contract

**Phase:** 10 — Stellar Detection Contract Layer  
**Status:** Contract definition (no live API)  
**Vendor:** Stellar Cyber  
**Configuration:** `dsp/detection/providers/stellar/contracts/scenario_contracts.yaml`

---

## 1. Purpose

This document defines how each DSP scenario maps to expected Stellar detection artifacts. Contracts are **category- and evidence-based**, not alert-name-based. Alert display names may change between Stellar releases; correlation relies on entity, time, and analytics dimensions defined in Phase 10.

---

## 2. Contract Model

Each scenario contract specifies:

| Field | Description |
|-------|-------------|
| Scenario ID | DSP plugin identifier (`manifest.yaml` `id`) |
| Detection Category | Stellar detection family (not a single alert title) |
| Detection Model ID | Stable internal reference (`stellar.<scenario>`) |
| Evidence Sources | Required and optional vendor evidence types |
| Entity Types | Expected Stellar entity classifications |
| Analytics Types | Expected analytic identifiers |
| Timeline Artifacts | Optional chronological events |
| Confidence | Expected S3 confirmation confidence when evidence aligns |

---

## 3. Scenario Contracts

### 3.1 `dns_tunnel`

| Attribute | Value |
|-----------|-------|
| **Scenario ID** | `dns_tunnel` |
| **Detection Category** | DNS Tunnel |
| **Detection Model ID** | `stellar.dns_tunnel` |
| **Evidence Sources (required)** | Alert, Analytics, Entity |
| **Evidence Sources (optional)** | Timeline |
| **Entity Types** | `ip`, `host`, `domain` |
| **Analytics Types** | `dns_query_volume_anomaly`, `long_subdomain_pattern` |
| **Timeline Artifacts** | DNS query bursts, subdomain length anomalies |
| **Confidence** | HIGH |

**Expected behavior:** Stellar should surface DNS tunnel or exfiltration alerts correlated with high-volume UDP/53 queries containing `idx-{seq}-{base32}` subdomain patterns from the scenario source IP.

---

### 3.2 `dga`

| Attribute | Value |
|-----------|-------|
| **Scenario ID** | `dga` |
| **Detection Category** | DGA |
| **Detection Model ID** | `stellar.dga` |
| **Evidence Sources (required)** | Alert, Analytics |
| **Evidence Sources (optional)** | Entity, Timeline |
| **Entity Types** | `ip`, `domain` |
| **Analytics Types** | `nxdomain_burst`, `dga_domain_entropy` |
| **Timeline Artifacts** | NXDOMAIN response clusters, entropy spikes |
| **Confidence** | HIGH |

**Expected behavior:** Stellar should detect algorithmically generated domain lookups with elevated NXDOMAIN rates from a single source IP within the search window.

---

### 3.3 `http_followup`

| Attribute | Value |
|-----------|-------|
| **Scenario ID** | `http_followup` |
| **Detection Category** | HTTP Reconnaissance |
| **Detection Model ID** | `stellar.http_recon` |
| **Evidence Sources (required)** | Alert, Analytics |
| **Evidence Sources (optional)** | Entity, Timeline |
| **Entity Types** | `ip`, `host`, `url` |
| **Analytics Types** | `http_path_enumeration` |
| **Timeline Artifacts** | Sequential HTTP GET/HEAD to common paths |
| **Confidence** | HIGH |

**Expected behavior:** Stellar should identify path enumeration or suspicious HTTP activity between the scenario source and destination IPs over HTTP/HTTPS.

---

### 3.4 `ssh_failure`

| Attribute | Value |
|-----------|-------|
| **Scenario ID** | `ssh_failure` |
| **Detection Category** | SSH Login Failure |
| **Detection Model ID** | `stellar.ssh_login_failure` |
| **Evidence Sources (required)** | Alert, Analytics, Entity |
| **Evidence Sources (optional)** | Timeline |
| **Entity Types** | `ip`, `host`, `user` |
| **Analytics Types** | `ssh_auth_failure_burst` |
| **Timeline Artifacts** | Repeated auth failure events on port 22 |
| **Confidence** | HIGH |

**Expected behavior:** Stellar should detect brute-force or repeated SSH authentication failures from source IP to destination IP, optionally scoped by target username.

---

### 3.5 `sql_injection`

| Attribute | Value |
|-----------|-------|
| **Scenario ID** | `sql_injection` |
| **Detection Category** | SQL Injection |
| **Detection Model ID** | `stellar.sql_injection` |
| **Evidence Sources (required)** | Alert, Analytics |
| **Evidence Sources (optional)** | Entity, Timeline |
| **Entity Types** | `ip`, `host`, `url` |
| **Analytics Types** | `sqli_payload_detected` |
| **Timeline Artifacts** | HTTP requests containing SQLi payload signatures |
| **Confidence** | HIGH |

**Expected behavior:** Stellar should surface web attack or SQLi alerts/analytics tied to HTTP requests from the scenario source to the web target.

---

## 4. Non-Goals (Phase 10)

- No live Stellar API calls
- No alert title string matching as primary correlation signal
- No changes to Event Store, Validation Engine, Reporting Engine, or S2 behavior
- No vendor-specific query optimization (Phase 11)

---

## 5. Related Artifacts

| Document / File | Role |
|-----------------|------|
| `scenario_contracts.yaml` | Machine-readable contract registry |
| `STELLAR_QUERY_MAPPING.md` | Search dimension strategy per scenario |
| `STELLAR_EVIDENCE_MODEL.md` | Vendor → DSP evidence normalization |
| `STELLAR_CORRELATION_RULES.md` | S3 scoring and status thresholds |
| `scenario_mapping.yaml` | Legacy alert family hints (Phase 7–9) |

---

## 6. Version History

| Version | Phase | Notes |
|---------|-------|-------|
| 1.0.0 | 10 | Initial contract layer for five production scenarios |
