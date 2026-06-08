# Detection Scenario Platform — Implementation Risk Register

**문서 버전:** 1.0.0 (Phase 0.6)  
**상태:** Pre-implementation risk capture  
**Review cadence:** Phase gate + major PR

---

## 1. Purpose

코딩 시작 전 알려진 리스크를 문서화하여 **scope drift, 아키텍처 위반, 레거시 오염**을 조기에 차단한다.  
각 리스크는 Likelihood × Impact로 우선순위를 판단하고, Mitigation과 Owner를 명시한다.

**Scale:**

| Likelihood | Definition |
|------------|------------|
| L — Low | Unlikely without explicit mistake |
| M — Medium | Plausible during normal implementation |
| H — High | Common failure mode in similar projects |

| Impact | Definition |
|--------|------------|
| L — Low | Localized fix, no contract change |
| M — Medium | Rework across components |
| H — High | Frozen contract violation or project restart |

---

## 2. Required Risks (Mandatory Entries)

### R-AD-01 — Architecture Drift

| Field | Value |
|-------|-------|
| **Risk** | Implementation introduces patterns outside frozen ARCHITECTURE_SPEC (e.g. dual SOT, bash subprocess validation, vendor logic in scenarios) |
| **Likelihood** | M |
| **Impact** | H |
| **Mitigation** | ARCHITECTURE_COMPLIANCE_CHECKLIST on every PR; Phase gate sign-off; ADR required for any contract change; Cursor Skill from SKILL_SPEC at Phase 1 start |
| **Owner** | DSP lead / reviewer |
| **Trigger signals** | New validation input source; new success declaration outside ValidationEngine |
| **Contingency** | Stop merge; revert; ADR or spec amendment before retry |

---

### R-PE-01 — Path Equality Violation

| Field | Value |
|-------|-------|
| **Risk** | Validation or reporting reads stdout, logs, planned/attempted counters, or test-only bypass paths |
| **Likelihood** | H |
| **Impact** | H |
| **Mitigation** | PATH_EQUALITY_VERIFICATION_SPEC mandatory tests; forbidden pattern grep in CI; PR gate P3/P11 from SKILL_SPEC; code review rejects `validate_from_stdout` |
| **Owner** | Validation/Reporting implementer |
| **Trigger signals** | Test uses non-production ValidationEngine; report row without ValidationResult |
| **Contingency** | Block phase gate until Path Equality suite 100% green |

---

### R-PC-01 — Plugin Contract Violation

| Field | Value |
|-------|-------|
| **Risk** | Plugin Loader or scenarios deviate from manifest schema, PluginStatus lifecycle, or Scenario Interface (e.g. execute returns bool, validate on Scenario) |
| **Likelihood** | M |
| **Impact** | H |
| **Mitigation** | Manifest validator M1–M10; loader tests for REJECTED/CONFLICT/DISABLED; interface freeze tests; dummy scenario as reference plugin |
| **Owner** | Plugin Loader + scenario authors |
| **Trigger signals** | Core edit required to add plugin; manifest field inventing without spec |
| **Contingency** | Reject plugin PR; fix manifest or interface before registration |

---

### R-ES-01 — Event Schema Drift

| Field | Value |
|-------|-------|
| **Risk** | Event rows, status vocabulary, or SQLite columns diverge from EVENT_SCHEMA_FREEZE v1.0.0 |
| **Likelihood** | M |
| **Impact** | H |
| **Mitigation** | EVENT_STORE_ACCEPTANCE_SPEC checklist; append-time validation; forbidden status rejection tests; version field on every row |
| **Owner** | Event Store implementer |
| **Trigger signals** | Column rename without ADR; `success` on event.status |
| **Contingency** | Migration ADR + major version bump; no silent drift |

---

### R-VR-01 — Validation / Report Divergence

| Field | Value |
|-------|-------|
| **Risk** | ValidationEngine and ReportingEngine compute different metrics or decisions for same run |
| **Likelihood** | M |
| **Impact** | H |
| **Mitigation** | Reporting reads ValidationResult only for decisions; metric trace table in PATH_EQUALITY_VERIFICATION_SPEC; regeneration tests |
| **Owner** | Validation + Reporting implementers |
| **Trigger signals** | Report metric not in ValidationResult; manual report row edits |
| **Contingency** | Single source: ValidationResult for table; fix ReportingEngine only |

---

### R-LC-01 — Legacy Code Contamination

| Field | Value |
|-------|-------|
| **Risk** | DSP imports or copies patterns from `stellar_poc*.sh`, TSV SOT, awk summaries, stdout markers, overlap env files |
| **Likelihood** | H |
| **Impact** | H |
| **Mitigation** | WORKSPACE_BOUNDARY read-only legacy; SKILL_SPEC prohibitions P1–P13; no bash PoC structure; code review grep for legacy symbols (`DNS_TUNNEL_ENH`, `stage_result`, TSV paths) |
| **Owner** | All implementers |
| **Trigger signals** | Bash subprocess for validation; TSV compatibility layer |
| **Contingency** | Remove legacy path; rewrite using Event Store aggregate |

---

### R-RB-01 — Repository Boundary Violation

| Field | Value |
|-------|-------|
| **Risk** | Files created or modified outside `detection-scenario-platform/` (deployment, CI, root pyproject, legacy PoC) |
| **Likelihood** | M |
| **Impact** | H |
| **Mitigation** | WORKSPACE_BOUNDARY agent checklist; CI path filter (Phase 1+); git diff scope review on every PR |
| **Owner** | All contributors |
| **Trigger signals** | Changes in `appliance/`, `.github/`, `stellar_poc*.sh` |
| **Contingency** | Revert out-of-scope files immediately; no exceptions without explicit integration phase |

---

## 3. Additional Risks

### R-PE-02 — Aggregate Metric Implementation Bugs

| Field | Value |
|-------|-------|
| **Risk** | `ratio`, `json_extract`, `distinct_artifact` aggregates incorrect → false validation results |
| **Likelihood** | M |
| **Impact** | M |
| **Mitigation** | Unit tests per aggregate type; golden SQL fixtures; dummy manifest uses simple count first |
| **Owner** | Event Store + Validation Engine |

---

### R-SD-01 — Phase 1A Scope Drift (Real Scenarios Early)

| Field | Value |
|-------|-------|
| **Risk** | dns_tunnel or other real scenarios merged under Phase 1A label before skeleton proven |
| **Likelihood** | M |
| **Impact** | M |
| **Mitigation** | PHASE_1_ACCEPTANCE_CRITERIA non-goals; separate Phase 1B scope; PR label review |
| **Owner** | Phase owner |

---

### R-TP-01 — Target Provider Over-Implementation

| Field | Value |
|-------|-------|
| **Risk** | Full TARGET_PROVIDER_SPEC probing built in Phase 1A, delaying skeleton |
| **Likelihood** | M |
| **Impact** | M |
| **Mitigation** | Minimal TargetSet stub for dummy; defer alive_host/dns_resolver probing to Phase 1B |
| **Owner** | Runner / Target implementer |

---

### R-TE-01 — Test Infrastructure Bypass

| Field | Value |
|-------|-------|
| **Risk** | Tests use mock validation that skips Event Store for speed |
| **Likelihood** | M |
| **Impact** | H |
| **Mitigation** | DEFINITION_OF_DONE §2.8; PATH_EQUALITY tests on production classes; `:memory:` SQLite only |
| **Owner** | Test author |

---

### R-DO-01 — Open Questions Deferred Indefinitely

| Field | Value |
|-------|-------|
| **Risk** | Q1–Q7 from Phase 0.5 unresolved at Step 2, causing rework |
| **Likelihood** | L |
| **Impact** | M |
| **Mitigation** | PHASE_1_EXECUTION_PLAN §8 resolution schedule; document in README at step start |
| **Owner** | Phase 1A kickoff owner |

---

### R-SK-01 — Cursor Skill Not Installed

| Field | Value |
|-------|-------|
| **Risk** | Agents implement without SKILL_SPEC constraints |
| **Likelihood** | M |
| **Impact** | M |
| **Mitigation** | Generate Skill from SKILL_SPEC at first Phase 1 commit (Q7); link in README |
| **Owner** | Platform owner |

---

## 4. Risk Matrix Summary

| ID | Risk | L × I | Priority |
|----|------|-------|----------|
| R-PE-01 | Path Equality violation | H × H | **Critical** |
| R-LC-01 | Legacy contamination | H × H | **Critical** |
| R-AD-01 | Architecture drift | M × H | **High** |
| R-PC-01 | Plugin contract violation | M × H | **High** |
| R-ES-01 | Event schema drift | M × H | **High** |
| R-VR-01 | Validation/report divergence | M × H | **High** |
| R-RB-01 | Repository boundary violation | M × H | **High** |
| R-TE-01 | Test bypass | M × H | **High** |
| R-PE-02 | Aggregate bugs | M × M | Medium |
| R-SD-01 | Phase 1A scope drift | M × M | Medium |
| R-TP-01 | Target Provider scope creep | M × M | Medium |
| R-DO-01 | Open questions | L × M | Low |
| R-SK-01 | Skill not installed | M × M | Medium |

---

## 5. Review Log

| Date | Reviewer | Notes |
|------|----------|-------|
| 2026-06-05 | Phase 0.6 | Initial register — pre-implementation |

---

## 6. Related Documents

- [PHASE_1_EXECUTION_PLAN.md](./PHASE_1_EXECUTION_PLAN.md) §6
- [PHASE_1_ACCEPTANCE_CRITERIA.md](./PHASE_1_ACCEPTANCE_CRITERIA.md)
- [PHASE_0_6_IMPLEMENTATION_READINESS_REVIEW.md](./PHASE_0_6_IMPLEMENTATION_READINESS_REVIEW.md)
- [SKILL_SPEC.md](./SKILL_SPEC.md) §3
