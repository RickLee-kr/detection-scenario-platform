# Phase 0.1 — Architecture Hardening Review Report

**문서 버전:** 1.0.0  
**날짜:** 2026-06-05  
**상태:** Phase 0.1 complete — **no code implemented**

---

## 1. Executive Summary

Phase 0.1은 DSP 마스터 설계를 **3년·30–50 시나리오 확장** 관점에서 강화했다.  
코드·테스트·통합·기존 workspace 수정은 **수행하지 않았다**.  
모든 산출물은 canonical root `detection-scenario-platform/`에만 존재한다.

---

## 2. New Document Inventory

### 2.1 New Files (Phase 0.1)

| File | Purpose |
|------|---------|
| `docs/adr/README.md` | ADR index |
| `docs/adr/0001-python-over-bash.md` | Python 전면 선택 |
| `docs/adr/0002-event-store-as-sot.md` | Event Store SOT |
| `docs/adr/0003-scenario-plugin-architecture.md` | Plugin 구조 |
| `docs/adr/0004-no-stdout-validation.md` | stdout/grep 금지 |
| `docs/adr/0005-sqlite-primary-storage.md` | SQLite 1차 저장소 |
| `DETECTION_CATALOG.md` | Scenario ↔ Detection ↔ Vendor 중앙 catalog |
| `PHASE_0_1_ARCHITECTURE_REVIEW.md` | 본 리뷰 리포트 |

### 2.2 Updated Files (canonical only)

| File | Change |
|------|--------|
| `SKILL_SPEC.md` | v0.2.0 — §4.1 Runtime Path Equality Rule 강화 |
| `WORKSPACE_BOUNDARY.md` | v0.2.0 — §3 Canonical Source Rule |
| `ARCHITECTURE_SPEC.md` | v0.2.0 — §14–16 Scalability, Path Equality, Detection Model |
| `README.md` | (updated below) doc index |

### 2.3 Untouched (per boundary)

- `docs/detection-scenario-platform/` — Historical Draft, **not modified**
- `appliance/`, `bootstrap/`, `installer/`, `scripts/`, `stellar_poc*.sh` — **not modified**
- No Python, test, CI, requirements, docker, terraform, ansible

---

## 3. ADR Summary

| ADR | Decision | Key consequence |
|-----|----------|-----------------|
| **0001** Python over Bash | DSP 전체 Python | Bash dual-path 제거, plugin import |
| **0002** Event Store as SOT | SQLite events = 유일한 traffic truth | validate/report 재현 가능 |
| **0003** Scenario Plugin | `scenarios/<id>/` folder auto-discovery | 50 scenarios without core fork |
| **0004** No stdout validation | Execution = Validation = Reporting | grep/planned/attempted 금지 |
| **0005** SQLite primary | Runtime SOT in `.db`, JSONL export only | SQL aggregate replaces awk |

---

## 4. Detection Catalog Summary

### 4.1 Current (MVP) — 5 Scenarios

| Scenario | Status | P0 Vendor focus | Signal types |
|----------|--------|-----------------|--------------|
| `dns_tunnel` | validated | Stellar | NDR, DNS |
| `dga` | validated | Stellar | NDR, DNS |
| `http_followup` | validated | Stellar | NDR, WAF |
| `ssh_failure` | planned | Stellar, Splunk | NDR, Identity |
| `sql_injection` | planned | Stellar, WAF | WAF, NDR |

### 4.2 Future Candidates — 15+ catalogued

Examples: `smb_login_failure`, `ldap_enumeration`, `dns_txt_exfil`, `webshell_callback`, `rdp_login_failure`, `kerberos_auth_failure`, `port_sweep`, `internal_recon`, …

### 4.3 Retired

`icmp_tunnel`, `dns_visibility_gate`, `entropy_only_dga`

### 4.4 Vendor expansion path

Stellar (now) → Splunk (P1) → Defender / SentinelOne / Elastic / Darktrace / QRadar (P2–P3)  
Via **Detection Adapter layer**, not scenario code forks.

---

## 5. Strengthened Architecture Rules

### 5.1 Runtime Path Equality (SKILL_SPEC §4.1)

```
Execution Path = Validation Path = Reporting Path
```

- Scenario가 기록한 **Event만** Validation·Reporting 입력
- **금지:** test-only validation, report-only counter, synthetic/planned/attempted/stdout counter
- pytest = production `ValidationEngine` + `EventStore`

### 5.2 Canonical Source (WORKSPACE_BOUNDARY §3)

| Path | Role |
|------|------|
| `detection-scenario-platform/` | **Canonical SOT** |
| `docs/detection-scenario-platform/` | Historical Draft — read-only, do not edit |

### 5.3 Scenario ≠ Detection Model (ARCHITECTURE_SPEC §16)

| Layer | Answers |
|-------|---------|
| Scenario | "Did we generate the traffic?" → Event Store |
| Detection Model | "Did the vendor detect it?" → Adapter (optional) |

Example: `dns_tunnel` scenario maps to Stellar DNS Tunnel, Splunk DNS Exfil, Defender DNS Anomaly — **1:N via catalog**.

---

## 6. Architecture Review Checklist

| Area | Phase 0 | Phase 0.1 | 30–50 scenario ready? |
|------|---------|-------------|------------------------|
| **확장성** | Plugin concept | ADR 0003 + §14 scalability table | ✅ manifest-driven |
| **유지보수성** | Spec docs | ADR trail + catalog | ✅ decisions documented |
| **Plugin Architecture** | SCENARIO_FRAMEWORK | ADR 0003 zero-core-change rule | ✅ |
| **Event Store** | SQLite rec | ADR 0005 + MetricDef | ✅ |
| **Validation Engine** | manifest thresholds | Path equality + forbidden counters | ✅ |
| **Reporting Engine** | ValidationResult only | Two-table (traffic + detection) | ✅ |
| **Future Vendor Expansion** | adapter stub | §16 + DETECTION_CATALOG | ✅ |
| **Scenario Isolation** | folder plugin | executor/scenario split | ✅ |
| **Repository Boundary** | WORKSPACE_BOUNDARY | Canonical source rule | ✅ |

### 6.1 Gaps (acceptable for Phase 0.1)

| Gap | Planned phase |
|-----|---------------|
| `manifest.schema.json` formal JSON Schema | Phase 1 |
| `detection-catalog.yaml` machine-readable | Phase 3 |
| Remote webshell executor adapter | Phase 2 |
| Composite scenario spec detail | Phase 3 |
| `dsp/protocols/` shared DNS/HTTP lib | Phase 1 |

---

## 7. Document Tree (Canonical)

```
detection-scenario-platform/
├── README.md
├── WORKSPACE_BOUNDARY.md
├── PROJECT_CHARTER.md
├── ARCHITECTURE_SPEC.md          ← v0.2.0
├── SCENARIO_FRAMEWORK_SPEC.md
├── EVENT_STORE_SPEC.md
├── SKILL_SPEC.md                 ← v0.2.0
├── DETECTION_CATALOG.md          ← NEW
├── PHASE_0_1_ARCHITECTURE_REVIEW.md ← NEW
└── docs/adr/
    ├── README.md
    ├── 0001-python-over-bash.md
    ├── 0002-event-store-as-sot.md
    ├── 0003-scenario-plugin-architecture.md
    ├── 0004-no-stdout-validation.md
    └── 0005-sqlite-primary-storage.md
```

---

## 8. Compliance Statement

| Rule | Compliant |
|------|-----------|
| No Python code | ✅ |
| No test code | ✅ |
| No integration code | ✅ |
| No modification outside `detection-scenario-platform/` | ✅ |
| No modification to `docs/detection-scenario-platform/` historical draft | ✅ |
| No deployment / legacy / CI changes | ✅ |

---

## 9. Recommended Next Step (Phase 1 — not started)

1. `dsp/event_store/` — SQLite per ADR 0005
2. `dsp/validation/engine.py` — manifest-driven per ADR 0002
3. `scenarios/dns_tunnel/` — first plugin per ADR 0003
4. pytest with Path Equality per SKILL_SPEC §4.1
5. Install Cursor Skill from SKILL_SPEC §16

**Phase 1 착수 전 사용자 승인 필요.**

---

## 10. Related Documents

- [README.md](./README.md)
- [WORKSPACE_BOUNDARY.md](./WORKSPACE_BOUNDARY.md)
- [DETECTION_CATALOG.md](./DETECTION_CATALOG.md)
- [docs/adr/README.md](./docs/adr/README.md)
