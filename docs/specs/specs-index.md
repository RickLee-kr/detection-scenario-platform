# XDR Lab Appliance — Specifications Index

This index enumerates all specifications that govern the XDR Lab
Appliance platform. Every spec is **derived from and bound by**
`memory/constitution.md`. Implementation work MUST cite the
corresponding spec(s); spec work MUST cite the corresponding
constitution clauses.

## 0. Hierarchy

```
.specify/
├── memory/
│   └── constitution.md            ← top-level binding rules
├── specs-index.md                 ← this file
└── specs/
    ├── 001-core-architecture/spec.md
    ├── 002-kvm-runtime/spec.md
    ├── 003-vm-image-policy/spec.md
    ├── 004-sensor-deployment/spec.md
    ├── 005-cli-extension-policy/spec.md
    ├── 006-network-architecture/spec.md
    ├── 007-ovs-mirror-policy/spec.md
    ├── 008-scenario-framework/spec.md
    ├── 009-snapshot-runtime/spec.md
    ├── 010-reverse-nat-policy/spec.md
    ├── 011-operational-safety/spec.md
    └── 012-runtime-logging/spec.md
```

Companion operational memory for Cursor / contributor agents lives in
`skills/` at the repo root.

## 0.1 CLI Module Convention (cross-spec note)

The CLI is a **root single-file Python module**: `appliance_cli.py`
at the project root, installed via `py_modules=["appliance_cli"]`
and exposed by `setup.py` as the console-script
`aella_cli=appliance_cli:main`.

`src/stellar_appliance_cli/appliance_cli.py` is a **reference-only**
historical snapshot; it is NOT installed, NOT driven by
`aella_cli`, and NOT authoritative. Whenever a spec or skill says
"`appliance_cli.py`", it means the root single-file module unless
explicitly qualified otherwise.

## 0.2 Operator guides (non-governance)

These Markdown files are **operator runbooks** (release readiness,
checklists, recovery). They complement specs and `README.md` but are not
numbered specifications:

- `docs/deployment-readiness.md`
- `docs/environment-sanity-checklist.md`
- `docs/real-environment-bringup.md`
- `docs/release-candidate-checklist.md`
- `docs/runtime-smoke-validation.md`
- `docs/operational-recovery.md`
- `docs/operational-maintenance.md`
- `docs/packaging-guidance.md`
- `docs/caldera-integration.md`
- `docs/live-run-playbook.md`
- `docs/runtime-evidence-collection.md`
- `docs/runtime-state-inspection.md`
- `docs/operator-troubleshooting-matrix.md`

## 1. Spec Catalog

| ID  | Title                     | Concerns                                                       | Status   |
|-----|---------------------------|----------------------------------------------------------------|----------|
| 001 | Core Architecture         | Layering: CLI / runtime / image / config / network / logging  | Adopted  |
| 002 | KVM Runtime               | `virsh` / `virt-install` / `qemu-img` lifecycle                | Adopted  |
| 003 | VM Image Policy           | External download, caching, verification, versioning           | Adopted  |
| 004 | Sensor Deployment         | Sensor VM as a special deploy type via modular script          | Adopted  |
| 005 | CLI Extension Policy      | How new `aella_cli` subcommands MUST be added                  | Adopted  |
| 006 | Network Architecture      | `br0`, `10.10.10.0/24`, NAT, reverse-NAT plane                 | Adopted  |
| 007 | OVS Mirror Policy         | Non-destructive mirror of internal traffic to sensor port      | Adopted  |
| 008 | Scenario Framework        | BAS / Caldera / Atomic Red Team / Sliver / Mythic extensions   | Reserved |
| 009 | Snapshot Runtime          | Snapshot/revert lifecycle for replayable scenarios             | Reserved |
| 010 | Reverse NAT Policy        | iptables-based reverse NAT, lab-owned chain only               | Adopted  |
| 011 | Operational Safety        | Destructive-action prevention, confirmation, cleanup safety    | Adopted  |
| 012 | Runtime Logging           | Structured logging across Python and shell layers, SIEM export | Adopted  |

"Status" semantics:

- **Adopted**: governance is binding now; implementation MAY exist or
  is queued. Code MUST conform.
- **Reserved**: feature is acknowledged in
  `lab-vms.json._future_capabilities` and in this index. No runtime
  code is permitted yet; only the spec governs.

## 2. Cross-cutting Dependencies

```
constitution
   │
   ├── 001 core-architecture ───────────┬─── 005 cli-extension-policy
   │                                    │
   ├── 002 kvm-runtime ─── 003 vm-image-policy ─── 004 sensor-deployment
   │                                    │
   ├── 006 network-architecture ─── 007 ovs-mirror-policy
   │                                    │
   │                                    └── 010 reverse-nat-policy
   │
   ├── 009 snapshot-runtime ─── 008 scenario-framework
   │
   ├── 011 operational-safety   (cross-cuts ALL specs)
   │
   └── 012 runtime-logging      (cross-cuts ALL specs)
```

- Specs **011** and **012** are cross-cutting: every other spec MUST
  conform to their rules.
- Spec **008** depends on **009** (scenarios are useless without
  reliable revert).
- Spec **007** depends on **006** (mirror plane lives on the same
  `br0` and assumes the declared subnet).
- Spec **004** depends on **002** and **003** (sensor is a KVM
  deployment with an external image set).

## 3. Implementation Workflow

A future contributor or future Cursor task MUST:

1. Read `memory/constitution.md` first.
2. Read the spec(s) implicated by the change.
3. Read any relevant `skills/*.md` (operational memory).
4. Plan the change to live in the correct **layer** (CLI vs runtime
   vs image vs config).
5. Implement, ensuring:
   - Idempotency (M-5),
   - Structured logging (M-8, spec 012),
   - Inventory-scoped operations (M-16, spec 011),
   - No prohibited patterns (constitution §11).
6. Update the spec(s) **only if** governance itself changed. Routine
   implementation does not amend specs.
7. If a spec must change, also re-check whether the constitution
   needs amending (§12 of the constitution).

## 4. Document Conventions

- All governance documents are written in **English only**.
- All governance documents are **implementation-oriented**: they tell
  the future implementer what to do, what not to do, and how to
  verify.
- Every spec is a single file named `spec.md` inside its numbered
  directory. The directory name is the canonical id.
- Cross-references use the form `spec 0NN` (e.g. "spec 007") and
  refer to the directory id, not the file path.

## 5. Authoritative Source

If any external document (README, presentation, ticket) contradicts a
spec or the constitution, the documents under `.specify/` win.
