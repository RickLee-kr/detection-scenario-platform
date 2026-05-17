# XDR Lab — bootstrap scripts

Optional host and golden-image preparation scripts for the appliance, Windows lab images, **optional** MITRE CALDERA server install, Atomic Red Team checkout, and **host runtime validation / safe self-healing**.

Lab networking is **Open vSwitch `br0`** with libvirt **`ovs-net`** (`<virtualport type='openvswitch'/>`); see `docs/specs/006-network-architecture/spec.md`.

## Golden Image bootstrap (install once)

| Script | Target | Purpose |
| --- | --- | --- |
| `windows-bootstrap.ps1` | Windows golden image | RDP, OpenSSH, WinRM (HTTP), lab-standard access channels |
| `caldera-server-bootstrap.sh` | Ubuntu 24.04 (host or admin VM) | CALDERA git clone, Python venv, `conf/default.yml`, systemd unit |
| `atomic-red-team-linux.sh` | Linux server role | ART repo clone, safety readme, optional pwsh + Invoke-AtomicRedTeam |
| `atomic-red-team-windows.ps1` | Windows victim | ART clone, optional Invoke-AtomicRedTeam, Defender left enabled |

## Host runtime validation (RC / post-reboot)

Installed to `${XDR_ROOT}/bootstrap/` by `installer/cli-installer.sh`. **Read-only** except `fix-runtime-state.sh`.

| Script | Purpose |
| --- | --- |
| `validate-host-network.sh` | `br0` UP + `10.10.10.1/24`, OVS, `ovs-net`, `ip_forward`, MASQUERADE + reverse NAT contract |
| `validate-libvirt.sh` | `libvirtd`, `qemu:///system`, `ovs-net`, `virsh list` |
| `validate-caldera.sh` | CALDERA unit, venv, port listen, HTTP from localhost and lab gateway |
| `validate-web-console.sh` | Per-VM websockify/noVNC (`PORT_MAP` or default VM); skips stopped VMs |
| `validate-appliance.sh` | Aggregate host-network + CALDERA + libvirt (+ optional mirror + web console) |
| `ensure-caldera-runtime.sh` | Idempotent venv/requirements repair for CALDERA |
| `repair-caldera-service.sh` | Regenerate `caldera.service` to match runtime user and venv python |
| `deploy-caldera-runtime-fix.sh` | One-shot install scripts + ensure + repair + validate |
| `fix-runtime-state.sh` | Safe recovery: link up, restore gateway IP, `virsh net-start ovs-net`, restart `libvirtd` |

Operational console: `${XDR_ROOT}/xdr-lab.sh` (menu items 1–4 mirror the scripts above).

See `docs/operational-validation.md` for reboot persistence, failure analysis, and RC procedure.

CALDERA orchestration order, API keys, Sandcat deployment: `docs/caldera-integration.md`.
