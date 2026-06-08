# Phase 6.5 Review — Detection Validation Readiness

**문서 버전:** 1.0.0  
**상태:** Final review — documentation only  
**Date:** 2026-06-05  
**Milestone:** DSP MVP complete (5/5 scenarios); S1+S2 complete; S3 strategy defined

---

## 1. Executive Summary

DSP는 **트래픽 생성·증명(S1/S2)** 에서 production-ready MVP 상태에 도달했다.  
**탐지 확인(S3)** 은 아직 Stellar lab에서 체계적으로 수행되지 않았으며, 본 Phase 6.5에서 검증 방법론·증거 카탈로그·lab 절차를 정의했다.

**결론:** DSP는 **내부·기술 고객 검증(S2)** 에 준비됨. **외부 고객 데모(S3)** 는 Stellar manual lab battery + Phase 7 Adapter 이후 full-ready.

---

## 2. Review Questions

### 2.1 Which MVP scenarios are most likely to detect (Stellar)?

| Rank | Scenario | Likelihood | Primary Stellar Model |
|------|----------|------------|----------------------|
| 1 | **DNS Tunnel** | **Highest** | DNS Tunnel — idx-pattern, high DNS volume |
| 2 | **DGA** | **Highest** (at full volume) | DGA / DNS Anomaly — NXDOMAIN + resolvable |
| 3 | **SSH Login Failure** | **High** | Failed SSH Login — repeated :22 failures |
| 4 | **SQL Injection** | **Medium–High** | SQL Injection — signature in query string |
| 5 | **HTTP Follow-up** | **Medium** | HTTP Recon — low volume, tuning sensitive |

**DNS scenarios** are strongest Stellar NDR fits based on legacy PoC mapping and traffic distinctiveness.

---

### 2.2 Which scenarios need tuning?

| Scenario | Tuning need | Action |
|----------|-------------|--------|
| **HTTP Follow-up** | **High** | Reachable web target; full 20 requests; may need abnormal UA in future (out of MVP) |
| **DGA** | **Medium** | Use production `phase1_count=500`, not E2E-minimal counts |
| **DNS Tunnel** | **Medium** | Increase chunk count; confirm DNS visibility path |
| **SSH Failure** | **Medium** | Explicit SSH target IP; 30+ attempts; pubkey-only may map to Failed Login not Brute-force |
| **SQL Injection** | **Medium** | Web target with HTTP logging; WAF in path improves demo |

**None need DSP code changes for initial S3 lab** — parameter and environment tuning only.

---

### 2.3 Which scenarios have the highest customer demo value?

| Rank | Scenario | Demo value | Why |
|------|----------|------------|-----|
| 1 | **DNS Tunnel** | ⭐⭐⭐⭐⭐ | Classic NDR story; visual FQDN evidence; Stellar flagship |
| 2 | **DGA** | ⭐⭐⭐⭐⭐ | Two-phase story; clear DNS analytics |
| 3 | **SQL Injection** | ⭐⭐⭐⭐ | Web attack/WAF narrative; universal customer interest |
| 4 | **SSH Failure** | ⭐⭐⭐⭐ | Identity + lateral precursor story |
| 5 | **HTTP Follow-up** | ⭐⭐⭐ | Supporting recon; less dramatic alone |

**Recommended demo order:** DNS Tunnel → DGA → SQL Injection → SSH Failure → HTTP Follow-up

**Demo narrative:** "DSP generates traffic → Event Store proves execution → Stellar detects → evidence pack links both."

---

### 2.4 What should be implemented next?

| Priority | Phase | Deliverable |
|----------|-------|-------------|
| **1** | 7 | **Detection Adapter Layer** (Stellar) — S3 automation |
| **2** | 7b | **Manual Stellar lab battery** — per LAB_VALIDATION_PROCEDURE.md |
| **3** | 8 | **Port Sweep** — recon atomic; improves demo breadth |
| **4** | 9 | **SMB Login Failure** — Windows Identity |

**Not next:** Kerberos (high effort), Internal Recon composite (needs prerequisites), Splunk adapter (after Stellar S3 baseline).

---

### 2.5 Is DSP ready for customer validation?

| Validation type | Ready? | Condition |
|-----------------|--------|-----------|
| **Technical S2 validation** | **Yes** | 122 pytest pass; Path Equality; Event Store SOT; 5 scenarios ACTIVE |
| **Architecture review** | **Yes** | Frozen specs; MVP complete; no stdout validation |
| **Stellar S3 validation (manual)** | **Ready to start** | Follow LAB_VALIDATION_PROCEDURE.md; evidence packs |
| **Stellar S3 validation (automated)** | **No** | Adapter not implemented |
| **Customer demo (traffic only)** | **Yes** | `dsp run --dry-run` or live with S2 report |
| **Customer demo (detection proof)** | **Partial** | Requires lab S3 battery + screenshots; Adapter recommended |
| **Production deployment** | **No** | Out of scope; no deployment integration |

**Verdict:**

> DSP is **ready for customer technical validation (S2)** and **ready to begin Stellar detection validation (S3 manual)**.  
> DSP is **not yet ready** to claim "validated detections" in customer-facing materials without completed lab evidence packs.

---

## 3. Phase 6.5 Deliverables

| # | Document | Purpose |
|---|----------|---------|
| 1 | [DETECTION_VALIDATION_PLAN.md](./DETECTION_VALIDATION_PLAN.md) | Per-scenario Stellar alert/analytics/entity/evidence |
| 2 | [S3_CONFIRMATION_MATRIX.md](./S3_CONFIRMATION_MATRIX.md) | S1/S2/S3 definitions + per-scenario gates |
| 3 | [LAB_VALIDATION_PROCEDURE.md](./LAB_VALIDATION_PROCEDURE.md) | Repeatable lab playbook |
| 4 | [DETECTION_EVIDENCE_CATALOG.md](./DETECTION_EVIDENCE_CATALOG.md) | Evidence pack artifacts |
| 5 | [DETECTION_GAP_REASSESSMENT.md](./DETECTION_GAP_REASSESSMENT.md) | Post-MVP priority ranking |
| 6 | [PHASE_6_5_REVIEW.md](./PHASE_6_5_REVIEW.md) | This review |

---

## 4. S3 Validation Strategy (Summary)

```
DSP Run (live)
    → S2 validation.json success
    → Wait 15–30 min
    → Stellar Alert + Analytics search
    → Entity + timeline + artifact correlation
    → Evidence pack (DSP + Stellar)
    → S3 confirmed / not_observed recorded
```

**Phase 7 Adapter** automates Stellar poll → `DetectionConfirmation` → report appendix.  
**S2 remains authoritative** for DSP exit code until `--require-detection`.

---

## 5. Evidence Collection Strategy (Summary)

- **S2 pack:** `events.db`, `validation.json`, `report.md`, `events.jsonl` per `run_id`
- **S3 pack:** Stellar alert screenshots, alert IDs, analytics views
- **Correlation:** `correlation_notes.md` linking `run_id` ↔ Stellar alert ID
- **Retention:** 90 days; no real credentials

See [DETECTION_EVIDENCE_CATALOG.md](./DETECTION_EVIDENCE_CATALOG.md).

---

## 6. Updated Scenario Priorities (Post-MVP)

| Priority | Item |
|----------|------|
| **HIGH** | Detection Adapter Layer, Port Sweep, SMB Login Failure |
| **MEDIUM** | LDAP Enumeration, Kerberos Failure |
| **LOW** | Composite Internal Recon, Webshell/Beaconing (defer) |

See [DETECTION_GAP_REASSESSMENT.md](./DETECTION_GAP_REASSESSMENT.md).

---

## 7. Recommended Next Implementation Phase

**Phase 7: Detection Adapter Layer (Stellar MVP)**

Parallel lab activity: Execute MVP battery per [LAB_VALIDATION_PROCEDURE.md](./LAB_VALIDATION_PROCEDURE.md) and collect first S3 evidence packs before Adapter codifies match rules.

---

## 8. Acceptance Criteria — Phase 6.5

| Criterion | Status |
|-----------|--------|
| S3 validation defined per scenario | ✅ |
| S3 confirmation matrix | ✅ |
| Lab procedure documented | ✅ |
| Evidence catalog complete | ✅ |
| Post-MVP gap reassessment | ✅ |
| Final review answers (5 questions) | ✅ |
| No code / adapter / architecture changes | ✅ |
| All docs under `detection-scenario-platform/` only | ✅ |

---

## 9. Related Documents

- [DETECTION_CONFIDENCE_MODEL.md](./DETECTION_CONFIDENCE_MODEL.md)
- [DETECTION_COVERAGE_REVIEW.md](./DETECTION_COVERAGE_REVIEW.md)
- [PHASE_ROADMAP.md](./PHASE_ROADMAP.md)
- [DEFINITION_OF_DONE.md](./DEFINITION_OF_DONE.md)
