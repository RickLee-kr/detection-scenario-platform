# Skill — Appliance CLI

Operational memory for any task that touches `aella_cli`. The
**authoritative** source is the root single-file module
`appliance_cli.py` at the project root (installed by `setup.py`
via `py_modules=["appliance_cli"]`, entrypoint
`aella_cli=appliance_cli:main`).

`src/stellar_appliance_cli/appliance_cli.py` exists as a
**reference-only** historical snapshot. It is NOT installed, NOT
driven by the console-script, and NOT the source of truth — do
not edit it for CLI changes; edit the root file.

Governed by constitution §3, §8 and spec 005. Read **before**
editing the CLI, adding a new subcommand, or changing `setup.py`.

## Hard rules

- **Preserve the nested command structure.** Operators rely on
  `aella_cli <group> <verb> [target] [flags]`. The current groups
  are `appliance` and `lab` — do not flatten, rename, or
  reshuffle them.
- **Preserve `shell_cmd_exec` usage.** Every external command
  goes through `shell_cmd_exec(argv)`. No new `subprocess.run` /
  `subprocess.Popen` calls. No `shell=True`. No
  `os.system`/`os.popen`.
- **The CLI is orchestration-only.** It MUST NOT call
  `virsh`, `virt-install`, `qemu-img`, `ovs-vsctl`, `iptables`,
  `ip`, `brctl`, `sudo`, `apt`, `dnf`, or `systemctl` directly
  (constitution P-2).
- **Never implement virsh logic in `appliance_cli.py`.** All
  virtualization primitives live in L2 under
  `/opt/xdr-lab/scripts/`. If you find yourself reaching for
  libvirt from Python, you are in the wrong layer.
- **Never break the entrypoint.** `setup.py` MUST keep
  `py_modules=["appliance_cli"]` and:
  ```python
  entry_points={
      "console_scripts": [
          "aella_cli=appliance_cli:main",
      ],
  }
  ```
  Do NOT repackage the CLI as
  `stellar_appliance_cli.appliance_cli:main` or any other dotted
  module path; the root single-file module is the contract
  (constitution P-7).

## Mandatory handler shape

```python
@log_command
def cmd_<group>_<verb>(args: argparse.Namespace) -> int:
    _validate_lab_vm(args.target, allow_all=...)         # if target is a VM
    _require_<runtime_script>()                          # asserts L2 entrypoint exists
    extra: List[str] = []
    if getattr(args, "<flag>", False):
        extra.append("--<flag>")
    rc, out, err = shell_cmd_exec(_<group>_argv("<verb>", args.target, extra))
    return _emit_streams(rc, out, err)
```

Every handler:

- Has `@log_command` (`command_enter` / `command_exit` events).
- Returns `int` (the process exit code).
- Calls `shell_cmd_exec` exactly once for the primary action.
- Forwards child stdout/stderr verbatim via `_emit_streams`.

## Argument validation invariants

- VM target → `_validate_lab_vm(target, allow_all=…)`.
  - Sources: `_lab_vm_names_effective()` (config ∪
    `LAB_KNOWN_VMS` baseline).
  - `all` is accepted only when `allow_all=True` and the
    corresponding L2 verb supports the literal string `all`.
- Numeric flags → range-check in L1.
- Boolean flags → `argparse` `store_true`; never invent
  three-valued logic.

## Adding a new subcommand (canonical recipe)

1. Identify the spec governing the capability. If none, write
   one first (and possibly amend the constitution).
2. Add the L2 script under `/opt/xdr-lab/scripts/` following the
   `xdr-lab-vm-manager.sh` conventions:
   - `set -euo pipefail`
   - `log_structured` helper to its own
     `/opt/xdr-lab/logs/<script>.log`
   - `die`, `require_cmd`
   - reads only from `/opt/xdr-lab/config/lab-vms.json`
3. In the root `appliance_cli.py` (single-file module at the
   project root — NOT `src/stellar_appliance_cli/`):
   - Add a `Path("/opt/xdr-lab/scripts/<new>.sh")` constant.
   - Add `_require_<new>()` mirroring `_require_lab_manager`.
   - Add `_<group>_argv(action, target, extra)` mirroring
     `_lab_argv`.
   - Add the `cmd_<group>_<verb>` handlers (each with
     `@log_command`).
   - In `_build_parser`:
     ```python
     g = sub.add_parser("<group>", help="…")
     g_sub = g.add_subparsers(dest="<group>_cmd", required=True)
     v = g_sub.add_parser("<verb>", help="…")
     v.add_argument("target", help="VM name or 'all'")
     v.set_defaults(handler=cmd_<group>_<verb>)
     ```
4. Update the relevant spec's "Validation Philosophy" and
   `skills/appliance-cli-skill.md` (this file) if conventions
   change.

## Logging invariants

- `@log_command` is required on every handler.
- `shell_cmd_exec` already logs the argv on entry and the
  failure on `check=True` non-zero exit. Do not duplicate.
- `LOG.error("structured_log", extra={"event": …})` for
  user-visible errors, plus a one-line stderr message via
  `print(..., file=sys.stderr)` is acceptable for `SystemExit`
  paths only (see `_validate_lab_vm` / `_require_lab_manager`).

## Failure handling invariants

- `argparse` errors → handled by the existing `SystemExit`
  catch in `main()`. Don't introduce alternate parsers.
- Validation errors → `SystemExit(message)`; main translates to
  exit code.
- `RuntimeError` from `shell_cmd_exec(check=True)` →
  `main()` logs `handler_runtime_error` and returns 1. Do not
  swallow.
- Non-zero rc from `shell_cmd_exec(check=False)` → propagate
  unchanged via `_emit_streams`. No invented retries.

## When you would otherwise be tempted to…

- **…import `libvirt` (Python bindings) "for type safety":**
  stop. L1 talks to L2 via argv. Libvirt belongs in L2.
- **…read `/opt/xdr-lab/images/` to check disk existence
  before calling deploy:** stop. L2 owns that check; the CLI is
  blind to image content.
- **…add a `--force` flag that bypasses validation:** stop.
  Validation is mandatory (spec 011 §6).
- **…add a top-level command like `aella_cli deploy <vm>` for
  brevity:** stop. The nested structure
  (`aella_cli lab deploy <vm>`) is the contract.
- **…rename `aella_cli`:** stop. The entrypoint name is part
  of the appliance contract (constitution §8).
- **…move the CLI into a package (`src/stellar_appliance_cli/`
  or similar) "for tidiness":** stop. The CLI is shipped as a
  flat root `appliance_cli.py` and the `setup.py` entrypoint is
  `appliance_cli:main` (constitution §8, P-7). Repackaging
  requires a constitutional amendment first.
- **…catch every exception in `main()` and print friendlier
  messages:** stop. The existing translation
  (`RuntimeError` → exit 1 with `handler_runtime_error`) is
  what operators expect.

## Recovery patterns

- A bad CLI release is fixed by reinstalling a known-good
  version. L1 has no persistent state to recover.
- Regressions never corrupt L2/L3/L4/L5; worst case is
  operators cannot drive the appliance until the CLI is
  reinstalled.

## Related specs and skills

- Spec 001 (architecture), spec 005 (primary), spec 011
  (safety), spec 012 (logging). Every other spec also
  constrains the CLI when it grows a new group.
- Companion skills: every other skill in `skills/`. The CLI
  is the operator's entry point into all of them.
