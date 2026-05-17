# Skill — Attack Scenario

Operational memory for any task that touches the (future) attack
scenario runner. Governed by spec 008 (Reserved). Read before
drafting `xdr-lab-scenario-runner.sh`, any
`scenario-engines/*.sh` adapter, or the `aella_cli scenario …`
group.

## Hard rules

- The scenario framework is **Reserved**. No runtime code is
  permitted yet; this skill governs *future* implementation.
- Scenarios are **content**, not code: each scenario lives under
  `/opt/xdr-lab/scenarios/<id>/` with a `manifest.json` and
  artifacts subdirectory.
- The scenario runner is an L2 script (`xdr-lab-scenario-
  runner.sh`); it MUST NOT be implemented inside
  `appliance_cli.py` (constitution P-2).
- The sensor VM is **observed**, never attacked: `targets` in a
  manifest MUST NOT include `sensor-vm` (spec 008 §3.1).
- Engine adapters MUST run with read-only access to the lab
  config; they read `engine_config` from the manifest, not
  `lab-vms.json` directly.
- Engine adapters MUST NOT initiate snapshot revert (spec 009).
- All scenario artifacts live under
  `/opt/xdr-lab/scenarios/<id>/artifacts/`; do not scatter
  files across the host.

## Manifest shape (canonical)

```json
{
  "schema_version": 1,
  "id": "<scenario_id>",
  "engine": "caldera | atomic_red_team | sliver | mythic | bas_custom",
  "title": "Human-readable name",
  "targets": ["windows-victim", "linux-server"],
  "preflight": {
    "require_vms_running": true,
    "require_mirror_enabled": true
  },
  "snapshots": { "pre": "auto", "post": "auto" },
  "engine_config": { /* engine-specific */ },
  "artifacts_dir": "/opt/xdr-lab/scenarios/<id>/artifacts"
}
```

Validation rules:

- `engine` MUST be one of the registered values.
- Every `targets[]` MUST exist in `lab-vms.json::vms`.
- `sensor-vm` MUST NOT appear in `targets`.

## Runner lifecycle (mandatory)

```
parse manifest
preflight (assert running VMs, mirror state)
snapshot-pre per target (spec 009)
engine adapter: prepare → execute → collect
snapshot-post per target (even on execute failure)
emit scenario_run_end result=ok|failed
```

Idempotency: `scenario run <id>` always takes fresh pre/post
snapshots. It does NOT resume a half-finished run. (Future
opt-in resume would require a spec amendment.)

## Isolation invariants

- Traffic stays in `10.10.10.0/24` or goes through the
  declared reverse-NAT entries (spec 010).
- No outbound callbacks to non-lab destinations without an
  explicit per-scenario operator flag (logged).
- No credentials inline in manifests. Use
  `<engine>.credentials_path` / `.token_path` patterns.

## Engine adapters

Each adapter under `/opt/xdr-lab/scripts/scenario-engines/`:

- Fixed CLI: `<adapter> prepare|execute|collect|teardown
  <scenario_dir>`.
- Logs to `/opt/xdr-lab/logs/scenario-runner.log` via the
  shared `log_structured` shape (spec 012).
- Reads credentials from paths declared in the manifest.
- Writes findings/artifacts only under
  `<scenario_dir>/artifacts/`.

## When you would otherwise be tempted to…

- **…build implants on the fly inside the adapter:** stop.
  Implants are operator-prepared; the adapter triggers
  pre-staged tasks.
- **…run a scenario without `snapshot-pre` "to save time":**
  stop. If the manifest says `snapshots.pre = "auto"`, the
  runner takes it (M-15).
- **…skip `snapshot-post` because the engine failed:** stop.
  Forensics depend on the post-state.
- **…have the adapter call `aella_cli snapshot revert` on
  failure:** stop. Revert is operator-initiated only.
- **…install engine dependencies with `apt install` during
  the run:** stop. Dependencies are baked into the relevant
  VMs or installed by the operator out-of-band
  (constitution P-9).

## Logging (spec 012)

- `scenario_run_begin id=… engine=…`
- `scenario_preflight_ok` / `scenario_preflight_failed
  reason=…`
- `snapshot_pre_taken id=… vm=… snap=…`
- `engine_step_begin step=…` / `engine_step_end step=…
  result=…`
- `snapshot_post_taken id=… vm=… snap=…`
- `scenario_run_end id=… result=ok|failed`

## Recovery patterns

- **Bad manifest →** runner refuses with
  `scenario_preflight_failed reason=manifest_schema`.
- **Target VM not running →** runner refuses unless
  `preflight.require_vms_running = false`.
- **Mirror not enabled but required →** runner refuses; operator
  runs `aella_cli mirror enable` then retries.
- **Engine adapter failed →** post-snapshot taken; operator
  inspects artifacts; runs `aella_cli scenario revert <id>` to
  return to pre.

## Related specs and skills

- Spec 008 (primary), spec 009 (snapshots — hard dependency),
  spec 007 (mirror — required for sensor observability), spec
  010 (reverse NAT — for operator/engine access), spec 011
  (safety), spec 012 (logging).
- Companion skills: `snapshot-management-skill.md`,
  `ovs-mirror-skill.md`, `reverse-nat-skill.md`,
  `appliance-cli-skill.md`.
