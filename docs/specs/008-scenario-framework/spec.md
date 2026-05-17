# Spec 008 — Scenario Framework (Reserved)

> Binds to: constitution §9, M-12, M-15, P-9. Depends on spec 009
> (snapshot runtime) and spec 011 (operational safety).
> **Status: Reserved. No runtime code permitted yet.**

## 1. Goal

Define the **future** architecture for running attack scenarios on
the lab — BAS engines, Caldera, Atomic Red Team, Sliver, Mythic,
and similar — in a way that:

- Is reproducible (snapshot pre, run, snapshot post, revert).
- Is isolated from the appliance's own runtime.
- Cannot accidentally exfiltrate beyond the lab subnet.
- Reuses the existing CLI / runtime / config layering.

This spec **does not** authorize implementation. It exists so that
when implementation is approved, the structure is already agreed.

## 2. Architecture

```
aella_cli scenario <verb> <scenario_id> [target]
        │  (spec 005)
        ▼
xdr-lab-scenario-runner.sh   (new L2 script, future)
        │
        ├─ reads /opt/xdr-lab/scenarios/<scenario_id>/manifest.json
        ├─ orchestrates snapshot-pre   (spec 009)
        ├─ invokes the scenario engine (Caldera/ART/Sliver/Mythic/BAS)
        ├─ collects logs and artifacts
        ├─ orchestrates snapshot-post  (spec 009)
        └─ structured logs            (spec 012)
```

Scenarios are **content**, not code: each scenario lives under
`/opt/xdr-lab/scenarios/<id>/` and is identified by its manifest.
The runner is the only L2 component that knows how to dispatch on
manifest type.

## 3. Component Responsibilities

### 3.1 Scenario manifest (proposed)

`/opt/xdr-lab/scenarios/<id>/manifest.json`:

```
{
  "schema_version": 1,
  "id": "<scenario_id>",
  "engine": "caldera" | "atomic_red_team" | "sliver" | "mythic" | "bas_custom",
  "title": "Human-readable name",
  "targets": ["windows-victim", "linux-server"],
  "preflight": {
    "require_vms_running": true,
    "require_mirror_enabled": true
  },
  "snapshots": {
    "pre": "auto",
    "post": "auto"
  },
  "engine_config": { /* engine-specific */ },
  "artifacts_dir": "/opt/xdr-lab/scenarios/<id>/artifacts"
}
```

Hard rules:

- The manifest is the only declarative source.
- The runner refuses unknown `engine` values.
- Targets MUST be valid keys in `lab-vms.json::vms`.
- Targets MUST NOT include `sensor-vm` (the sensor is observed,
  not attacked).

### 3.2 Engine adapters (sub-scripts)

Inside `/opt/xdr-lab/scripts/scenario-engines/`:

- `caldera.sh`        — drive Caldera operations via its REST API
- `atomic_red_team.sh`— execute Invoke-AtomicTest on Windows /
                         atomic-runner on Linux
- `sliver.sh`         — drive a Sliver C2 session
- `mythic.sh`         — drive a Mythic operator API
- `bas_custom.sh`     — pluggable adapter for any custom BAS

Each adapter:

- Has a fixed CLI surface invoked by
  `xdr-lab-scenario-runner.sh` (e.g.
  `<adapter> prepare|execute|collect|teardown <scenario_dir>`).
- Logs to `/opt/xdr-lab/logs/scenario-runner.log` via the same
  `log_structured` shape (spec 012).
- Is forbidden from touching anything outside the lab subnet.

### 3.3 L1 CLI surface (future)

```
aella_cli scenario list                       # enumerate manifests
aella_cli scenario describe <id>              # print manifest summary
aella_cli scenario run <id>                   # full pre/run/post
aella_cli scenario run <id> --no-snapshot     # operator override
aella_cli scenario revert <id>                # revert to snapshot-pre
aella_cli scenario status <id>                # last run status from log
```

Each handler follows spec 005 conventions.

## 4. Operational Assumptions

- Snapshot runtime (spec 009) is implemented before any
  scenario engine is enabled.
- OVS mirror (spec 007) is implemented and verified before a
  scenario is run with `require_mirror_enabled: true`.
- The lab subnet `10.10.10.0/24` is isolated from production
  networks at the operator's network boundary. The scenario
  framework does NOT add or remove firewall rules of its own.

## 5. Runtime Flow (canonical)

```
aella_cli scenario run my-caldera-op
       │
       ▼
xdr-lab-scenario-runner.sh run my-caldera-op
       │
       ├─ parse /opt/xdr-lab/scenarios/my-caldera-op/manifest.json
       │
       ├─ preflight:
       │    ├─ assert each target VM is running (virsh dominfo + state)
       │    ├─ assert sensor running
       │    └─ if require_mirror_enabled: aella_cli mirror verify
       │
       ├─ snapshot-pre (spec 009) for each target VM
       │
       ├─ dispatch engine adapter:
       │    bash scenario-engines/caldera.sh prepare  <dir>
       │    bash scenario-engines/caldera.sh execute  <dir>
       │    bash scenario-engines/caldera.sh collect  <dir>
       │
       ├─ snapshot-post (spec 009) for each target VM
       │
       └─ structured summary log scenario_run_end id=… result=…
```

## 6. Scenario Isolation Philosophy

- **Targets isolated to lab subnet.** Scenario engines MUST run
  inside the appliance or inside lab VMs; their network
  ingress/egress MUST stay within `10.10.10.0/24` or go through
  the appliance's declared reverse-NAT entries.
- **No production callbacks.** No scenario adapter MAY initiate
  outbound connections to a non-lab destination unless an
  explicit per-scenario operator flag is set and logged.
- **Engine state isolated.** Each scenario's artifacts live
  under `/opt/xdr-lab/scenarios/<id>/artifacts/`; engines MUST
  NOT scatter files across the host.
- **Idempotent dispatch.** Re-running `scenario run <id>`
  triggers a fresh `pre` snapshot (or refuses, depending on a
  future per-scenario policy). It MUST NOT silently resume a
  half-finished run.

## 7. BAS Integration

Generic BAS engines are accommodated through the `bas_custom`
adapter, which loads its own per-vendor configuration from
`engine_config`. Rules:

- BAS engines MUST run with read-only access to the appliance
  config — they read from `engine_config`, not from
  `lab-vms.json` directly.
- BAS engines MUST emit their findings into the scenario's
  `artifacts_dir` only.
- The runner aggregates per-engine logs into structured records
  (spec 012) so SIEM export remains uniform.

## 8. Caldera Integration

- The Caldera adapter assumes a Caldera server is reachable
  from the lab subnet at an operator-declared URL in
  `engine_config.caldera.server_url`.
- Authentication tokens MUST come from
  `engine_config.caldera.token_path` (file path), never inline.
- Operations are launched via Caldera's REST API; the adapter
  polls for completion and copies the operation report into
  `artifacts_dir`.

## 9. Atomic Red Team Integration

- For Windows targets, the adapter invokes
  `Invoke-AtomicTest` via WinRM (entry via reverse NAT, spec
  010) using credentials from `engine_config.art.credentials_path`.
- For Linux targets, the adapter uses an SSH-based atomic
  runner with the same credentials policy.
- The atomic technique set is declared in
  `engine_config.art.techniques`.

## 10. Sliver / Mythic Integration

- Sliver and Mythic adapters are operator-driven; they assume an
  existing C2 server reachable from the lab subnet.
- Implant deployment is the operator's responsibility within the
  scenario; the adapter triggers pre-staged tasks, it does NOT
  build implants on the fly.

## 11. Failure Handling Philosophy

- Preflight failure (target VM down, mirror not enabled) → the
  runner aborts before taking any pre-snapshot. No state change.
- Engine adapter failure during `execute` → the runner still
  takes `snapshot-post` (so forensics survive) and exits
  non-zero with `scenario_run_failed`. Revert to `snapshot-pre`
  is operator-initiated via `scenario revert`.
- Artifact collection failure → WARN; does not fail the run.
- Manifest schema mismatch → hard failure, no snapshot taken,
  no engine invoked.

## 12. Recovery Philosophy

- `aella_cli scenario revert <id>` reverts target VMs to
  `snapshot-pre`.
- `aella_cli scenario run <id>` after a revert is a fresh run.
- A globally bad scenario is removed by deleting its manifest
  directory under `/opt/xdr-lab/scenarios/<id>/`. Active state
  on lab VMs is recovered via revert.

## 13. Future Extensibility Guidance

- New engines are added as new adapters under
  `scenario-engines/` and a new value of the `engine` field.
- New target classes (e.g. macOS VMs) require updates to spec
  002 (KVM runtime) before being accepted here.
- A future "campaign" verb (multi-scenario sequencing) is
  acceptable; it MUST be additive and live above the per-
  scenario runner.

## 14. Forbidden Implementation Patterns

- Implementing the scenario runner inside `appliance_cli.py`
  (constitution P-2).
- Running a scenario without snapshot-pre when the manifest
  declares `snapshots.pre = "auto"` (constitution M-15, spec
  009).
- Forcing `apt install` of engine dependencies during a
  scenario run (constitution P-9). Dependencies are operator-
  side or pre-baked into the relevant VMs.
- Hard-coded credentials anywhere in manifests or adapter
  scripts (constitution P-8).
- Scenario adapters reaching outside the lab subnet without an
  explicit, logged operator override.
- Reverting a snapshot from inside an engine adapter. Revert
  is operator-initiated only.

## 15. Validation Philosophy (for future implementation)

When this spec moves from Reserved to Adopted, validation MUST
confirm:

1. `aella_cli scenario` group exists with the verbs listed in
   §3.3 and follows spec 005.
2. The runner refuses to operate on a target that is not in
   `lab-vms.json::vms`.
3. The runner refuses `engine` values it does not know.
4. Pre-snapshot is taken before any engine adapter step.
5. Post-snapshot is taken even when `execute` failed (so
   forensics survive).
6. Artifacts live only under the scenario's `artifacts_dir`.
7. No new top-level destructive verb is introduced (revert is
   per-scenario, not global).
