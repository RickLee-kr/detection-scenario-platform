# Detection Gap Reassessment — Phase 6.5 (Post-MVP)

**문서 버전:** 1.0.0  
**상태:** Documentation only  
**기준:** MVP 5/5 완료 (DNS Tunnel, DGA, HTTP Follow-up, SSH Failure, SQL Injection)  
**변경점:** SQL Injection 구현 완료; S3 검증 전략 정의; 우선순위 재평가

---

## 1. MVP Completion Status

| Catalog MVP | Implemented | S2 (DSP) | S3 (Stellar) |
|-------------|-------------|----------|--------------|
| dns_tunnel | ✅ | ✅ | ❌ pending lab |
| dga | ✅ | ✅ | ❌ pending lab |
| http_followup | ✅ | ✅ | ❌ pending lab |
| ssh_failure | ✅ | ✅ | ❌ pending lab |
| sql_injection | ✅ | ✅ | ❌ pending lab |

**Primary gap shifted:** Implementation → **S3 proof + Detection Adapter + Identity/Recon expansion**

---

## 2. Reassessed Priority Ranking

### 2.1 Summary Table

| Rank | Item | Priority | Stellar Value | Effort | Customer Visibility |
|------|------|----------|---------------|--------|---------------------|
| 1 | **Detection Adapter Layer** | **HIGH** | Critical — enables S3 | Medium–High | **Highest** — closes traffic↔detection loop |
| 2 | **Port Sweep** | **HIGH** | High — Internal Port Scan | Low–Medium | High — demo recon story |
| 3 | **SMB Login Failure** | **HIGH** | High — Windows Identity | Medium | High — enterprise Identity |
| 4 | **LDAP Enumeration** | **MEDIUM** | Medium — AD Discovery | Medium–High | Medium — AD lab required |
| 5 | **Kerberos Failure** | **MEDIUM** | Medium — Kerberos Activity | High | Medium — niche AD demo |

### 2.2 Rationale Changes from Phase 5.5

| Item | Phase 5.5 | Phase 6.5 | Reason |
|------|-----------|-----------|--------|
| SQL Injection | HIGH (implement) | **Done** | MVP complete |
| Detection Adapter | Phase 10 | **Elevated to #1** | S3 undefined without it; customer validation blocked |
| Port Sweep | HIGH | **HIGH (#2)** | HTTP Recon S3 tuning may need recon context; quick win |
| SMB Login Failure | HIGH | **HIGH (#3)** | Identity axis still single-protocol (SSH only) |
| LDAP / Kerberos | MEDIUM | **MEDIUM** | AD lab dependency; after SMB |

---

## 3. Detailed Reassessment

### 3.1 Detection Adapter Layer — **HIGH**

| Dimension | Assessment |
|-----------|------------|
| **Expected Stellar value** | **Critical** — converts S2 proof into customer-trusted S3 confirmation |
| **Implementation effort** | Medium–High — Stellar API client, poll templates, `DetectionConfirmation` entity, report appendix |
| **Customer visibility** | **Highest** — "DSP validated detection" narrative requires automated Stellar poll |
| **Dependency** | Manual lab procedure ([LAB_VALIDATION_PROCEDURE.md](./LAB_VALIDATION_PROCEDURE.md)) first; adapter codifies winners |
| **Recommendation** | **Phase 7 (platform)** — parallel with first new scenario |

**Without Adapter:** DSP is traffic validation platform only — not yet detection validation platform.

---

### 3.2 Port Sweep — **HIGH**

| Dimension | Assessment |
|-----------|------------|
| **Expected Stellar value** | **High** — Internal Port Scan / Service Discovery (legacy PoC validated stage family) |
| **Implementation effort** | **Low–Medium** — `dsp/protocols/tcp/`; atomic scenario |
| **Customer visibility** | **High** — visible recon story; complements HTTP Follow-up PARTIAL S3 |
| **S3 note** | May improve HTTP/SSH follow-up hit rate when run as battery prelude |
| **Recommendation** | **Phase 8 (scenario)** — after Adapter MVP |

---

### 3.3 SMB Login Failure — **HIGH**

| Dimension | Assessment |
|-----------|------------|
| **Expected Stellar value** | **High** — SMB Recon / bad auth; Windows Telemetry alignment |
| **Implementation effort** | **Medium** — new `dsp/protocols/smb/` |
| **Customer visibility** | **High** — enterprise customers expect Windows Identity demos |
| **Lab dependency** | `windows_host`, port 445, AD optional |
| **Recommendation** | **Phase 9 (scenario)** |

---

### 3.4 LDAP Enumeration — **MEDIUM**

| Dimension | Assessment |
|-----------|------------|
| **Expected Stellar value** | **Medium** — AD Discovery; overlaps SMB/Windows Telemetry |
| **Implementation effort** | **Medium–High** — LDAP protocol + DC dependency |
| **Customer visibility** | **Medium** — valuable in full AD lab; less universal than port scan |
| **Recommendation** | **Phase 10 (scenario)** — after SMB |

---

### 3.5 Kerberos Failure — **MEDIUM**

| Dimension | Assessment |
|-----------|------------|
| **Expected Stellar value** | **Medium** — Kerberos Activity subset; Defender/QRadar stronger than Stellar NDR |
| **Implementation effort** | **High** — crypto, DC safety, volume caps |
| **Customer visibility** | **Medium** — impressive in AD demo; operationally sensitive |
| **Recommendation** | **Phase 11 (scenario)** — defer until AD lab mature |

---

## 4. What Dropped in Priority

| Item | New priority | Reason |
|------|--------------|--------|
| SQL Injection (implement) | N/A — complete | MVP done |
| DNS TXT Exfil | LOW–MEDIUM | DNS Tunnel S3 should be proven first |
| Internal Recon (composite) | MEDIUM (deferred) | Needs Port Sweep + targets |
| Webshell / Beaconing | LOW | High complexity; out of customer MVP |

---

## 5. Recommended Implementation Sequence (Post-MVP)

| Phase | Deliverable | Type |
|-------|-------------|------|
| **6.5** | S3 validation docs (this set) | Documentation ✅ |
| **7** | Detection Adapter (Stellar MVP) + manual lab S3 battery | Platform |
| **8** | Port Sweep | Scenario |
| **9** | SMB Login Failure | Scenario |
| **10** | LDAP Enumeration | Scenario |
| **11** | Kerberos Failure | Scenario |

---

## 6. S3-Driven Scenario Tuning (No Code — Lab Only)

Before new scenarios, tune existing MVP for Stellar S3:

| Scenario | Tuning action |
|----------|---------------|
| DNS Tunnel | Increase `max_chunks`; verify DNS SPAN |
| DGA | Use full `phase1_count=500` |
| HTTP Follow-up | Ensure reachable web target; `max_total=20` |
| SSH Failure | Explicit SSH host; `max_total=30` |
| SQL Injection | Reachable web app; full payload set |

Document results in lab evidence packs — informs Adapter match rules.

---

## 7. Related Documents

- [PHASE_6_5_REVIEW.md](./PHASE_6_5_REVIEW.md)
- [PHASE_ROADMAP.md](./PHASE_ROADMAP.md)
- [DETECTION_GAP_ANALYSIS.md](./DETECTION_GAP_ANALYSIS.md)
- [DETECTION_COVERAGE_REVIEW.md](./DETECTION_COVERAGE_REVIEW.md)
