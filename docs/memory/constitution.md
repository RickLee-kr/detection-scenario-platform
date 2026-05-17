# XDR Lab Appliance — Project Constitution

> Document type: **Constitution (binding governance)**
> Scope: **All code, scripts, packaging, configuration, and operational
> procedures of the XDR Lab Appliance platform.**
> Status: **Authoritative.** Every specification under `.specify/specs/`
> and every skill under `skills/` derives from, and MUST remain consistent
> with, the rules below. If a future specification, implementation, or
> patch conflicts with this constitution, the constitution wins and the
> conflicting change MUST be revised or rejected.

---

## 0. Reading Guide

- The keywords **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and
  **MAY** are used in the sense of RFC 2119.
- Rules in **Section 10 (Mandatory Rules)** and
  **Section 11 (Prohibited Patterns)** are non-negotiable; they may only
  be modified by an explicit constitutional amendment that updates this
  file.
- All other sections describe the philosophy that those rules enforce.

---

## 1. Project Purpose

The XDR Lab Appliance is a **reproducible KVM-based XDR/NDR lab
platform** that runs on Ubuntu 24.04 (nested on ESXi) and provides:

- A controlled internal lab network for sensor, victim, and attacker VMs.
- A sensor VM (NDR/XDR sensor under test) deployed via a dedicated
  modular deploy script (`virt_deploy_modular_ds.sh`).
- Windows/Linux attack simulation and victim VMs.
- Open vSwitch (OVS) based mirror/tap of internal traffic to the sensor.
- Reverse NAT exposure from the appliance's external interface into the
  internal lab subnet for operator access.
- A future-extensible framework for BAS (Breach & Attack Simulation),
  Caldera, Atomic Red Team, Sliver, Mythic, and similar scenario engines.
- Snapshot/revert workflows so destructive scenarios can be replayed.
- An **appliance-style CLI** (`aella_cli`) that orchestrates the above
  without itself containing virtualization logic.

The appliance is intentionally shipped as an **appliance**, not as a
toolbox: an operator who installs the package MUST be able to use the
lab without learning libvirt, OVS, or iptables internals.

---

## 2. Architecture Philosophy

The platform is layered, and the layers MUST stay decoupled:

1. **CLI / Orchestration layer** — `aella_cli` (Python).
   Validates arguments, emits structured logs, and delegates work to the
   runtime layer.
2. **Runtime / Deployment layer** — shell entrypoints under
   `/opt/xdr-lab/scripts/` (today: `xdr-lab-vm-manager.sh`).
   Owns all `virsh`, `virt-install`, `qemu-img`, `ovs-vsctl`,
   `iptables`, and sensor-specific deploy invocations.
3. **Image layer** — `/opt/xdr-lab/images/` and the sensor cache dir.
   Stores externally-downloaded qcow2 images and the sensor deploy
   script. Treated as **content**, never as code shipped in the package.
4. **Runtime state layer** — `/opt/xdr-lab/runtime/`.
   Stores per-VM runtime qcow2 disks and other ephemeral state that may
   be regenerated from images + config.
5. **Configuration layer** — `/opt/xdr-lab/config/lab-vms.json` and
   sibling files. Single source of truth for VM identity, network
   parameters, NAT mappings, and feature flags.
6. **Logging layer** — `/opt/xdr-lab/logs/`. Structured (JSON-lines)
   logs produced by both Python and shell layers.
7. **Network layer** — `br0` (authoritative **Open vSwitch** internal
   bridge, `10.10.10.0/24`, OVS-backed libvirt **`ovs-net`** with
   **openvswitch virtualport**), OVS mirror plane on `br0`, and
   reverse-NAT iptables chains.

A change that blurs these boundaries (for example, putting `virsh`
calls into Python, or shipping qcow2 inside the Python package) is a
constitutional violation regardless of how convenient it appears.

---

## 3. Runtime Separation Philosophy

`appliance_cli.py` is, and MUST remain, **orchestration-only**:

- It parses commands, validates inputs against the config, emits
  structured logs, and shells out via `shell_cmd_exec` to the runtime
  layer.
- It MUST NOT call `virsh`, `virt-install`, `qemu-img`, `ovs-vsctl`,
  `iptables`, `ip`, `brctl`, or any other virtualization/network
  primitive directly.
- It MUST NOT embed deploy logic, qcow2 mutation logic, or sensor
  install logic.

The runtime layer (`xdr-lab-vm-manager.sh` and future sibling scripts
such as an OVS mirror manager, a snapshot manager, a reverse-NAT
manager, and a scenario runner) owns those primitives. The CLI calls
them; the CLI does not replace them.

This rule exists so that the appliance can be debugged, audited, and
re-implemented one layer at a time without rewriting the operator-facing
contract.

---

## 4. Operational Safety Philosophy

The appliance is operated by humans on hardware (or nested ESXi) that
may also host unrelated workloads. Therefore:

- **No global destructive defaults.** No command shipped in the
  appliance may, in its default form, wipe `br0`, flush OVS, flush
  `iptables`, or undefine VMs outside the lab inventory.
- **Validate before mutate.** Every deploy, mirror, NAT, snapshot, or
  cleanup action MUST first verify that the targeted object is part of
  the declared lab inventory (config-driven) and that preconditions are
  met.
- **Confirm before destroy.** Destructive operator-facing actions
  (`destroy`, `revert-all`, future `reset`) MUST either be explicitly
  scoped to a single named VM or require an explicit confirmation flag.
- **Preserve the host.** No command may modify networking on the
  appliance's primary uplink in a way that could disconnect the
  operator (e.g. reconfiguring the ESXi-facing NIC).
- **Fail loudly, fail safely.** When a precondition is missing
  (e.g. missing qcow2, missing sensor script), the runtime MUST refuse
  to proceed and emit a structured error rather than improvising.

---

## 5. Idempotent Deployment Philosophy

Every deployment-class operation MUST be idempotent:

- Re-running `deploy <vm>` on an already-deployed VM MUST NOT recreate
  it; it MUST detect the existing domain via `virsh dominfo` (or
  equivalent) and either no-op or reconcile autostart / config drift
  in a non-destructive way.
- Re-running `download <vm>` MUST be safe to repeat; the runtime
  SHOULD use cache-friendly download semantics and MUST NOT corrupt a
  previously valid image on transient network failure.
- Re-running `start`/`stop` MUST tolerate the VM already being in the
  target state.
- Bulk operations (`<action> all`) MUST iterate per-VM and continue
  past per-VM failures with structured logging, not abort the batch on
  first error unless the operator has explicitly opted into strict
  mode.

Idempotency is a property of the **runtime layer**, not the CLI; the
CLI MUST NOT add ad-hoc "skip if exists" logic of its own.

---

## 6. Recovery Philosophy

Failures are expected. The platform MUST be recoverable without
re-imaging the appliance:

- VM disk corruption MUST be recoverable by re-running `deploy` after
  removing the per-VM file under `/opt/xdr-lab/runtime/`. The base
  qcow2 in `/opt/xdr-lab/images/<vm>/` MUST NOT be mutated by deploy.
- Sensor recovery MUST be possible by re-downloading the sensor script
  and qcow2 into the sensor cache dir and re-running deploy with the
  documented flags.
- OVS mirror misconfiguration MUST be recoverable by a targeted,
  scoped mirror-clear (future spec 007) — NOT by `ovs-vsctl
  emer-reset` or by deleting `br0`.
- Reverse-NAT misconfiguration MUST be recoverable by removing only
  the lab-owned iptables rules — NOT by flushing the host firewall.
- Snapshot/revert operations MUST leave the VM in a defined libvirt
  state (running or shut off) and MUST log the transition.

Recovery procedures MUST be documented per spec and MUST be the only
sanctioned remediation paths.

---

## 7. Logging Philosophy

Structured logging is mandatory at every layer:

- The Python CLI emits JSON-lines structured records on stderr via the
  `aella_cli` logger and the `log_command` decorator. Every command
  handler MUST be wrapped with `@log_command`.
- The runtime layer emits JSON-lines records via `log_structured` into
  `/opt/xdr-lab/logs/vm-manager.log` (and future siblings).
- Every external command invocation MUST be logged before execution,
  and every failure MUST log return code and a bounded stderr preview.
- Logs MUST NOT contain plaintext secrets. Credentials, tokens, and
  guest passwords MUST be referenced indirectly (path, key id, or
  redacted token).
- Log shape SHOULD remain stable enough that a future SIEM export
  (spec 012) can ingest it without per-release schema changes.

Unstructured `print()` debug output is not acceptable in production
code paths.

---

## 8. Appliance Preservation Philosophy

The appliance contract is a **stable surface** for operators:

- The CLI is shipped as a **root single-file Python module**
  (`appliance_cli.py` at the project root). The entrypoint
  `aella_cli` (declared in `setup.py`) MUST continue to resolve
  to `appliance_cli:main` — that is, the `main` function in the
  flat top-level `appliance_cli` module installed via
  `py_modules=["appliance_cli"]`. The historical reference tree
  under `src/stellar_appliance_cli/` is **reference-only** and
  is NOT the authoritative source; any drift between it and the
  root `appliance_cli.py` is resolved in favor of the root
  module.
- The existing nested command structure (`appliance status`,
  `appliance info`, `lab deploy|download|start|stop|destroy|status`)
  MUST be preserved. New commands MUST be added as siblings; existing
  commands MUST NOT silently change semantics.
- The login-shell behavior of the appliance account MUST NOT be
  altered by this project. If a future scenario or feature requires
  shell customization, it MUST be additive and opt-in.
- Configuration backwards compatibility: `lab-vms.json` carries a
  `schema_version` field. Breaking changes to its shape MUST bump the
  version and the runtime MUST refuse unknown versions with a
  structured error.

---

## 9. Future Extensibility Philosophy

The platform anticipates future capabilities (OVS mirror automation,
snapshot management, reverse-NAT verification, BAS integration, EDR
agent deployment — see `_future_capabilities` in `lab-vms.json`).
These MUST be added as:

- **New runtime scripts** under `/opt/xdr-lab/scripts/`
  (e.g. `xdr-lab-ovs-manager.sh`, `xdr-lab-snapshot-manager.sh`,
  `xdr-lab-nat-manager.sh`, `xdr-lab-scenario-runner.sh`).
- **New nested CLI subcommands** under `aella_cli` (e.g.
  `aella_cli mirror …`, `aella_cli snapshot …`, `aella_cli nat …`,
  `aella_cli scenario …`) that delegate to those scripts via
  `shell_cmd_exec`.
- **New specs** under `.specify/specs/`. No runtime extension may be
  merged without an accompanying spec; no spec may be merged without
  pointing at the constitution clauses it implements.

The appliance MUST remain *additive over time*. Existing scripts and
commands MUST NOT be repurposed to host unrelated new behavior.

---

## 10. MANDATORY RULES

The following rules are binding on every contributor, every patch, and
every future automation:

- **M-1.** `appliance_cli.py` is orchestration-only and MUST stay so.
- **M-2.** All VM deployment logic MUST be externalized to the runtime
  layer under `/opt/xdr-lab/scripts/`.
- **M-3.** All qcow2 images MUST be downloaded externally at runtime;
  they are content, not code.
- **M-4.** VM images MUST NOT be embedded into Python packages, debian
  packages, or any release artifact.
- **M-5.** All deployment operations MUST be idempotent (see §5).
- **M-6.** Existing appliance functionality (CLI surface, entrypoint,
  config shape on a given `schema_version`) MUST be preserved.
- **M-7.** Deployment scripts MUST support rollback-safe execution:
  partial failures MUST be diagnosable and re-runnable.
- **M-8.** Structured logging is mandatory in both Python and shell
  layers (see §7).
- **M-9.** Runtime state separation is mandatory:
  `config/` is declarative, `images/` is immutable base content,
  `runtime/` is per-VM ephemeral state, `logs/` is append-only.
- **M-10.** `br0` is the authoritative internal lab **Open vSwitch**
  bridge. All lab VMs attach to `br0` via the **OVS-backed libvirt
  network** (`ovs-net`, `<virtualport type='openvswitch'/>`). Other
  bridges MAY exist for non-lab purposes but MUST NOT be silently reused.
- **M-11.** The internal lab subnet is fixed at `10.10.10.0/24` with
  gateway `10.10.10.1` and netmask `255.255.255.0`, as declared in
  `lab-vms.json`. Changes MUST go through a schema bump.
- **M-12.** The Sensor VM is a **special deployment type**: it is
  identified by `name == "sensor-vm"` or `type == "sensor"` in
  `lab-vms.json` and is deployed via a dedicated script, not via the
  generic `virt-install` path.
- **M-13.** Sensor deployment MUST use `virt_deploy_modular_ds.sh`
  delivered into the sensor cache dir (`/opt/xdr-lab/images/sensor/`)
  and invoked from that directory.
- **M-14.** OVS mirror operations MUST be **non-destructive**:
  incremental add/remove only, scoped to the lab's named mirror
  object.
- **M-15.** Snapshot/revert operations MUST preserve VM consistency
  (defined libvirt state before and after; documented disk format;
  no half-applied snapshots left behind).
- **M-16.** Cleanup operations MUST avoid destructive wildcard
  deletion. Cleanup targets MUST come from the declared lab inventory.
- **M-17.** **English-only operational platform policy.** All code,
  comments, CLI and help text, logs, JSONL events, runtime JSON
  **values** (human-readable messages, hints, summaries, operator
  workflows), documentation, scenario pack metadata
  (`display_name`, `description`, `expected_telemetry`, safety and
  cleanup notes), remediation strings, and telemetry checklist text
  MUST be authored and maintained in **English**. Korean or other
  non-English operational strings MUST NOT be introduced; mixed-language
  CLI output is forbidden. Existing JSON **keys** and stable identifiers
  MUST NOT be renamed when doing so would break compatibility; new
  fields MUST use English-only labels and values. Future contributions
  MUST preserve English-only consistency across the platform.

---

## 11. PROHIBITED PATTERNS

The following patterns are forbidden. A patch that introduces any of
them is a constitutional violation and MUST be rejected:

- **P-1.** Embedding qcow2 images (or any large binary VM artifact)
  into the Python package, the debian package, or any git tree.
- **P-2.** Implementing KVM/libvirt deployment logic directly inside
  `appliance_cli.py` (e.g. `subprocess` calls to `virt-install`,
  `virsh define`, `qemu-img create/resize` from Python).
- **P-3.** Destructive OVS reset operations such as
  `ovs-vsctl emer-reset`, `ovs-vsctl del-br br0`, or wholesale
  recreation of `br0`, in any code path shipped by this project.
- **P-4.** Automatic deletion of unknown VM images (anything under
  `/opt/xdr-lab/images/` or `/opt/xdr-lab/runtime/` that is not in
  the current `lab-vms.json` inventory).
- **P-5.** Direct modification of libvirt networks not owned by the
  lab (no `virsh net-destroy default` etc.); the lab attaches VM NICs to
  the Open vSwitch bridge `br0` through the documented **OVS-backed**
  libvirt network **`ovs-net`** (`<virtualport type='openvswitch'/>`).
  It does not commandeer unrelated libvirt-managed networks.
- **P-6.** Changing the appliance account's login-shell behavior
  (PAM, `/etc/passwd` shell, `.bashrc` rewriting, etc.).
- **P-7.** Changing `setup.py` entrypoint behavior — specifically,
  the `aella_cli` console-script MUST continue to point at
  `appliance_cli:main` (root single-file module). Repackaging
  the CLI as `stellar_appliance_cli.appliance_cli:main` (or any
  other dotted module path) is a violation of the appliance
  preservation philosophy unless the constitution is first
  amended.
- **P-8.** Storing credentials in plaintext anywhere in
  `lab-vms.json`, in shipped scripts, or in logs. Secrets MUST be
  injected at deploy time via the sensor deploy script or a future
  secrets channel.
- **P-9.** Forced `apt install` / `apt-get install` without explicit
  operator approval. Any automated package installation MUST be
  gated behind a flag and MUST log what it intends to install
  *before* it does so.
- **P-10.** Destructive `rm -rf` patterns. Specifically forbidden:
  `rm -rf /opt/xdr-lab`, `rm -rf $VAR/*` where `$VAR` is not known
  to be a lab-owned directory, and unquoted globs over paths that
  could ever be empty.
- **P-11.** Automatic recreation of `br0`. If `br0` is missing, the
  runtime MUST surface a structured error and stop; it MUST NOT
  silently create or reconfigure a bridge of the same name.
- **P-12.** Automatic modification of production-facing host
  interfaces (the ESXi-facing NIC, the operator's management
  interface). The lab plane is internal; it does not touch the
  uplink.
- **P-13.** Unsafe `iptables` flush operations:
  `iptables -F`, `iptables -X`, `iptables -t nat -F`,
  `iptables-restore < /dev/null`, etc. Reverse-NAT MUST manage only
  its own named chain (spec 010).
- **P-14.** Destructive `virsh undefine` loops over `virsh list
  --all` without first validating that each target name is part of
  the declared lab inventory. "Clean up everything" loops are
  forbidden.

---

## 12. Amendment Process

This constitution MAY only be changed by:

1. Updating this file in a single, dedicated commit.
2. Updating any spec that becomes inconsistent in the same change set.
3. Recording the rationale in the commit message and, where relevant,
   in `.specify/specs-index.md`.

No implementation patch may add a "temporary exception" to the rules
in §10 or §11. If a rule blocks a legitimate need, the rule itself
MUST be amended first.

---

## 13. Conformance Statement

All current artifacts in this repository are intended to conform to
this constitution as of its initial adoption:

- `appliance_cli.py` (project root, flat top-level module) —
  orchestration-only; uses `shell_cmd_exec` to delegate; wraps
  handlers in `@log_command`; validates VM names against
  `lab-vms.json`. This is the **authoritative** CLI source.
- `src/stellar_appliance_cli/appliance_cli.py` — **reference-only
  historical snapshot.** Not installed by `setup.py`, not driven
  by the `aella_cli` console-script, and not the place to make
  CLI changes. May be retained for traceability; MUST NOT be
  treated as the source of truth.
- `packaging/opt/xdr-lab/scripts/xdr-lab-vm-manager.sh` — owns
  `virsh`, `virt-install`, `qemu-img`, and the sensor deploy
  invocation; emits structured logs via `log_structured`.
- `packaging/opt/xdr-lab/config/lab-vms.json` — single declarative
  source for VMs, network, and reserved future capabilities.
- `setup.py` — `py_modules=["appliance_cli"]` with entrypoint
  `aella_cli` → `appliance_cli:main`.

Future contributions MUST preserve these properties.
