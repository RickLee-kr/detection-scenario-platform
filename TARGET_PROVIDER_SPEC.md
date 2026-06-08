# Detection Scenario Platform — Target Provider Specification

**문서 버전:** 1.0.0 (Phase 0.5 — **FROZEN**)  
**상태:** Canonical contract for target selection abstraction

---

## 1. Purpose

Target Provider는 시나리오가 트래픽을 보낼 **대상(endpoint)** 을 lab 범위 내에서 안전하게 제공한다.

| Phase | Scope |
|-------|-------|
| **Current (Phase 1)** | Alive host selection, basic capability resolution |
| **Future** | Role-based hosts: Windows, Linux, Web, DNS, DC, DB |

시나리오는 Target Provider가 반환한 `TargetSet`만 사용 — 자체 IP sweep 금지.

---

## 2. Target Provider Abstraction

```python
# FROZEN — documentation only

class TargetProvider(Protocol):
    def resolve(
        self,
        ctx: RunContext,
        requirements: TargetRequirements,
    ) -> TargetSet: ...

    def describe_capabilities(self) -> list[CapabilityDescriptor]: ...
```

| Component | Owner |
|-----------|-------|
| Target Provider | `dsp/targets/provider.py` |
| Target requirements source | `manifest.supported_targets` |
| CIDR enforcement | Target Provider (hard gate) |
| Scenario | consumes `TargetSet` only |

---

## 3. Capability Model (Frozen)

### 3.1 Capability ID

| ID | Description | Phase |
|----|-------------|-------|
| `alive_host` | Any reachable IP in target_net | 1 |
| `dns_resolver` | Host accepting UDP/53 (or system resolver in net) | 1 |
| `http_host` | HTTP service on allowed ports | 1 |
| `https_host` | HTTPS service on allowed ports | 1 |
| `web_app` | HTTP app suitable for SQLi paths | 2 |
| `ssh_host` | SSH port 22 reachable | 2 |
| `linux_host` | Linux victim (role tag) | 3 |
| `windows_host` | Windows victim (role tag) | 3 |
| `web_server` | Dedicated web tier (role tag) | 3 |
| `dns_server` | DNS service host (role tag) | 3 |
| `domain_controller` | AD DC (role tag) | 4 |
| `database_server` | DB service (role tag) | 4 |

### 3.2 CapabilityDescriptor

```yaml
id: string
title: string
phase_introduced: int
selection_method: probe | inventory | config | hybrid
required_fields: [string]   # e.g. host, port, scheme
```

---

## 4. TargetSet Model (Frozen)

```python
@dataclass
class TargetEndpoint:
    host: str              # IP address — MUST be in target_net
    port: int | None
    scheme: str | None     # http | https | ssh | dns
    role: str | None       # linux_host | windows_host | ...
    metadata: dict         # os_hint, hostname, tags


@dataclass
class TargetSet:
    capabilities: dict[str, list[TargetEndpoint]]  # capability_id → endpoints
    resolver: str | None                             # DNS resolver IP
    target_net: str
    resolved_at: datetime

    def get(self, capability_id: str) -> list[TargetEndpoint]: ...
    def has(self, capability_id: str) -> bool: ...
    def first(self, capability_id: str) -> TargetEndpoint | None: ...
```

**Rules:**

- All `host` values MUST pass CIDR check against `ctx.target_net`
- Empty capability → `has()` false — Scenario may skip via `ScenarioSkipError`
- `max_hosts` from manifest applied per capability

---

## 5. Selection Flow

```
┌──────────────┐
│  Run start   │
└──────┬───────┘
       ▼
┌──────────────┐
│ Load manifest│  supported_targets.requires
│ requirements │
└──────┬───────┘
       ▼
┌──────────────┐
│ CIDR validate│  target_net from RunContext
│ target_net   │  invalid → config_error
└──────┬───────┘
       ▼
┌──────────────┐
│  Discovery   │  Phase 1: alive probe
│  (optional)  │  Phase 3+: inventory file / deployment API (read-only)
└──────┬───────┘
       ▼
┌──────────────┐
│  Capability  │  map hosts → capabilities
│  matching    │
└──────┬───────┘
       ▼
┌──────────────┐
│ Apply filters│  max_hosts, port allowlist, role tags
└──────┬───────┘
       ▼
┌──────────────┐
│  TargetSet   │  passed to Scenario.prepare/execute
└──────────────┘
```

### 5.1 Phase 1 — Alive Host Selection (Current design)

| Step | Action |
|------|--------|
| 1 | Parse `target_net` CIDR |
| 2 | Optional: ICMP/TCP probe key ports (22, 53, 80, 443, 8080) — **preflight only** |
| 3 | Mark alive IPs |
| 4 | Assign capabilities by port response |
| 5 | Cap lists per `max_hosts` |

**Legacy lesson:** Discovery 0 hosts → **skip scenario**, not fake success. Emit no traffic events unless `scenario_skipped`.

### 5.2 Phase 3+ — Role-Based Inventory (Future)

```yaml
# Future: ~/.dsp/inventory.yaml or deployment-provided (read-only file)
hosts:
  - host: 10.10.10.20
    roles: [linux_host, web_server, ssh_host, http_host]
    os: linux
  - host: 10.10.10.30
    roles: [windows_host, rdp_host]
    os: windows
  - host: 10.10.10.10
    roles: [dns_server, dns_resolver]
```

**Integration rule:** Deployment automation provides inventory file path via env `DSP_INVENTORY` — **no import/link to appliance code** (WORKSPACE_BOUNDARY).

---

## 6. Filtering Model (Frozen)

| Filter | Source | Mandatory |
|--------|--------|-----------|
| CIDR membership | `target_net` | yes |
| `max_hosts` | manifest | yes |
| `safety.allowed_ports` | manifest | if declared |
| `enabled: false` hosts | inventory `disabled: true` | Phase 3+ |
| Operator exclude list | CLI `--exclude-hosts` | optional |

Filter order: CIDR → exclude → capability match → max_hosts cap.

---

## 7. Scenario Integration

```python
# In Scenario.prepare()
if not targets.has("dns_resolver"):
    raise ScenarioSkipError("no_dns_resolver")
```

| manifest.requires | Empty TargetSet behavior |
|-------------------|--------------------------|
| all required met | execute proceeds |
| any required empty | `ScenarioSkipError` → `scenario_skipped` |
| optional empty | execute proceeds without optional |

**Preflight ≠ validation:** empty targets → skip, not failed validation.

---

## 8. Future Extensibility

| Extension | Mechanism |
|-----------|-----------|
| New capability ID | Add to §3.1 + TARGET_PROVIDER_SPEC minor version |
| New role | inventory `roles[]` tag |
| New probe | `dsp/targets/probes/` plugin — **not** scenario code |
| Geo / zone filter | inventory metadata — Phase 4+ |
| Deployment API | file-based inventory snapshot only — no live coupling Phase 0–2 |

---

## 9. Safety (Frozen)

| Rule | |
|------|--|
| Never return host outside `target_net` | |
| Never return credentials in TargetSet | |
| Never auto-escalate to production IPs | |
| Resolver MUST be in-lab or explicit config | |

---

## 10. Phase Rollout

| Phase | Capabilities implemented |
|-------|-------------------------|
| 1 | `alive_host`, `dns_resolver`, `http_host`, `https_host` |
| 2 | `web_app`, `ssh_host` |
| 3 | `linux_host`, `windows_host`, `web_server`, `dns_server` |
| 4 | `domain_controller`, `database_server` |

Manifest may declare future capability IDs — Provider returns empty until phase ships (skip behavior).

---

## 11. Related Documents

- [SCENARIO_MANIFEST_SPEC.md](./SCENARIO_MANIFEST_SPEC.md) — `supported_targets`
- [SCENARIO_INTERFACE_FREEZE.md](./SCENARIO_INTERFACE_FREEZE.md) — `ScenarioSkipError`
- [WORKSPACE_BOUNDARY.md](./WORKSPACE_BOUNDARY.md) — no deployment import
