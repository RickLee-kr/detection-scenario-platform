# Detection Scenario Platform (DSP)

**Release 1.0.0** — Core platform, local + webshell execution providers, evidence export, manual verification templates, E2E harness.

| Release docs | |
|--------------|--|
| [RELEASE_1_0_SUMMARY.md](./RELEASE_1_0_SUMMARY.md) | Scope, flows, E2E command, non-goals |
| [RELEASE_1_0_LAB_GUIDE.md](./RELEASE_1_0_LAB_GUIDE.md) | Manual lab verification procedure |

이 디렉터리는 workspace의 **XDR Lab Deployment Automation** 및 레거시 Bash PoC와 **분리**된 DSP 프로젝트이다.

---

## Repository Boundary

| 구분 | 경로 | Phase 0 조작 |
|------|------|--------------|
| **DSP (본 프로젝트)** | `detection-scenario-platform/` | 생성·수정 허용 (문서만) |
| 레거시 Bash PoC | `stellar_poc*.sh`, `stellar_*_client.py` | **읽기만** |
| XDR Lab Deployment Automation | `appliance/`, `bootstrap/`, `installer/`, `scripts/`, `config/`, `docs/specs/`, … | **읽기만, 수정 금지** |

자세한 규칙: [WORKSPACE_BOUNDARY.md](./WORKSPACE_BOUNDARY.md)

---

## 문서 목록 (Canonical)

| 문서 | 설명 |
|------|------|
| [PROJECT_CHARTER.md](./PROJECT_CHARTER.md) | 프로젝트 헌장, 목적·범위·설계 원칙 |
| [ARCHITECTURE_SPEC.md](./ARCHITECTURE_SPEC.md) | 컴포넌트·데이터 흐름·Detection Model 분리 (v0.2) |
| [SCENARIO_FRAMEWORK_SPEC.md](./SCENARIO_FRAMEWORK_SPEC.md) | 시나리오 플러그인 인터페이스 |
| [EVENT_STORE_SPEC.md](./EVENT_STORE_SPEC.md) | Event Store SOT 설계 |
| [SKILL_SPEC.md](./SKILL_SPEC.md) | Cursor 구현 규칙·Runtime Path Equality (v0.2) |
| [DETECTION_CATALOG.md](./DETECTION_CATALOG.md) | Scenario ↔ Vendor ↔ Detection 매핑 |
| [WORKSPACE_BOUNDARY.md](./WORKSPACE_BOUNDARY.md) | Workspace·Canonical Source 규칙 |
| [PHASE_0_1_ARCHITECTURE_REVIEW.md](./PHASE_0_1_ARCHITECTURE_REVIEW.md) | Phase 0.1 리뷰 리포트 |
| [PHASE_0_5_ARCHITECTURE_FREEZE_REVIEW.md](./PHASE_0_5_ARCHITECTURE_FREEZE_REVIEW.md) | Phase 0.5 동결 리뷰 |
| **Frozen contracts (0.5)** | |
| [SCENARIO_MANIFEST_SPEC.md](./SCENARIO_MANIFEST_SPEC.md) | manifest.yaml v1.0.0 |
| [PLUGIN_DISCOVERY_SPEC.md](./PLUGIN_DISCOVERY_SPEC.md) | Plugin discover/load/register |
| [EVENT_SCHEMA_FREEZE.md](./EVENT_SCHEMA_FREEZE.md) | Entity model v1.0.0 |
| [SCENARIO_INTERFACE_FREEZE.md](./SCENARIO_INTERFACE_FREEZE.md) | Scenario protocol v1.0.0 |
| [TARGET_PROVIDER_SPEC.md](./TARGET_PROVIDER_SPEC.md) | Target capability model |
| [PROTOCOL_LIBRARY_SPEC.md](./PROTOCOL_LIBRARY_SPEC.md) | dns/http/ssh shared lib |
| [DETECTION_CONFIDENCE_MODEL.md](./DETECTION_CONFIDENCE_MODEL.md) | S1/S2/S3 states |
| [docs/adr/](./docs/adr/) | Architecture Decision Records (0001–0005) |
| **Phase 0.6 — Implementation readiness** | |
| [PHASE_1_ACCEPTANCE_CRITERIA.md](./PHASE_1_ACCEPTANCE_CRITERIA.md) | Phase 1A exit criteria |
| [DEFINITION_OF_DONE.md](./DEFINITION_OF_DONE.md) | DSP-wide DoD |
| [ARCHITECTURE_COMPLIANCE_CHECKLIST.md](./ARCHITECTURE_COMPLIANCE_CHECKLIST.md) | Review checklist |
| [PATH_EQUALITY_VERIFICATION_SPEC.md](./PATH_EQUALITY_VERIFICATION_SPEC.md) | Path equality verification |
| [EVENT_STORE_ACCEPTANCE_SPEC.md](./EVENT_STORE_ACCEPTANCE_SPEC.md) | Event Store acceptance |
| [PHASE_1_EXECUTION_PLAN.md](./PHASE_1_EXECUTION_PLAN.md) | Phase 1A implementation sequence |
| [IMPLEMENTATION_RISK_REGISTER.md](./IMPLEMENTATION_RISK_REGISTER.md) | Pre-implementation risks |
| [PHASE_0_6_IMPLEMENTATION_READINESS_REVIEW.md](./PHASE_0_6_IMPLEMENTATION_READINESS_REVIEW.md) | Phase 0.6 readiness review |

> `docs/detection-scenario-platform/` (workspace 루트)는 **Historical Draft** — 수정하지 않음. 본 디렉터리가 SOT.

---

## 상태

- **Release 1.0.0:** Core platform, execution providers, evidence export, manual verification, E2E harness
- **Local execution:** `dsp run` via `LocalExecutionProvider`
- **Webshell execution:** API composition (`WebshellExecutionProvider` + `RemoteEventCollector`)
- **통합:** Deployment automation 연동 미착수

---

## Phase 1A — Core Platform Skeleton

### Package Layout

```
detection-scenario-platform/
├── pyproject.toml          # Python 3.11+, hatchling, dsp CLI entry
├── dsp/
│   ├── event_store/        # SQLite SOT (append-only)
│   ├── runner/             # CLI + run lifecycle
│   ├── plugins/            # discover → validate → register
│   ├── engine/             # Scenario interface + orchestrator
│   ├── validation/         # manifest-driven ValidationEngine
│   └── reporting/          # ValidationResult-based reports
├── scenarios/
│   └── dummy/              # Phase 1A architecture verification
└── tests/
```

### Quick Start

```bash
cd detection-scenario-platform
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# E2E dry-run (no network)
dsp run --scenarios dummy --dry-run

# List plugins
dsp plugins list

# Run tests
pytest

# Release 1.0 E2E harness
pytest tests/e2e -v
```

### Run Artifacts

기본 run 디렉터리: `~/.dsp/runs/<run_id>/` (환경변수 `DSP_RUNS_DIR`로 override 가능)

| Artifact | Description |
|----------|-------------|
| `events.db` | SQLite Event Store (SOT) |
| `run.json` | Run metadata |
| `manifest.snapshot.json` | Resolved manifest per scenario |
| `validation.json` | ValidationResult[] |
| `report.md` | Human-readable report |
| `report.json` | Machine-readable bundle |
| `events.jsonl` | Optional export |

### Open Questions (Phase 0.5 Q1–Q7) — Resolved

| ID | Decision |
|----|----------|
| Q1 | Python ≥3.11 (`pyproject.toml`) |
| Q2 | ratio metric: numerator/denominator via count aggregate |
| Q3 | Package name: `dsp` |
| Q4 | Run directory: `~/.dsp/runs/<run_id>/` |
| Q5 | Per-run `events.db` |
| Q6 | Build backend: hatchling |
| Q7 | Cursor Skill install: deferred post-M4 |

### Path Equality Verification

```bash
pytest tests/validation/test_path_equality.py -v
```

Execution → Event Store → ValidationEngine → ReportingEngine 단일 경로만 사용. stdout/grep/planned counter 경로 없음.

---

## Phase 1B — DNS Protocol Foundation

### DNS Protocol Layout

```
dsp/protocols/
├── base.py                 # ProtocolError hierarchy
├── types.py                # DnsQuery, DnsQueryResult
└── dns/
    ├── client.py           # encode_qname, build_query, DnsClient (mock/dry-run)
    ├── events.py           # DNS event definitions + Store mapping
    ├── validation.py       # dns_validation_profile() template
    └── reporting.py        # dns_report_profile() + report section builder
```

### DNS Events (Event Store)

| Event | Status | Description |
|-------|--------|-------------|
| `dns_query_created` | info | Query object created |
| `dns_query_sent` | sent | Query dispatched (mock) |
| `dns_response_received` | response / nxdomain | Response received |
| `dns_timeout` | timeout | Query timed out |
| `dns_error` | error | Protocol error |

### DNS Dummy Scenario

```bash
dsp run --scenarios dns_dummy --dry-run
```

- **NOT** DNS Tunnel — mock protocol only, no UDP packets
- Uses `DnsClient` + `build_dns_events()` → Event Store → generic ValidationEngine

### DNS Tests

```bash
pytest tests/protocols/dns/ tests/scenarios/test_dns_dummy_e2e.py tests/validation/test_dns_path_equality.py -v
```
