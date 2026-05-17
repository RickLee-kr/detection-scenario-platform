# Spec 011 — Operational Safety

> Binds to: constitution §4, §6, §10 (all M-* rules), §11 (all
> P-* rules). Cross-cuts every other spec.

## 1. Goal

Define the **safety envelope** within which every command in this
project operates. Safety is not a feature; it is a property that
every L1 handler and every L2 script MUST preserve.

This spec exists to make the implicit "do no harm" rules of the
constitution **enforceable by checklist**.

## 2. Architecture

Safety is enforced at four chokepoints:

1. **Argument validation (L1).** No L2 script receives an
   un-validated target.
2. **Inventory scoping (L2).** No L2 script acts on objects
   outside the declared lab inventory.
3. **Pre-mutation validation (L2).** No L2 script mutates state
   without first asserting that preconditions hold.
4. **Structured logging (L1+L2).** Every mutation is announced
   before it happens.

If any of the four is bypassed, the operation is unsafe regardless
of intent.

## 3. Component Responsibilities

### 3.1 L1 — argument validation

- `_validate_lab_vm(target, allow_all=…)` is the canonical
  validator. Every handler that takes a VM target MUST call it.
- Numeric flags (ports, sizes) MUST be range-checked in L1.
- "Yes/no" destructive prompts MUST be expressed as explicit
  flags (`--yes`, `--force` — see §6) rather than interactive
  prompts; the CLI is non-interactive.

### 3.2 L2 — inventory scoping

Every L2 script MUST:

- Read `lab-vms.json` once at the top of the operation.
- Build the in-scope set (VM names, mirror ports, iptables
  rules, snapshots) from the config.
- Refuse to mutate anything outside the set, including:
  - VMs not in `lab-vms.json::vms`.
  - libvirt domains, OVS ports, iptables rules, snapshots with
    names not derivable from the config.
- When iterating over a system-level enumeration (e.g.
  `virsh list --all`, `ovs-vsctl list mirror`, `iptables -t nat
  -S`), filter that enumeration against the in-scope set
  **before** issuing any destructive command.

### 3.3 L2 — pre-mutation validation

For each verb, the L2 script MUST verify:

- The target exists (or is allowed to not exist, e.g. `destroy`
  on a missing VM is a WARN-no-op).
- The preconditions for the verb are satisfied (e.g.
  `start` requires the domain to be defined; `revert` requires
  the snapshot to exist).
- The host preconditions are satisfied (e.g. `br0` exists for
  any verb that needs it).

If any precondition fails, the script `die`s before issuing the
mutation.

### 3.4 L1+L2 — structured logging of mutations

Every mutation MUST log:

- A `_begin` event with target and parameters.
- The argv being executed (via `shell_cmd_exec` log line in L1
  and the L2 script's own logs).
- A `_end` event with result.
- A `_failed` event if the mutation failed.

See spec 012 for the log shape.

## 4. Operational Assumptions

- The appliance is operated by a human (or CI account) that
  understands the lab is not production-isolated by default.
- Operator confirmation is expressed via explicit flags, not
  interactive `read`.
- The appliance is **not** designed to be safe against a
  malicious operator. Its safety guarantees are against
  **mistakes** by a well-intentioned operator.

## 5. Runtime Flow (canonical safety check)

```
operator → aella_cli <group> <verb> <target> [--force]
        │
        ▼
L1: parser validates target via _validate_lab_vm
L1: parser validates flags
L1: _require_<script>() asserts L2 entrypoint exists
L1: shell_cmd_exec invokes L2
        │
        ▼
L2: set -euo pipefail
L2: load lab-vms.json or die
L2: build in-scope set
L2: per-target loop:
      - require_cmd <tool>
      - assert preconditions or die
      - log_structured INFO <verb>_begin target=…
      - execute mutation
      - log_structured INFO <verb>_end target=…
L2: exit 0 (or non-zero with a tail summary)
```

If `--force` is set, L2 MAY skip a single, explicitly-named
precondition (e.g. "snapshot exists" check) but MUST log
`force_used skipped=<precondition>` so the bypass is auditable.

## 6. Destructive Action Prevention

The following verbs are destructive and MUST follow the rules
below:

- `lab destroy <vm>` — undefines a domain and removes its
  runtime qcow2.
  - Rule: must be called with an explicit VM name. `destroy
    all` is permitted because the iteration is still
    inventory-scoped, but it MUST log every target it intends
    to touch **before** acting.
- `snapshot delete <vm> <snap>` (future) — must validate snap
  exists.
- `snapshot revert <vm> <snap>` (future) — must be explicit;
  no scenario engine may invoke revert (spec 008).
- `mirror disable` (future) — only removes the named mirror
  object; never deletes bridges or ports.
- `nat disable` (future) — flushes only `XDR_LAB_DNAT` and
  removes only the lab's PREROUTING jump.

A future global `aella_cli reset` or `aella_cli purge` verb is
**forbidden by default**. If ever introduced, it would require:

- An accompanying spec amendment.
- An explicit `--confirm-irreversible` flag with no shorthand.
- Inventory-scoped iteration that prints every target before
  acting.

## 7. Rollback-safe Execution

Every deploy-class operation (deploy, mirror enable, nat enable,
snapshot take, scenario run) MUST be rerunnable after a partial
failure with no manual cleanup required:

- **Deploy:** idempotent existence check (spec 002 §11).
- **Mirror enable:** named, scoped, incremental (spec 007 §6).
- **NAT enable:** rebuild deterministically from config (spec
  010 §3.2).
- **Snapshot take:** failure leaves no half-applied snapshot
  (libvirt is transactional per VM); sidecar updated only on
  success (spec 009 §9).
- **Scenario run:** preflight gates everything; engine failure
  does not skip the post-snapshot (spec 008 §5).

A partial failure MUST surface a structured error with enough
context to identify the failing step. The operator's next action
is "re-run the same command".

## 8. Operator Confirmation Philosophy

- **No interactive prompts.** The CLI is scriptable.
- **Explicit flags are confirmation.** `--force`, `--yes`,
  `--confirm-irreversible` (if ever introduced) are the
  confirmation mechanism.
- **Defaults are conservative.** Where a flag's absence vs.
  presence is ambiguous, the absence means "don't do the
  destructive thing".
- **Logged confirmation.** Whenever a `--force`-class flag is
  used, the L2 script MUST log it (`force_used flag=…`).

## 9. Validation-before-execution Philosophy

For every L2 verb, the implementation MUST be structured as:

```
parse_args
load_config_or_die
build_scope_or_die
for target in scope:
    validate_target_or_warn_and_skip
    validate_preconditions_or_die
    log_begin
    perform_mutation
    log_end
summarize
```

Specifically:

- All `die`-class errors happen **before** any mutation.
- `WARN`-class errors per-target do not abort the rest of the
  loop unless `--strict` is requested.
- A precondition check that depends on system state (e.g. "is
  br0 up?") MUST run with the same privilege as the mutation,
  so the operator doesn't see "check passed, mutation failed".

## 10. Cleanup Safety Philosophy

- Cleanup verbs (`destroy`, `disable`, `delete`, `prune`,
  future `purge`) MUST always derive their targets from the
  declared inventory (or from explicit operator arguments), not
  from a system-level enumeration.
- `rm` calls MUST use full, quoted paths under `/opt/xdr-lab/`.
  No `rm -rf` of variables that could expand to empty.
- `virsh undefine` MUST never run inside a loop over `virsh
  list --all` without filtering against the inventory
  (constitution P-14).
- Cleanup MUST be **observable**: every removal is logged.
- Cleanup MUST be **recoverable**: removed runtime state is
  rebuildable from L3 base + L4 config (spec 001 §7).

## 11. Failure Handling Philosophy (cross-cutting)

- Errors MUST be structured. No bare `echo "oops" >&2`.
- Errors MUST include enough context (which target, which
  precondition, which command).
- `die` is the canonical error exit in L2; it logs first, then
  exits non-zero.
- L1 propagates non-zero exit codes verbatim; it does NOT
  translate non-zero into zero "for convenience".

## 12. Recovery Philosophy (cross-cutting)

- Recovery procedures are **documented per spec**. Operators
  follow the spec, they do not improvise.
- Recovery MUST NOT require destructive global resets
  (constitution §11). If a spec's recovery procedure ever
  needs one, the spec MUST be amended first.

## 13. Future Extensibility Guidance

- A future "pre-flight diagnostic" subcommand
  (`aella_cli appliance preflight`) MAY be added to surface
  precondition checks in one place. It MUST be read-only.
- A future "dry-run" flag on every mutating verb is
  encouraged. Implementation: L2 receives an env var
  `XDR_LAB_DRY_RUN=1` and short-circuits each mutation with a
  structured `dry_run_would_do` event.

## 14. Forbidden Implementation Patterns (compiled)

- Operating on non-inventory objects (constitution M-16,
  P-4, P-14).
- Wildcard removals (`rm -rf /opt/xdr-lab/*`,
  `iptables -F`, `ovs-vsctl emer-reset`) — see constitution
  P-3, P-10, P-13.
- Interactive prompts in any L1 handler or L2 script.
- Silent fallbacks that hide mutation (`|| true` is allowed
  only on documented best-effort operations and only when the
  preceding command has been logged).
- Catch-all exception handlers in L1 that swallow stack traces
  without logging them.
- `set +e` regions in L2 longer than a single command, unless
  the script restores `set -e` immediately and the bypass is
  logged.

## 15. Validation Philosophy

A change is safe only if:

1. It passes the four chokepoints (§2).
2. It does not introduce a new destructive verb without a
   spec amendment.
3. It does not weaken any existing precondition check.
4. It does not move a precondition check into the middle of a
   mutation sequence.
5. It does not add an interactive prompt.
6. It does not remove or shorten an existing structured log
   event.

## 16. Safety Checklist (every PR / change)

A contributor MUST verify all of the following for their change:

- [ ] No new `iptables -F` / `-X` / `-P` / `nat -F` patterns.
- [ ] No new `ovs-vsctl emer-reset` / `del-br br0` patterns.
- [ ] No new `virsh undefine` loop over `virsh list --all`.
- [ ] No new `rm -rf` against a variable that could be empty.
- [ ] No new code reads under `/opt/xdr-lab/images/` from L1.
- [ ] No new code writes under `/opt/xdr-lab/` from L1.
- [ ] Every new mutation has a `_begin` and `_end` event.
- [ ] Every new verb validates its target against
      `lab-vms.json`.
- [ ] Every new flag with destructive effect is opt-in.
- [ ] Recovery is documented in the relevant spec.
