# Detection Scenario Platform — Scenario Manifest Specification

**문서 버전:** 1.0.0 (Phase 0.5 — **FROZEN**)  
**상태:** Canonical contract — implementation MUST conform  
**Supersedes:** SCENARIO_FRAMEWORK_SPEC.md §5.1 (detail expanded, not replaced)

---

## 1. Purpose

`manifest.yaml`은 시나리오 플러그인의 **자기 기술(self-describing) 계약**이다.  
Plugin Loader·Validation Engine·Reporting Engine·Target Provider가 코어 수정 없이 시나리오 메타데이터만으로 동작한다.

**Freeze 선언:** `manifest_schema_version: "1.0.0"` 필드 semantics는 Phase 1 구현 시작 전 변경 불가. Breaking change는 `2.0.0` + migration ADR.

---

## 2. File Location & Identity

| Rule | Requirement |
|------|-------------|
| Path | `scenarios/<id>/manifest.yaml` |
| `id` field | MUST equal directory name `<id>` |
| `id` format | `^[a-z][a-z0-9_]{1,63}$` (snake_case, 2–64 chars) |
| Class binding | `scenario.py` → `Scenario.scenario_id()` MUST return same `id` |

---

## 3. Full Schema

```yaml
# ─── FROZEN HEADER ───
manifest_schema_version: "1.0.0"   # REQUIRED — manifest format version
id: string                          # REQUIRED
name: string                        # REQUIRED — human title (was: title)
version: string                     # REQUIRED — scenario semver
description: string                 # REQUIRED — multi-line OK

# ─── CLASSIFICATION ───
category: string                    # REQUIRED — enum §3.2
tags: [string]                      # OPTIONAL — default []
enabled: bool                       # OPTIONAL — default true

# ─── TARGET & PROTOCOL ───
supported_targets:                  # REQUIRED
  requires: [string]                # capability IDs §TARGET_PROVIDER_SPEC
  optional: [string]                # OPTIONAL — default []
  max_hosts: int                    # OPTIONAL — default from platform
supported_protocols: [string]       # REQUIRED — enum §3.3

# ─── PROFILES (FROZEN CONTRACTS) ───
validation_profile: object          # REQUIRED — §5
report_profile: object              # REQUIRED — §6
detection_mappings: [object]        # OPTIONAL — §7 (catalog mirror)

# ─── EXECUTION ───
defaults: object                    # OPTIONAL — scenario params
safety: object                      # REQUIRED — §8
requirements: object                # OPTIONAL — §9

# ─── IMPLEMENTATION BINDING ───
executor: object                    # REQUIRED — §10
```

---

## 4. Field Reference

### 4.1 Required Fields

| Field | Type | Validation |
|-------|------|------------|
| `manifest_schema_version` | string | MUST be `"1.0.0"` until ADR supersedes |
| `id` | string | snake_case, unique in registry |
| `name` | string | 1–128 chars, non-empty |
| `version` | string | semver `MAJOR.MINOR.PATCH` |
| `description` | string | 1–2048 chars |
| `category` | enum | §3.2 |
| `supported_targets.requires` | list | ≥1 capability; known IDs only |
| `supported_protocols` | list | ≥1 protocol; known IDs only |
| `validation_profile` | object | §5 schema |
| `report_profile` | object | §6 schema |
| `safety` | object | §8 schema |
| `executor` | object | §10 schema |

### 4.2 Optional Fields

| Field | Default | Notes |
|-------|---------|-------|
| `tags` | `[]` | free-form labels |
| `enabled` | `true` | `false` → discovered but not runnable |
| `supported_targets.optional` | `[]` | soft requirements |
| `supported_targets.max_hosts` | platform default (2) | safety cap |
| `defaults` | `{}` | CLI/env override |
| `detection_mappings` | `[]` | links to DETECTION_CATALOG |
| `requirements` | `{}` | python packages, min dsp version |

### 4.3 Enumerations (Frozen v1.0.0)

#### 4.3.1 `category`

`network` | `dns` | `web` | `auth` | `endpoint` | `identity` | `composite`

#### 4.3.2 `supported_protocols`

`dns_udp` | `dns_tcp` | `http` | `https` | `ssh` | `smb` | `ldap` | `rdp` | `kerberos`

(미사용 protocol 선언 금지 — Loader validation error)

#### 4.3.3 `supported_targets.requires` / `optional`

Capability IDs — [TARGET_PROVIDER_SPEC.md](./TARGET_PROVIDER_SPEC.md) §4:

`alive_host` | `dns_resolver` | `http_host` | `https_host` | `web_app` | `ssh_host` | `windows_host` | `linux_host` | `domain_controller` | `database_server`

Phase 1 implements subset; unknown ID at load time → **warning** (forward compat), at run time → **skip** if unfulfilled.

---

## 5. validation_profile (Frozen)

```yaml
validation_profile:
  profile_version: "1.0.0"          # REQUIRED
  metrics:                          # REQUIRED — ≥1 metric
    - name: string                  # metric key in ValidationResult
      event_filter:                 # REQUIRED
        event: string | [string]    # event name(s)
        status: string | [string]   # optional status filter
      aggregate: count | sum | distinct_artifact | ratio | json_extract
      json_path: string             # if aggregate=json_extract
  success:                          # REQUIRED — threshold map
    <metric_name>:
      min: number                   # optional
      max: number                   # optional
      eq: string | number | bool    # optional
  partial: {}                       # OPTIONAL — same shape as success
  fail_fast: [string]               # OPTIONAL — invariant IDs
```

**Rules:**

- Validation Engine reads **only** this block + Event Store — no hardcoded per-scenario if/else in core
- Metric names MUST be unique within profile
- `success` empty → Loader reject

**Example (dns_tunnel):**

```yaml
validation_profile:
  profile_version: "1.0.0"
  metrics:
    - name: query_sent
      event_filter: { event: query_sent, status: sent }
      aggregate: count
    - name: idx_pattern_count
      event_filter: { event: query_sent, status: sent }
      aggregate: count
      # idx filter applied via evidence.idx_pattern=true in executor
    - name: avg_label_length
      event_filter: { event: query_sent }
      aggregate: json_extract
      json_path: $.label_length
  success:
    query_sent: { min: 1 }
    idx_pattern_ratio: { min: 0.8 }
    avg_label_length: { min: 40 }
  fail_fast: [SOT_EMPTY_AFTER_EXECUTE]
```

---

## 6. report_profile (Frozen)

```yaml
report_profile:
  profile_version: "1.0.0"          # REQUIRED
  highlight_metrics: [string]       # REQUIRED — subset of validation metrics
  sample_events: int                # OPTIONAL — default 5, max 20
  sample_filter:                    # OPTIONAL
    event: string | [string]
  detail_level: summary | standard | verbose  # OPTIONAL — default standard
```

Reporting Engine MUST use `highlight_metrics` for scenario table columns — not ad-hoc metric names.

---

## 7. detection_mappings (Optional)

```yaml
detection_mappings:
  - detection_model_id: string      # e.g. stellar.dns_tunnel
    vendor: string                  # stellar | splunk | defender | ...
    catalog_ref: string             # DETECTION_CATALOG row key
    expected_signal: string         # NDR | SIEM | EDR | WAF | ...
    status: validated | planned | candidate
```

**Rules:**

- Informational for adapters — **does NOT** affect traffic validation
- Vendor-specific query logic MUST NOT appear in manifest
- Canonical catalog: [DETECTION_CATALOG.md](./DETECTION_CATALOG.md)

---

## 8. safety (Required)

```yaml
safety:
  max_events: int                   # REQUIRED — hard cap per scenario run
  max_duration_sec: int             # REQUIRED — executor timeout hint
  allowed_domains: [string]         # OPTIONAL — DNS scenarios
  allowed_ports: [int]              # OPTIONAL — network scenarios
  forbidden_actions: [string]       # REQUIRED — enum §8.1
  target_net_enforced: bool         # OPTIONAL — default true
```

#### 8.1 `forbidden_actions` (frozen enum)

`malware_execute` | `privilege_escalation` | `data_exfiltration` | `destructive_sql` | `valid_credential_use` | `ransomware` | `lateral_movement`

Manifest MUST list applicable forbidden actions explicitly (may be `[]` only for pure network scenarios with justification in description).

---

## 9. requirements (Optional)

```yaml
requirements:
  dsp_min_version: string           # semver — platform compatibility
  python_min_version: string        # default "3.11"
  packages: [string]                # pip package names
  platform: [linux]                 # OPTIONAL — default [linux]
```

Import failure → plugin status `unavailable`, not crash entire registry.

---

## 10. executor (Required)

```yaml
executor:
  module: string                    # default "executor"
  entrypoint: string                # default "run"
  class_name: string                # scenario.py Scenario class, default derived
  remote_capable: bool              # default false
  dry_run_supported: bool           # default true
```

---

## 11. Validation Rules (Loader)

| ID | Rule | On failure |
|----|------|------------|
| M1 | `manifest_schema_version` supported | reject plugin |
| M2 | `id` == folder name | reject plugin |
| M3 | semver valid | reject plugin |
| M4 | all required fields present | reject plugin |
| M5 | enum values known (warn on unknown target capability) | reject / warn |
| M6 | `validation_profile.metrics` non-empty | reject plugin |
| M7 | `highlight_metrics` ⊆ validation metric names | reject plugin |
| M8 | `safety.max_events` > 0 | reject plugin |
| M9 | duplicate `id` in registry | reject duplicate (first wins) |
| M10 | `enabled: false` | register as disabled, skip run |

---

## 12. Versioning Strategy

### 12.1 Two Version Dimensions

| Version | Field | Meaning |
|---------|-------|---------|
| Manifest schema | `manifest_schema_version` | Format of manifest.yaml |
| Scenario impl | `version` | Plugin implementation semver |

### 12.2 Scenario `version` Semver

| Bump | When |
|------|------|
| MAJOR | Breaking validation_profile metrics rename, executor contract change |
| MINOR | New optional defaults, new metrics (backward compatible thresholds) |
| PATCH | Bugfix in executor only, manifest unchanged |

### 12.3 Manifest Schema Evolution

```
1.0.0 (FROZEN Phase 0.5)
  ↓ future
2.0.0 — requires ADR + Loader migration + manifest_schema_version bump
```

Loader MUST reject unknown `manifest_schema_version` major without migration path.

---

## 13. Backward Compatibility Strategy

| Change type | Strategy |
|-------------|----------|
| New optional manifest field | MINOR schema bump; Loader default fill |
| New metric in validation_profile | Scenario MINOR bump; old runs still valid |
| Renamed metric | Scenario MAJOR bump; migration script for historical reports |
| New target capability ID | Add to TARGET_PROVIDER_SPEC; old manifests valid |
| Removed enum value | MAJOR schema bump + ADR |

**Run reproducibility:** `manifest.snapshot.json` saved per run with resolved config — immutable after run start.

---

## 14. Manifest Lifecycle

```
┌─────────────┐
│   AUTHOR    │  Developer edits manifest.yaml
└──────┬──────┘
       ▼
┌─────────────┐
│  DISCOVER   │  Plugin Loader scan
└──────┬──────┘
       ▼
┌─────────────┐
│  VALIDATE   │  Schema + semantic rules (§11)
└──────┬──────┘
       ├── fail ──► rejected (log error, not in registry)
       ▼ pass
┌─────────────┐
│  REGISTER   │  Registry[id] = {manifest, status, class?}
└──────┬──────┘
       ▼
┌─────────────┐
│  RESOLVE    │  Run start: defaults + CLI + env → snapshot
└──────┬──────┘
       ▼
┌─────────────┐
│  EXECUTE    │  validation_profile drives post-run validation
└──────┬──────┘
       ▼
┌─────────────┐
│  ARCHIVE    │  manifest.snapshot.json in run directory
└─────────────┘
```

---

## 15. Example Manifest (dns_tunnel)

```yaml
manifest_schema_version: "1.0.0"
id: dns_tunnel
name: DNS Tunnel — idx-pattern UDP/53
version: "1.0.0"
description: >
  Generates Stellar-pattern DNS tunnel queries (strt/idx/end FQDNs)
  via raw UDP/53. Response not required for validation.

category: dns
tags: [ndr, tunnel, udp53]
enabled: true

supported_targets:
  requires: [dns_resolver]
  optional: [alive_host]
  max_hosts: 1

supported_protocols: [dns_udp]

validation_profile:
  profile_version: "1.0.0"
  metrics:
    - name: query_sent
      event_filter: { event: query_sent, status: sent }
      aggregate: count
    - name: idx_pattern_count
      event_filter: { event: query_sent, status: sent }
      aggregate: count
    - name: avg_label_length
      event_filter: { event: query_sent }
      aggregate: json_extract
      json_path: $.label_length
  success:
    query_sent: { min: 1 }
  fail_fast: [SOT_EMPTY_AFTER_EXECUTE]

report_profile:
  profile_version: "1.0.0"
  highlight_metrics: [query_sent, idx_pattern_count, avg_label_length]
  sample_events: 5

detection_mappings:
  - detection_model_id: stellar.dns_tunnel
    vendor: stellar
    catalog_ref: dns_tunnel.stellar
    expected_signal: NDR
    status: validated

defaults:
  base_domain: dns-tunnel.com
  duration_sec: 180

safety:
  max_events: 15000
  max_duration_sec: 240
  allowed_domains: [dns-tunnel.com]
  allowed_ports: [53]
  forbidden_actions: []
  target_net_enforced: true

requirements:
  dsp_min_version: "1.0.0"
  python_min_version: "3.11"

executor:
  module: executor
  entrypoint: run
  remote_capable: false
  dry_run_supported: true
```

---

## 16. Related Documents

- [PLUGIN_DISCOVERY_SPEC.md](./PLUGIN_DISCOVERY_SPEC.md)
- [SCENARIO_INTERFACE_FREEZE.md](./SCENARIO_INTERFACE_FREEZE.md)
- [SCENARIO_FRAMEWORK_SPEC.md](./SCENARIO_FRAMEWORK_SPEC.md)
- [TARGET_PROVIDER_SPEC.md](./TARGET_PROVIDER_SPEC.md)
- [docs/adr/0003-scenario-plugin-architecture.md](./docs/adr/0003-scenario-plugin-architecture.md)
