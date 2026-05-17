# Spec 005 — CLI Extension Policy

> Binds to: constitution §3, §8, §9, M-1, M-6, P-2, P-7. Refines L1
> from spec 001.

## 1. Goal

Define how `aella_cli` (L1, Python) **grows** over time. The CLI is
the operator-facing contract; every new capability shows up here as
a new nested subcommand. This spec exists so that growth is
predictable, additive, and free of architecture violations.

## 2. Architecture

```
aella_cli (entrypoint: appliance_cli:main — root single-file module)
 ├─ appliance                          [existing, preserved]
 │    ├─ status   → cmd_appliance_status
 │    └─ info     → cmd_appliance_info
 │
 ├─ lab                                [existing, preserved]
 │    ├─ deploy   → cmd_lab_deploy     [--nodownload for sensor]
 │    ├─ download → cmd_lab_download
 │    ├─ start    → cmd_lab_start
 │    ├─ stop     → cmd_lab_stop
 │    ├─ destroy  → cmd_lab_destroy
 │    └─ status   → cmd_lab_status
 │
 ├─ mirror        [future, spec 007]   → xdr-lab-ovs-manager.sh
 ├─ snapshot      [future, spec 009]   → xdr-lab-snapshot-manager.sh
 ├─ nat           [future, spec 010]   → xdr-lab-nat-manager.sh
 └─ scenario      [future, spec 008]   → xdr-lab-scenario-runner.sh
```

Top-level groups MUST stay shallow (one extra nesting level under
the group). The pattern is **`aella_cli <group> <verb> [target]
[flags]`**.

## 3. Component Responsibilities

### 3.1 Argument parsing

- The CLI uses `argparse` with `add_subparsers(required=True)` at
  every level so that an under-specified invocation gets a help
  message and a non-zero exit (`return 2`).
- Each leaf parser MUST set `set_defaults(handler=cmd_…)`.
- `target` arguments that name a VM MUST go through
  `_validate_lab_vm(target, allow_all=…)`.

### 3.2 Handler shape

Every handler:

```
@log_command
def cmd_<group>_<verb>(args: argparse.Namespace) -> int:
    # 1. Validate inputs against L4 config.
    # 2. _require_<runtime_script>()  (helper similar to _require_lab_manager)
    # 3. Build argv via a _<group>_argv(...) helper.
    # 4. rc, out, err = shell_cmd_exec(argv)
    # 5. return _emit_streams(rc, out, err)
```

Mandatory properties:

- Wrapped with `@log_command`.
- Returns `int` (the process exit code is propagated).
- Calls `shell_cmd_exec` exactly once for the main action.
- Never imports `subprocess` directly outside `shell_cmd_exec`.
- Never builds its own argv with `shell=True` semantics — always
  pure argv list.

### 3.3 Runtime script delegation

- Each top-level group corresponds to **one** L2 script under
  `/opt/xdr-lab/scripts/`.
- The CLI MUST provide a `_require_<script>()` helper that checks
  the script exists and emits a structured `…_missing` log if
  not.
- The script's CLI surface (the action verb and its positional
  target) MUST mirror the Python subcommand structure 1:1. This
  keeps the L1↔L2 contract auditable.

## 4. `shell_cmd_exec` Usage

`shell_cmd_exec(argv, *, cwd=None, env=None, check=False)` is the
**only** sanctioned way to invoke external commands.

Rules:

- Always pass a `Sequence[str]`, never a single shell string.
- Never set `shell=True` (the helper does not even expose it).
- Use `check=True` when the failure should raise `RuntimeError`;
  `main()` translates that into a structured `handler_runtime_error`
  and exit 1.
- The structured `shell_cmd_exec` event already logs the argv on
  entry; the handler MUST NOT add a duplicate `LOG.info("running
  %s", …)` line.
- stderr from the child process is preserved verbatim into the
  operator's stderr via `_emit_streams`.

`shell_cmd_exec` MUST NOT be used to call binaries that L2 owns
exclusively (no `virsh`/`virt-install`/`qemu-img`/`ovs-vsctl`/
`iptables` from L1, ever — constitution P-2).

## 5. Validation Philosophy

- **Inventory validation.** Any `target` that is a VM name is
  validated against `_lab_vm_names_effective()`. `all` is allowed
  only where the corresponding L2 script accepts the literal
  string `all`.
- **Script presence.** Every group MUST have a `_require_<script>()`
  helper. Missing script → `SystemExit` with a clear message
  pointing at install/packaging.
- **Argument coherence.** Per-flag validation happens in L1
  before the shell call. Example: a future `nat add <vm> <port>`
  MUST validate `<port>` is a 1..65535 integer in L1 rather than
  relying on the shell to fail.
- L1 does NOT perform feasibility checks that require privileged
  tooling (e.g. "is `br0` up?"). Those checks live in L2.

## 6. Orchestration-Only Policy

`appliance_cli.py` is and remains orchestration-only:

- It MUST NOT call `virsh`, `virt-install`, `qemu-img`,
  `ovs-vsctl`, `iptables`, `ip`, `brctl`, `sudo`, `apt`, `dnf`,
  `systemctl` (other than read-only `is-active` via L2 if needed).
- It MUST NOT read `/opt/xdr-lab/images/`, `/opt/xdr-lab/runtime/`,
  or `/opt/xdr-lab/logs/`. It MAY read `/opt/xdr-lab/config/lab-vms.json`
  via `_lab_vm_names_effective()` for validation.
- It MUST NOT write to disk under `/opt/xdr-lab/`. All
  side effects on disk happen in L2.

## 7. Nested Command Philosophy

- Two levels of nesting is the **maximum**. Anything deeper goes
  into flags or into a new top-level group.
- Verbs are imperative and operate on a target:
  `deploy <vm>`, `enable <vm>`, `revert <vm> <snap>`, `add <vm>
  <port>`. They do not silently default to "all".
- The string `all` is the only valid placeholder; no other
  wildcard is accepted.
- Help text on each parser is mandatory (`help="…"`); operators
  rely on `aella_cli <group> --help` for discovery.

## 8. Operational Assumptions

- Operators invoke `aella_cli` from a normal shell (or from a
  service script). No interactive prompts; arguments are
  exhaustive.
- The CLI runs as a user that can `shell_cmd_exec` the L2
  scripts under `/opt/xdr-lab/scripts/`. Privilege escalation, if
  needed, lives in those scripts, not in L1.

## 9. Runtime Flow (canonical extension)

Adding a new group `mirror` looks like:

```
1. Add /opt/xdr-lab/scripts/xdr-lab-ovs-manager.sh
   - mirrors the conventions of xdr-lab-vm-manager.sh:
     set -euo pipefail, log_structured, die, require_cmd, main args.
2. In the root appliance_cli.py (flat single-file module —
   NOT src/stellar_appliance_cli/):
   - LAB_OVS_MANAGER = Path("/opt/xdr-lab/scripts/xdr-lab-ovs-manager.sh")
   - _require_ovs_manager() (parallels _require_lab_manager).
   - cmd_mirror_enable / disable / status handlers, each with
     @log_command, validation, _ovs_argv(action, target, extra),
     shell_cmd_exec, _emit_streams.
   - In _build_parser():
        mirror = sub.add_parser("mirror", help="…")
        mirror_sub = mirror.add_subparsers(dest="mirror_cmd", required=True)
        ...
3. Add a spec entry under .specify/specs/007-ovs-mirror-policy/spec.md
   (already exists). Update specs-index.md if needed.
```

The same pattern applies to `snapshot` (spec 009), `nat` (spec
010), `scenario` (spec 008).

## 10. Failure Handling Philosophy

- Argparse errors → argparse exits; `main()` catches
  `SystemExit` and returns the underlying integer.
- Validation errors (`_validate_lab_vm`) → `SystemExit` with a
  one-line message naming the allowed set.
- Script-missing errors → `SystemExit` pointing at packaging
  (`/opt/xdr-lab/scripts/…`).
- Runtime errors from `shell_cmd_exec(check=True)` →
  `handler_runtime_error` structured log + exit 1.
- Non-zero rc from `shell_cmd_exec(check=False)` → propagated
  unchanged. The CLI does not invent retry/backoff.

## 11. Recovery Philosophy

- L1 is stateless. Recovery from a bad release of the CLI is
  `pip install --force-reinstall stellar-appliance-cli==<good>`
  or the equivalent debian downgrade.
- A regression in L1 cannot corrupt L2/L3/L4/L5; the worst case
  is that operators cannot drive the appliance until the CLI is
  fixed.

## 12. Future Extension Guidance

When adding a new subcommand, future contributors MUST:

1. Identify the spec that governs the capability (or create a
   new spec, after amending the constitution if needed).
2. Add the L2 script first (`/opt/xdr-lab/scripts/…`) following
   the existing patterns.
3. Add the L1 subparser + handler following the templates in §9.
4. Update `lab-vms.json` schema if new declarative fields are
   needed (with a `schema_version` bump if breaking).
5. Update `skills/appliance-cli-skill.md` and any other relevant
   skill with the new conventions.
6. Verify the constitution and the relevant spec's "Validation
   Philosophy" still pass.

## 13. Forbidden Implementation Patterns

- A top-level flat command structure (`aella_cli deploy …`)
  that bypasses the group/verb pattern.
- Using `subprocess.run`/`subprocess.Popen` outside
  `shell_cmd_exec`.
- Using `shlex.split`, `shell=True`, or string-concatenated
  shell commands.
- Hidden global state (module-level mutable singletons) in L1.
- Hiding output from the operator (no `>/dev/null`,
  `stderr=PIPE` then dropping). The CLI is transparent.
- Modifying the `aella_cli` entrypoint in `setup.py`
  (constitution P-7).
- Adding a `--force` flag that bypasses inventory validation.
  Forbidden because it normalizes inventory violations.
- Re-implementing inventory parsing outside
  `_lab_vm_names_effective()` (single source of truth for the
  CLI).

## 14. Validation Philosophy

A CLI extension is valid only if:

1. `aella_cli --help` still lists `appliance` and `lab` exactly
   as today, plus any newly added groups.
2. `aella_cli lab --help` and `aella_cli appliance --help`
   list their existing verbs exactly as today.
3. Every new handler is wrapped with `@log_command`.
4. Every new handler validates VM targets via
   `_validate_lab_vm`.
5. Every new handler delegates to L2 via `shell_cmd_exec`
   exactly once for the primary action.
6. `setup.py` still declares
   `aella_cli=appliance_cli:main` against
   `py_modules=["appliance_cli"]` (root single-file module).
   No dotted module path
   (`stellar_appliance_cli.appliance_cli:main`) is
   reintroduced.
7. `pip install -e .` followed by `aella_cli --help` succeeds
   without runtime privileges, and `python -c "import
   appliance_cli; appliance_cli.main"` resolves the same
   callable as the console-script.
