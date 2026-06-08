# Detection Scenario Platform — Scenario Framework Specification

**문서 버전:** 0.2.0 (Execution Provider Architecture)  
**상태:** Design only — no implementation

---

## 1. Purpose

모든 탐지 시나리오(DNS Tunnel, DGA, HTTP Follow-up, SSH Failure, SQL Injection, …)가 **동일한 인터페이스·lifecycle·등록 방식**을 따르도록 한다.

목표: `scenarios/<new_scenario>/` 폴더 추가만으로 신규 시나리오 등록.

**Execution-agnostic 규칙:** 시나리오는 실행 위치(local / webshell / agent / SSH)를 알 필요 없다. 실행 위치는 [Execution Provider](./EXECUTION_PROVIDER_SPEC.md)가 결정한다 (ADR 0006).

---

## 2. Scenario Interface

### 2.1 Abstract Base Class

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ScenarioSummary:
    scenario_id: str
    metrics: dict[str, int | float | str]
    event_count: int
    notes: list[str]


class Scenario(ABC):
    """All scenarios MUST implement this contract."""

    @classmethod
    @abstractmethod
    def scenario_id(cls) -> str:
        """Canonical ID matching manifest.yaml `id`."""

    @abstractmethod
    def prepare(self, ctx: RunContext, targets: TargetSet) -> None:
        """
        Validate preconditions, resolve config, emit preparatory events.
        MUST NOT perform network I/O that generates detection traffic.
        MAY emit: scenario_prepared, config_resolved events.
        """

    @abstractmethod
    def execute(self, ctx: RunContext, targets: TargetSet) -> None:
        """
        Generate traffic/behavior. Append events to ctx.event_store.
        MUST NOT return success/failure — only record events.
        MUST emit scenario_completed or allow Runner to emit scenario_aborted.
        """

    @abstractmethod
    def summarize(self, ctx: RunContext) -> ScenarioSummary:
        """
        Build human-readable metrics from Event Store for this scenario+run.
        MUST query ctx.event_store — never parse stdout.
        """

    # validate() is NOT on Scenario — Validation Engine owns judgment.
    # Scenario may expose validation_spec() for manifest merge.
```

### 2.2 금지 패턴

| 금지 | 이유 |
|------|------|
| `execute() -> bool` | Executor가 성공 선언 |
| `execute()` 내 `print("SUCCESS")` 판정 | stdout ≠ SOT |
| `prepare()`에서 대량 DNS/HTTP | prepare는 non-traffic |
| Scenario 내부 grep/log parsing | Validation은 Engine 담당 |
| `planned` counter를 validation에 전달 | 레거시 불일치 원인 |
| `if execution_provider == "webshell"` | Execution Provider 책임 |
| Remote bootstrap / SSH session in executor | Execution Provider 책임 |
| Separate validation block per execution mode | Single manifest for all modes |

---

## 3. Lifecycle

### 3.1 State Machine

```
                    ┌─────────────┐
                    │  REGISTERED │  (Plugin Loader)
                    └──────┬──────┘
                           │ run requested
                           ▼
                    ┌─────────────┐
              ┌────►│  PREPARING  │  prepare()
              │     └──────┬──────┘
              │            │ targets missing?
              │            ├──────────► SKIPPED
              │            ▼
              │     ┌─────────────┐
              │     │  EXECUTING  │  execute() → events appended
              │     └──────┬──────┘
              │            │ exception?
              │            ├──────────► ABORTED (scenario_aborted event)
              │            ▼
              │     ┌─────────────┐
              │     │  EXECUTED   │  (no decision yet)
              │     └──────┬──────┘
              │            │
              │            ▼
              │     ┌─────────────┐
              │     │ VALIDATING  │  ValidationEngine (NOT scenario)
              │     └──────┬──────┘
              │            │
              │     ┌──────┴──────┬──────────┐
              │     ▼             ▼          ▼
              │  SUCCESS      PARTIAL     FAILED
              │     │             │          │
              └─────┴─────────────┴──────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │ SUMMARIZING │  summarize() + ReportingEngine
                    └─────────────┘
```

### 3.2 Phase Responsibilities

| Phase | Owner | Event Store Write | Decision |
|-------|-------|-------------------|----------|
| `prepare()` | Scenario | Optional (meta) | No |
| `execute()` | Scenario (via Execution Provider transport) | **Required** (traffic) | No |
| `validate()` | Validation Engine | No | **Yes** |
| `summarize()` | Scenario + Reporter | No | No (metrics only) |

**Note:** Execution Provider는 `execute()` 호출 transport를 제공하지만, protocol logic·event recording은 Scenario가 소유한다. Provider는 validation 판정하지 않는다.

### 3.3 Mandatory Events

모든 시나리오 실행은 최소 다음 이벤트를 포함해야 한다:

| event | status | When |
|-------|--------|------|
| `scenario_started` | `info` | execute() 시작 |
| `scenario_completed` | `info` | execute() 정상 종료 |
| (traffic events) | `sent` / outcomes | execute() 중 |
| `scenario_aborted` | `error` | 예외 시 (Runner 기록 가능) |
| `scenario_skipped` | `info` | targets 없음 |

---

## 4. Plugin Registration

### 4.1 Directory Layout

```
scenarios/
├── dns_tunnel/
│   ├── manifest.yaml
│   ├── scenario.py          # class DnsTunnelScenario(Scenario)
│   └── executor.py          # UDP DNS logic
├── dga/
│   ├── manifest.yaml
│   ├── scenario.py
│   └── executor.py
├── http_followup/
│   ├── manifest.yaml
│   ├── scenario.py
│   └── executor.py
├── ssh_failure/
│   ├── manifest.yaml
│   ├── scenario.py
│   └── executor.py
├── sql_injection/
│   ├── manifest.yaml
│   ├── scenario.py
│   └── executor.py
└── future_scenario/
    ├── manifest.yaml
    └── scenario.py
```

### 4.2 Registration Rules

| Rule | Description |
|------|-------------|
| R1 | `manifest.yaml` 필수 — 없으면 로더 skip + warning |
| R2 | `manifest.id` == 폴더명 == `Scenario.scenario_id()` |
| R3 | 동일 id 중복 등록 시 나중 로드 거부 |
| R4 | `manifest.version` semver — breaking change 시 major bump |
| R5 | Optional deps: `manifest.requires_packages` — import 실패 시 `unavailable` 표시 |

### 4.3 Plugin Loader Algorithm

```
1. Scan scenarios/ for subdirectories
2. For each dir:
   a. Parse manifest.yaml → Manifest object
   b. Validate schema (id, version, validation block)
   c. import scenario.py → find Scenario subclass
   d. Register(id → ScenarioClass, Manifest)
3. Expose registry to Scenario Engine
```

### 4.4 Zero-Core-Change Registration Test

신규 시나리오 `future_scenario` 추가 시 수정 허용 파일:

- `scenarios/future_scenario/**`
- `tests/scenarios/test_future_scenario.py`

수정 **금지** (없이 동작해야 함):

- `dsp/engine/scenario_engine.py`
- `dsp/validation/engine.py`
- `dsp/runner/cli.py`

---

## 5. Metadata Structure

### 5.1 manifest.yaml Full Schema

```yaml
# Required
id: string                    # unique, lowercase, snake_case
version: string               # semver
title: string
description: string

# Classification
category: network | endpoint | web | auth
mitre_techniques: []          # e.g. ["T1071.004", "T1568.002"]
tags: []

# Target requirements
targets:
  requires: []                # dns_resolver | http_host | ssh_host | web_app
  optional: []
  max_hosts: int              # safety cap

# Validation contract (merged with Validation Engine)
validation:
  version: "1"
  metrics: []                 # metric names Scenario must produce
  success: {}                 # metric → {min, max, eq}
  partial: {}                 # optional
  fail_fast: []               # invariant names

# Default execution parameters
defaults: {}                  # scenario-specific, overridable by CLI

# Safety envelope
safety:
  max_events: int
  max_duration_sec: int
  allowed_domains: []
  allowed_ports: []
  forbidden_actions: []       # e.g. ["privilege_escalation", "malware_execute"]

# Executor
executor:
  module: executor            # scenarios.<id>.executor
  entrypoint: run             # function name
  remote_capable: bool        # hint only — provider capability matrix; NOT scenario branch

# Execution (platform — NOT per-scenario branch)
# execution.provider_id resolved by Runner; scenarios remain agnostic

# Reporting hints
reporting:
  sample_events: int          # default 5
  highlight_metrics: []
```

### 5.2 RunConfig Override Precedence

```
CLI flags  >  environment variables  >  manifest.defaults  >  platform defaults
```

---

## 6. Initial Scenario Specifications

### 6.1 dns_tunnel

**레거시 근거:** `stellar_dns_tunnel_file_client.py`

| Field | Value |
|-------|-------|
| Pattern | `strt-{session}`, `idx-{seq:06d}-{b32}`, `end-{session}` |
| Transport | UDP/53 raw DNS A query |
| Response | 기록하되 validation 불필요 |
| Key events | `query_sent`, `query_response`, `query_error` |
| Key metrics | `query_sent`, `idx_pattern_count`, `avg_label_length`, `sendto_success` |

```yaml
validation:
  success:
    query_sent: { min: 1 }
    idx_pattern_ratio: { min: 0.8 }
    avg_label_length: { min: 40 }
```

### 6.2 dga

**레거시 근거:** `stellar_dga_model_client.py`

| Field | Value |
|-------|-------|
| Phase 1 | `random.xdr.ooo` → NXDOMAIN (500) |
| Phase 2 | `random.live.xdr.ooo` → resolvable (30) |
| Key events | `query_sent` + status `nxdomain` / `response` |
| Key metrics | `nxdomain`, `resolvable`, `base_domain` |

```yaml
validation:
  success:
    base_domain: { eq: "xdr.ooo" }
    nxdomain: { min: 300 }
    resolvable: { min: 10 }
```

### 6.3 http_followup

| Field | Value |
|-------|-------|
| Ports (priority) | 443, 8443, 80, 8080, 8000 |
| Paths | `/`, `/login`, `/admin`, `/api`, `/status`, `/health`, `/robots.txt`, `/favicon.ico`, `/index.html`, `/dashboard` |
| Caps | max 2 hosts, 10 URLs/host, ≤20 requests |
| Key events | `http_request_sent`, `http_response` |
| Key metrics | `attempted`, `responses` |

```yaml
validation:
  success:
    attempted: { min: 1 }
    responses: { min: 1 }
```

### 6.4 ssh_failure

| Field | Value |
|-------|-------|
| Pattern | `invaliduser@target`, BatchMode, no password auth |
| Key events | `auth_attempted`, `auth_failed` |
| Key metrics | `auth_attempted` |

```yaml
validation:
  success:
    auth_attempted: { min: 1 }
safety:
  forbidden_actions: [privilege_escalation, valid_credential_use]
```

### 6.5 sql_injection

| Field | Value |
|-------|-------|
| Payloads | `?id=1' OR '1'='1`, `?id=1 UNION SELECT`, etc. |
| Method | GET (primary), POST (optional Phase 2) |
| Key events | `injection_request_sent`, `http_response` |
| Key metrics | `injection_request_sent`, `responses` |

```yaml
validation:
  success:
    injection_request_sent: { min: 1 }
safety:
  forbidden_actions: [data_exfiltration, destructive_sql]
```

---

## 7. Executor Module Pattern

시나리오별 프로토콜 로직은 `executor.py`에 격리:

```python
# scenarios/dns_tunnel/executor.py

def run(ctx: RunContext, targets: TargetSet, config: DnsTunnelConfig) -> None:
    """Called by DnsTunnelScenario.execute(). Appends events only."""
    store = ctx.event_store
    for fqdn in generate_fqdns(config):
        send_udp53_query(targets.dns_resolver, fqdn)
        store.append(Event(
            run_id=ctx.run_id,
            scenario="dns_tunnel",
            event="query_sent",
            target=targets.dns_resolver,
            artifact=fqdn,
            status="sent",
            evidence={"qtype": "A", "session": config.session_id},
        ))
```

Executor는 **순수 함수에 가깝게** — global state, stdout 판정 금지.

**Execution Provider boundary:** `executor.py`는 protocol I/O만 수행한다. Webshell upload, SSH connect, agent dispatch는 executor 밖(Execution Provider)에 둔다.

---

## 8. TargetSet Contract

```python
@dataclass
class TargetSet:
    dns_resolvers: list[str]      # IP, in target_net
    http_hosts: list[HttpTarget]  # host, port, scheme
    ssh_hosts: list[str]
    web_apps: list[HttpTarget]    # SQLi targets

    def has(self, requirement: str) -> bool: ...
```

Scenario `prepare()`에서 `targets.has(manifest.targets.requires)` 검사. 미충족 시 skip.

---

## 9. Dry-Run Mode

```bash
dsp run --scenarios dns_tunnel --dry-run
```

| Behavior | |
|----------|--|
| Network I/O | **금지** |
| Event Store | **기록** (synthetic `query_sent` with `dry_run=true` in evidence) |
| Validation | 동일 threshold 적용 OR `dry_run` 태그로 별도 profile (manifest 설정) |

레거시 `--dry-run-sot` 패턴 계승 — TSV/event 기록으로 validation path 테스트.

---

## 10. Extension Points

### 10.1 Execution Provider Integration (Phase X+)

시나리오는 Execution Provider와 **느슨하게 결합**한다:

```
Runner selects provider → provider.execute_scenario(ctx, scenario, targets)
  → scenario.prepare() / execute() unchanged
  → events in ctx.event_store (direct or synced)
```

신규 provider(webshell, agent, SSH) 추가 시 시나리오 폴더 수정 **불필요**.  
상세: [EXECUTION_PROVIDER_SPEC.md](./EXECUTION_PROVIDER_SPEC.md)

### 10.2 Hooks (Optional, Phase 2+)

```python
class ScenarioHooks(Protocol):
    def before_execute(self, ctx, scenario_id): ...
    def after_execute(self, ctx, scenario_id): ...
```

Detection Adapter가 `after_execute`에서 sensor poll 가능.

### 10.3 Composed Scenarios (Phase 3+)

```yaml
# scenarios/full_recon/manifest.yaml
id: full_recon
type: composite
children:
  - dns_tunnel
  - dga
  - http_followup
order: sequential
```

Composite도 각 child의 Event Store 이벤트를 그대로 사용. 별도 counter 금지.

---

## 11. Anti-Patterns (from Legacy)

| Legacy | Framework 대응 |
|--------|----------------|
| `DNS_TUNNEL_ENH_*` dual path | single `dns_tunnel` scenario |
| `dga_simulator` vs `dga_model_client` | single `dga` with versioned executor |
| `overlap stage env` | sequential execute + events |
| function per scenario in 4000-line .sh | plugin folder |
| `module` string free-form | manifest.id enum |

---

## 12. Verification Checklist (per new scenario)

- [ ] `manifest.yaml` validates against schema
- [ ] `Scenario` subclass implements all abstract methods
- [ ] `execute()` appends events, returns nothing
- [ ] No stdout-based success
- [ ] `summarize()` reads Event Store only
- [ ] `tests/scenarios/test_<id>_validation.py` exists
- [ ] Validation Engine picks up manifest thresholds without code change
- [ ] Safety block enforced (domains, ports, caps)
- [ ] `scenario_started` + `scenario_completed` events present
- [ ] No execution-provider-specific branches in scenario/executor code
- [ ] Same validation thresholds apply regardless of execution mode

---

## 13. Related Documents

- [PROJECT_CHARTER.md](./PROJECT_CHARTER.md)
- [ARCHITECTURE_SPEC.md](./ARCHITECTURE_SPEC.md)
- [EXECUTION_PROVIDER_SPEC.md](./EXECUTION_PROVIDER_SPEC.md)
- [docs/architecture/EXECUTION_MODEL_SPEC.md](./docs/architecture/EXECUTION_MODEL_SPEC.md)
- [docs/adr/0006-execution-provider-architecture.md](./docs/adr/0006-execution-provider-architecture.md)
- [EVENT_STORE_SPEC.md](./EVENT_STORE_SPEC.md)
- [SKILL_SPEC.md](./SKILL_SPEC.md)
