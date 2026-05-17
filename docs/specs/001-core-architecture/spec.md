# Spec 001 — Core Architecture

> Binds to: constitution §2, §3, §8, M-1, M-2, M-9, M-10, M-11.

## 1. Goal

Define the **layered architecture** of the XDR Lab Appliance and the
non-negotiable contracts between layers. Every other spec refines a
single layer; this spec is the map.

The goal is that any contributor can, by reading this document alone,
answer:

- "Where does this code belong?"
- "Which layer owns this responsibility?"
- "What is allowed to call what?"

## 2. Architecture

The appliance is composed of seven layers. Each layer has a single
owner directory and a single ownership rule.

```
┌─────────────────────────────────────────────────────────────────┐
│                        OPERATOR (human / CI)                     │
└───────────────────────────────┬─────────────────────────────────┘
                                │  invokes
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ L1  CLI / Orchestration   appliance_cli.py  (project root,      │
│      aella_cli (Python)   flat single-file Python module;       │
│                           src/stellar_appliance_cli/ is         │
│                           reference-only, not authoritative)    │
│      - argparse                                                  │
│      - validates target VMs against config                       │
│      - structured logging                                        │
│      - delegates via shell_cmd_exec                              │
└───────────────────────────────┬─────────────────────────────────┘
                                │  shell_cmd_exec(argv)
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ L2  Runtime / Deployment    /opt/xdr-lab/scripts/                │
│      xdr-lab-vm-manager.sh  (today)                              │
│      xdr-lab-ovs-manager.sh         (future, spec 007)           │
│      xdr-lab-snapshot-manager.sh    (future, spec 009)           │
│      xdr-lab-nat-manager.sh         (future, spec 010)           │
│      xdr-lab-scenario-runner.sh     (future, spec 008)           │
│      - owns virsh / virt-install / qemu-img / ovs-vsctl /        │
│        iptables / sensor deploy invocation                       │
└────────────────┬───────────────────────────────┬────────────────┘
                 │ reads                          │ reads
                 ▼                                ▼
┌──────────────────────────┐   ┌──────────────────────────────────┐
│ L3  Image                │   │ L4  Configuration                │
│     /opt/xdr-lab/images/ │   │     /opt/xdr-lab/config/          │
│     /opt/xdr-lab/images/ │   │     lab-vms.json (schema_version) │
│       sensor/            │   │     (single source of truth)      │
│     (downloaded qcow2,   │   │                                   │
│      sensor script)      │   │                                   │
└──────────────────────────┘   └──────────────────────────────────┘

                 ┌─────────────────────────────┐
                 │ L5  Runtime state           │
                 │     /opt/xdr-lab/runtime/   │
                 │     per-VM ephemeral qcow2  │
                 └─────────────────────────────┘

                 ┌─────────────────────────────┐
                 │ L6  Logging                 │
                 │     /opt/xdr-lab/logs/      │
                 │     JSON-lines from L1 + L2 │
                 └─────────────────────────────┘

                 ┌─────────────────────────────┐
                 │ L7  Network                 │
                 │     br0 (Open vSwitch)        │
                 │     ovs-net + ovs vport     │
                 │     OVS mirror on br0         │
                 │     iptables reverse NAT      │
                 └─────────────────────────────┘
```

## 3. Component Responsibilities

### 3.1 L1 — CLI / Orchestration

Owner file: `appliance_cli.py` at the **project root**, installed
by `setup.py` as a flat top-level module via
`py_modules=["appliance_cli"]`.
Entrypoint: `aella_cli` (see `setup.py`) →
`appliance_cli:main`.

`src/stellar_appliance_cli/appliance_cli.py` is a **reference-
only historical snapshot**. It is NOT installed, NOT driven by
the console-script, and MUST NOT be treated as the source of
truth. CLI changes go into the root `appliance_cli.py`; any
drift is resolved in favor of the root file.

Responsibilities:

- Build the argparse tree (nested subcommands).
- Validate `target` arguments against `lab-vms.json` via
  `_lab_vm_names_effective()`.
- Confirm the runtime entrypoint script exists
  (`_require_lab_manager()` today; sibling helpers in future).
- Configure root logging (`_configure_logging`).
- Wrap each handler with `@log_command`.
- Invoke the runtime layer via `shell_cmd_exec`.
- Convert non-zero exit codes and `RuntimeError` into a structured
  error and a process exit code.

L1 is FORBIDDEN from:

- Calling `virsh`, `virt-install`, `qemu-img`, `ovs-vsctl`,
  `iptables`, `ip`, `brctl`, or any privileged tool directly.
- Reading or writing files under `/opt/xdr-lab/images/`,
  `/opt/xdr-lab/runtime/`, or `/opt/xdr-lab/logs/`.
- Embedding deployment heuristics ("if VM exists, skip" — that
  belongs in L2).

### 3.2 L2 — Runtime / Deployment

Owner directory: `packaging/opt/xdr-lab/scripts/`
Today: `xdr-lab-vm-manager.sh`.

Responsibilities:

- Own all virtualization primitives (`virsh`, `virt-install`,
  `qemu-img`).
- Own all OVS primitives (future, spec 007).
- Own all iptables primitives (future, spec 010).
- Read declarative state from L4.
- Read base images from L3.
- Materialize runtime state into L5.
- Emit structured logs to L6 (`log_structured`).

L2 is FORBIDDEN from:

- Reaching back into L1 (no Python imports of CLI helpers).
- Mutating `lab-vms.json` (config is operator-edited, not
  runtime-edited).
- Mutating `/opt/xdr-lab/images/<vm>/<base>.qcow2` after download
  (base images are immutable; only L5 runtime qcow2 may be mutated).
- Performing global destructive operations (constitution §11).

### 3.3 L3 — Image

Owner directory: `/opt/xdr-lab/images/`
Special: `/opt/xdr-lab/images/sensor/` for the sensor deploy script
and the sensor base qcow2 (spec 004).

Responsibilities:

- Holds the canonical downloaded base content per VM:
  `/opt/xdr-lab/images/<vm>/<disk_filename>`.
- Holds the sensor deploy script and sensor base image inside the
  sensor cache dir declared in `lab-vms.json`.

Properties:

- **Immutable after download**, until an explicit re-download.
- **Externally sourced**: URLs are declared in `lab-vms.json`; no
  qcow2 is shipped in the package (constitution P-1, P-4).

### 3.4 L4 — Configuration

Owner file: `/opt/xdr-lab/config/lab-vms.json`.

Responsibilities:

- Declare `schema_version`.
- Declare the lab network (`bridge`, `lab_subnet_cidr`, `gateway`,
  `dns`, `netmask`).
- Declare every VM by stable key (`sensor-vm`, `windows-victim`,
  `linux-server`, `test-vm1`, …) with: `type`, `image_url`,
  `bridge`, `cpu`, `memory_mb`, `disk_size_gb`, `internal_ip`,
  `external_nat_port_mapping`, `autostart`, and type-specific keys
  (`os_variant`, `disk_filename`, or for sensor: `hostname`,
  `virt_deploy_script_url`, `virt_deploy_script_name`,
  `sensor_cache_dir`).
- Declare `_future_capabilities` so reserved features have a known
  home.

Properties:

- **Single source of truth.** L1 and L2 both read from it; nothing
  else may.
- **Schema-versioned.** Breaking changes bump `schema_version`.

### 3.5 L5 — Runtime state

Owner directory: `/opt/xdr-lab/runtime/`.

Responsibilities:

- Per-VM runtime qcow2 (`<vm>-runtime.qcow2`) copied from the L3
  base image, resized to `disk_size_gb`.
- Future per-VM scenario state, snapshot metadata sidecars
  (spec 009).

Properties:

- **Ephemeral.** Can be deleted to force a clean redeploy. The base
  image in L3 is untouched.
- **Per-VM scoped.** No shared mutable state across VMs.

### 3.6 L6 — Logging

Owner directory: `/opt/xdr-lab/logs/`.

Responsibilities:

- `vm-manager.log` — structured JSON lines from L2
  (`xdr-lab-vm-manager.sh::log_structured`).
- Future siblings: `ovs-manager.log`, `nat-manager.log`,
  `snapshot-manager.log`, `scenario-runner.log`.
- L1 writes structured logs to stderr; the operator's `journald` or
  log shipper collects them.

Detailed rules: spec 012.

### 3.7 L7 — Network

The internal lab network is a single **Open vSwitch bridge `br0`**
with subnet `10.10.10.0/24`, attached using the **OVS-backed libvirt
network `ovs-net`** and `<virtualport type='openvswitch'/>`. OVS
mirror semantics on `br0`, reverse-NAT semantics, and VM connectivity
rules are owned by specs 006, 007, and 010.

## 4. Operational Assumptions

- The appliance runs Ubuntu 24.04 with nested virtualization enabled
  on an ESXi host. `kvm-ok` returns success.
- The appliance has external network access for image downloads at
  deploy time (or has pre-warmed caches and runs with
  `--nodownload`).
- The operator account can run `virsh`, `virt-install`, `qemu-img`,
  `ovs-vsctl`, and `iptables` (membership in `libvirt`, `kvm`,
  `sudo` groups, or equivalent privileged context).
- `/opt/xdr-lab/` is writable by the operator account and is the
  ONLY directory the appliance mutates outside of its CLI's runtime
  state.

## 5. Runtime Flow (canonical)

Example: `aella_cli lab deploy windows-victim`.

```
operator → aella_cli lab deploy windows-victim
        L1: _build_parser() → cmd_lab_deploy
        L1: _validate_lab_vm("windows-victim", allow_all=True)
        L1: _require_lab_manager()
        L1: shell_cmd_exec([LAB_MANAGER, "deploy", "windows-victim"])
                 │
                 ▼
        L2: xdr-lab-vm-manager.sh deploy windows-victim
        L2:   reads L4 lab-vms.json
        L2:   reads L3 /opt/xdr-lab/images/windows-victim/<file>.qcow2
        L2:   if base missing → die (structured error)
        L2:   materializes L5 /opt/xdr-lab/runtime/windows-victim-runtime.qcow2
        L2:   qemu-img resize to disk_size_gb
        L2:   if domain exists (virsh dominfo) → idempotent no-op + autostart
        L2:   else virt-install --import (bridge=br0, model=virtio, …)
        L2:   logs each step to L6 /opt/xdr-lab/logs/vm-manager.log
        L1: propagates rc / out / err to operator
        L1: structured "command_exit" log on stderr
```

## 6. Failure Handling Philosophy

- Every L1 handler MUST surface the runtime's stdout/stderr to the
  operator and propagate the exit code (`_emit_streams`).
- Every L2 failure MUST be **fatal at the point of detection** with
  `die`, producing a structured log line first. L2 never
  "best-effort" continues a deploy whose preconditions failed.
- Batch (`<action> all`) operations MUST iterate per VM and SHOULD
  continue past per-VM failures with `WARN`-level structured logs,
  but MUST NOT silently lose error context.
- L1 MUST translate `RuntimeError` from `shell_cmd_exec(check=True)`
  into a process exit code, with a structured log of
  `handler_runtime_error`.

## 7. Recovery Philosophy

- L1 has no state to recover; it can be reinstalled at any time
  without touching L2/L3/L4/L5/L6.
- L2 is idempotent (M-5); rerunning recovers from partial state.
- L5 is the recovery surface for VM-level corruption (delete file,
  redeploy).
- L4 is the recovery surface for configuration drift (operator
  edits, re-runs `deploy`).
- L3 is the recovery surface for image corruption (re-run
  `download <vm>`).

## 8. Future Extensibility Guidance

- New verbs (`mirror`, `snapshot`, `nat`, `scenario`) are added to
  L1 as new top-level subparsers under `aella_cli`, each delegating
  to a dedicated L2 script.
- New L2 scripts MUST live under `/opt/xdr-lab/scripts/` and MUST
  follow the same patterns as `xdr-lab-vm-manager.sh`:
  - `set -euo pipefail`
  - `log_structured` helper to L6
  - `die` helper
  - `require_cmd` precondition checks
  - declarative reads from L4
- New L4 fields MUST be additive and MUST come with a
  `schema_version` bump when their semantics break older readers.

## 9. Forbidden Implementation Patterns

- Putting `virsh`/`virt-install`/`qemu-img`/`ovs-vsctl`/`iptables`
  calls inside Python (constitution P-2).
- Storing operator state inside L1 (no caches in `~/.aella_cli/`,
  no sqlite, no pickles).
- Bidirectional dependencies (L2 importing from L1, or L4 being
  rewritten by L2 in normal operation).
- A "monolithic" L2 script that absorbs OVS, NAT, snapshot, and
  scenario responsibilities. Each future capability is its own
  script.
- Hard-coding paths different from `/opt/xdr-lab/{config,images,
  runtime,logs,scripts}` anywhere in L1 or L2.

## 10. Validation Philosophy

A change to the architecture is valid only if, after the change:

1. L1 still contains zero virtualization primitives.
2. L2 still emits structured logs for every external command.
3. L4 remains the only declarative source consulted by L1 and L2.
4. L3 / L5 / L6 directories are still untouched by L1.
5. `aella_cli --help` still shows the documented command tree
   (additive growth allowed).
6. `setup.py` entrypoint still resolves to
   `appliance_cli:main` (root single-file module installed via
   `py_modules=["appliance_cli"]`). The reference tree under
   `src/stellar_appliance_cli/` is NOT installed and is NOT
   the source of truth.

If any of (1)–(6) is no longer true, the change MUST be reverted or
the constitution MUST be amended.
