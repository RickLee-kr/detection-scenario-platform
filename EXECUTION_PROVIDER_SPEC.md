# Detection Scenario Platform — Execution Provider Specification

**문서 버전:** 1.0.0  
**상태:** Architecture only — no implementation  
**Phase:** Pre-implementation (Execution Provider Framework)

---

## 1. Purpose

Execution Provider는 **트래픽이 어디서 생성되는지**(실행 위치·transport)를 추상화한다. Target Provider가 **대상 endpoint**를 제공하는 것과 대칭적으로, Execution Provider는 **출발 host·process·transport**를 제공한다.

| Abstraction | Question answered |
|-------------|-------------------|
| Target Provider | Where does traffic **go**? |
| Execution Provider | Where does traffic **originate**? |
| Scenario Plugin | What traffic **pattern** is generated? |

상세 execution model: [docs/architecture/EXECUTION_MODEL_SPEC.md](./docs/architecture/EXECUTION_MODEL_SPEC.md)

---

## 2. Design Principles

| ID | Principle |
|----|-----------|
| EP1 | Scenarios remain **execution-agnostic** — no local/remote branches in scenario code |
| EP2 | Event Store on DSP Host remains **authoritative SOT** — remote events sync in, same schema |
| EP3 | Validation Engine **unchanged** — reads Event Store only |
| EP4 | Reporting Engine **unchanged** — optional execution metadata in run header only |
| EP5 | New transport = new provider — **zero scenario modifications** |
| EP6 | `LocalExecutionProvider` is default — Mode A backward compatible |

---

## 3. ExecutionProvider Interface (Conceptual)

```python
# CONCEPTUAL ONLY — documentation, not runtime code

from typing import Protocol
from dataclasses import dataclass


@dataclass
class ExecutionContext:
    """Provider-specific runtime context injected into RunContext."""
    provider_id: str              # e.g. "local", "webshell", "agent", "ssh"
    traffic_origin_host: str      # IP/hostname where packets egress
    transport_metadata: dict      # provider-specific, non-validated


@dataclass
class ExecutionResult:
    """Outcome of provider-managed execution — NOT validation decision."""
    provider_id: str
    events_synced: int
    traffic_origin_host: str
    duration_ms: int
    error: str | None             # provider/transport failure
    notes: list[str]


class ExecutionProvider(Protocol):
    """Decides WHERE scenario traffic is generated."""

    provider_id: str              # canonical registry key

    def describe(self) -> ExecutionProviderDescriptor: ...

    def supports_scenario(self, scenario_id: str, manifest: Manifest) -> bool:
        """
        Capability check — e.g. webshell may not support raw UDP/53 without relay.
        Returns False → Runner skips with execution_provider_unsupported meta event.
        """

    def prepare_execution(
        self,
        ctx: RunContext,
        scenario_id: str,
        targets: TargetSet,
    ) -> ExecutionContext:
        """
        Establish transport — SSH session, webshell bootstrap, agent task channel.
        MAY append meta events: execution_prepared, execution_transport_ready.
        MUST NOT append traffic events (scenario owns traffic events).
        """

    def execute_scenario(
        self,
        ctx: RunContext,
        scenario: Scenario,
        targets: TargetSet,
        exec_ctx: ExecutionContext,
    ) -> ExecutionResult:
        """
        Run scenario lifecycle through provider transport.
        Scenario.prepare() + Scenario.execute() invoked.
        All traffic events MUST land in ctx.event_store (direct or synced).
        Provider MUST NOT return success/failure for validation purposes.
        """

    def teardown_execution(
        self,
        ctx: RunContext,
        exec_ctx: ExecutionContext,
    ) -> None:
        """
        Close sessions, cleanup remote artifacts (best-effort).
        MAY append execution_teardown meta event.
        """
```

### 3.1 Registry

```python
class ExecutionProviderRegistry(Protocol):
    def register(self, provider: ExecutionProvider) -> None: ...
    def get(self, provider_id: str) -> ExecutionProvider: ...
    def list_providers(self) -> list[ExecutionProviderDescriptor]: ...
    def default(self) -> ExecutionProvider: ...  # LocalExecutionProvider
```

Runner resolves provider:

```
CLI --execution-provider  >  RunConfig  >  platform default (local)
```

---

## 4. Provider Descriptors (Conceptual)

```yaml
# Example: ExecutionProviderDescriptor
id: webshell
title: Webshell Remote Execution
execution_mode: remote          # Mode B
traffic_origin: remote_host
transport: http_webshell
phase_introduced: X+1
requires:
  - remote_target_host
  - webshell_url_or_bootstrap_config
capabilities:
  supports_udp: false           # may require DNS relay — see supports_scenario()
  supports_tcp: true
  supports_http_client: true
safety:
  allowed_in_lab_only: true
  requires_explicit_opt_in: true
```

---

## 5. Provider Implementations (Conceptual)

### 5.1 LocalExecutionProvider

| Field | Value |
|-------|-------|
| `provider_id` | `local` |
| Execution Mode | A |
| Traffic origin | DSP Host |
| Transport | In-process Python, local sockets |

**Behavior:**

```
prepare_execution  → ExecutionContext(traffic_origin_host=dsp_host)
execute_scenario   → scenario.prepare(); scenario.execute()  [direct]
teardown_execution → no-op
```

**Status:** Implicit in current Phase 1–5 implementation. Phase X에서 formalize.

**Use cases:** Lab validation, local testing, standalone deployments, CI dry-run.

---

### 5.2 WebshellExecutionProvider

| Field | Value |
|-------|-------|
| `provider_id` | `webshell` |
| Execution Mode | B |
| Traffic origin | Remote compromised host |
| Transport | HTTP(S) webshell invoke |

**Behavior (conceptual):**

```
prepare_execution
  → bootstrap/copy minimal executor stub to remote (legacy pattern isolated here)
  → establish webshell session
  → ExecutionContext(traffic_origin_host=remote_victim_ip)

execute_scenario
  → dispatch scenario executor on remote via webshell
  → remote side generates traffic + buffers events
  → sync_events(remote_buffer → ctx.event_store)  [same Event schema]

teardown_execution
  → optional cleanup of dropped stub (lab policy)
```

**Constraints:**

- UDP/53 raw DNS may require local relay fallback — `supports_scenario("dns_tunnel")` may return False unless relay configured
- Webshell credentials, URL — RunConfig only, never in scenario code
- Event sync failure → `execution_sync_failed` meta event; validation sees traffic events received (partial sync policy in Phase X)

**Use cases:** XDR PoC victim-origin traffic, legacy stellar_poc webshell path replacement.

---

### 5.3 AgentExecutionProvider

| Field | Value |
|-------|-------|
| `provider_id` | `agent` |
| Execution Mode | B |
| Traffic origin | Remote agent endpoint |
| Transport | Agent protocol (Caldera, Sliver, custom agent API) |

**Behavior (conceptual):**

```
prepare_execution
  → resolve agent profile / beacon ID from lab inventory
  → verify agent alive (preflight — meta event only, not validation)
  → ExecutionContext(traffic_origin_host=agent_host)

execute_scenario
  → package scenario executor as agent task OR invoke pre-staged capability
  → agent runs protocol I/O on endpoint
  → agent returns event batch → append to ctx.event_store

teardown_execution
  → cancel pending tasks, release agent lock
```

**Constraints:**

- Agent capability matrix per scenario — registry documents supported pairs
- Agent offline → skip or failed meta; traffic validation = events in store only
- Future: integrate with xdr-lab-appliance Caldera/Sliver docs (design reference only)

**Use cases:** Endpoint detection validation, C2 simulation from agent host.

---

### 5.4 SSHExecutionProvider

| Field | Value |
|-------|-------|
| `provider_id` | `ssh` |
| Execution Mode | B |
| Traffic origin | Remote SSH-accessible host |
| Transport | SSH remote command / SFTP staging |

**Behavior (conceptual):**

```
prepare_execution
  → SSH connect (key-based, lab-only)
  → stage Python executor or invoke system tools per scenario needs
  → ExecutionContext(traffic_origin_host=ssh_target)

execute_scenario
  → remote execute scenario bundle
  → stream/collect events via SSH channel
  → append to ctx.event_store

teardown_execution
  → remove staged files (optional)
  → close SSH session
```

**Constraints:**

- Requires SSH target in lab inventory — distinct from `ssh_failure` scenario target (auth failure traffic vs execution transport)
- Privilege model documented in Safety Envelope
- Rate/volume caps enforced before remote dispatch

**Use cases:** Linux victim traffic origin, jump-host lab topology.

---

## 6. Scenario Engine Integration (Conceptual)

```
Runner.run_scenario(scenario_id):
  provider = registry.get(config.execution_provider_id)
  if not provider.supports_scenario(scenario_id, manifest):
      append execution_provider_unsupported event
      return SKIPPED

  exec_ctx = provider.prepare_execution(ctx, scenario_id, targets)
  try:
      result = provider.execute_scenario(ctx, scenario, targets, exec_ctx)
  finally:
      provider.teardown_execution(ctx, exec_ctx)

  # Validation — unchanged, Event Store only
  ValidationEngine.validate(ctx, scenario_id)
```

Scenario Engine **does not** choose local vs remote — Runner injects provider.

---

## 7. Event Store Bridge (Remote → Local SOT)

Remote providers MUST ensure events conform to [EVENT_STORE_SPEC.md](./EVENT_STORE_SPEC.md).

| Rule | Description |
|------|-------------|
| B1 | Synced events use identical schema — no `remote_event_v2` fork |
| B2 | `run_id` preserved across sync |
| B3 | Optional `evidence.execution_provider` = provider_id (reporting/debug) |
| B4 | Optional `evidence.traffic_origin_host` (reporting/debug) |
| B5 | Validation metrics MUST NOT depend on provider metadata fields |
| B6 | Sync batch append — atomic per scenario execute where possible |

**Fail-fast (provider layer, not validation):**

| Meta event | Meaning |
|------------|---------|
| `execution_sync_failed` | Zero traffic events received from remote |
| `execution_transport_failed` | Could not establish webshell/agent/SSH |
| `execution_provider_unsupported` | Scenario incompatible with provider transport |

Traffic validation still uses manifest thresholds on traffic events. Zero traffic events → `failed` per existing rules.

---

## 8. RunConfig Extensions (Conceptual)

```yaml
execution:
  provider_id: local              # default
  remote:
    target_host: null             # required for Mode B
    webshell_url: null            # webshell provider
    agent_profile: null           # agent provider
    ssh_host: null                # ssh provider
    ssh_user: null
    sync_timeout_sec: 300
```

Precedence:

```
CLI flags  >  environment  >  run yaml  >  platform default (local)
```

---

## 9. Safety Envelope Extensions

| Gate | Owner |
|------|-------|
| CIDR / target_net | Target Provider (unchanged) |
| Remote host in lab inventory | Execution Provider preflight |
| Webshell opt-in flag | Runner `--allow-webshell` (explicit) |
| Agent task volume caps | Execution Provider + manifest safety |
| SSH key / host allowlist | Execution Provider config |

Scenarios inherit caps via manifest `safety` block — provider enforces before dispatch.

---

## 10. Testing Strategy (Architecture)

| Test type | Scope |
|-----------|-------|
| Provider unit | mock transport, event sync |
| Path equality | remote provider (mocked) → Event Store → same validate() as local |
| Scenario unchanged | dns_tunnel validation tests pass with LocalExecutionProvider |
| stdout rejection | remote provider must not bypass Event Store (ADR 0004) |
| Provider matrix | documents supported scenario × provider pairs |

---

## 11. Related Documents

- [EXECUTION_MODEL_SPEC.md](./docs/architecture/EXECUTION_MODEL_SPEC.md)
- [EXECUTION_PROVIDER_DECISION_RECORD.md](./docs/architecture/EXECUTION_PROVIDER_DECISION_RECORD.md)
- [ADR 0006 — Execution Provider Architecture](./docs/adr/0006-execution-provider-architecture.md)
- [TARGET_PROVIDER_SPEC.md](./TARGET_PROVIDER_SPEC.md)
- [ARCHITECTURE_SPEC.md](./ARCHITECTURE_SPEC.md)
- [SCENARIO_FRAMEWORK_SPEC.md](./SCENARIO_FRAMEWORK_SPEC.md)
- [EVENT_STORE_SPEC.md](./EVENT_STORE_SPEC.md)
