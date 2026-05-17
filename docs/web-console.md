# Windows VM Web Console (noVNC + websockify)

Optional **management access** for Windows lab VMs. This path is separate from
the Reverse-NAT / iptables DNAT contract (SSH, RDP). QEMU VNC stays bound to
`127.0.0.1`; only **websockify** exposes a browser UI on the host.

## Architecture

```
Browser  →  host:6081|6082 (websockify, 0.0.0.0)  →  127.0.0.1:5901|5902 (QEMU VNC)
```

| Layer | Bind | Role |
| --- | --- | --- |
| QEMU VNC | `127.0.0.1:5900+N` | Libvirt graphic console (not exposed externally) |
| websockify | `XDR_LAB_WEB_CONSOLE_BIND` (default `0.0.0.0`) | WebSocket proxy + static noVNC UI |
| noVNC | served under `${XDR_RUNTIME_DIR}/web-console/www/` | Browser UI (`/` → `vnc.html`) |

Constraints (by design):

- **No nginx/apache** — websockify serves noVNC directly.
- **No iptables DNAT** for web console — not part of `nat_state.py` authoritative DNAT table.
- **Per-VM manifests** — `${XDR_RUNTIME_DIR}/web-console/<vm>.json` (PID, ports, target).
- **Per-VM listen ports** — optional `XDR_LAB_WEB_CONSOLE_PORT_MAP`.

## Recommended port map

Set in `config/paths.sh` or the environment before starting consoles:

```bash
export XDR_LAB_WEB_CONSOLE_PORT_MAP="windows-build=6081,windows-victim=6082"
```

| VM | websockify (host) | QEMU VNC (localhost) | Browser URL (on appliance) |
| --- | --- | --- | --- |
| `windows-build` | TCP **6081** | `127.0.0.1:5901` (display `:1`) | `http://127.0.0.1:6081/` |
| `windows-victim` | TCP **6082** | `127.0.0.1:5902` (display `:2`) | `http://127.0.0.1:6082/` |

From another machine, use the host's external IPv4 (same ports):

```text
http://<EXT>:6081/   # windows-build
http://<EXT>:6082/   # windows-victim
```

`XDR_LAB_WEB_CONSOLE_PORT` (default **6080**) applies only to VMs **not** listed in
`PORT_MAP`.

## Operator commands

Install host packages once (root):

```bash
sudo installer/lab-host-web-console-deps.sh
```

Start / check / verify (per VM):

```bash
aella_cli lab web-console start windows-build
aella_cli lab web-console start windows-victim
aella_cli lab web-console status windows-victim
aella_cli lab web-console verify windows-victim
```

Equivalent:

```bash
bash scripts/xdr-lab-vm-manager.sh web-console start windows-victim
bash scripts/xdr-lab-vm-manager.sh windows-console windows-victim
```

## Runtime manifest

Path: `${XDR_RUNTIME_DIR}/web-console/<vm>.json`

Example (`windows-victim` on port 6082):

```json
{
  "vm": "windows-victim",
  "websockify_pid": 12345,
  "listen_bind": "0.0.0.0",
  "listen_port": 6082,
  "target_host": "127.0.0.1",
  "target_port": 5902,
  "vnc_display": ":2",
  "webroot": "/opt/xdr-lab/runtime/web-console/www",
  "started_at": "2026-05-13T12:00:00Z",
  "verify_ok": true,
  "verify_reasons": []
}
```

Each VM has its **own** manifest and **own** websockify PID.

## Validation

Web console is **not** part of the iptables Reverse-NAT contract checked by
`validate-host-network.sh` (`nat_state.py verify --iptables-only`).

| Check | Command |
| --- | --- |
| Per-VM wiring | `aella_cli lab web-console verify <vm>` |
| Aggregate (optional) | `${XDR_ROOT}/bootstrap/validate-web-console.sh` |
| Appliance bundle | `${XDR_ROOT}/bootstrap/validate-appliance.sh --strict` (fails if web console down) |

`nat verify` (full, without `--iptables-only`) may still record web-console listener
state in `nat.json` for observability; treat it as **optional management**, not
core lab egress/DNAT.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `XDR_LAB_WEB_CONSOLE_DIR` | `${XDR_RUNTIME_DIR}/web-console` | Manifests + `www/` webroot |
| `XDR_LAB_WEB_CONSOLE_BIND` | `0.0.0.0` | websockify listen address |
| `XDR_LAB_WEB_CONSOLE_PORT` | `6080` | Fallback port (unmapped VMs) |
| `XDR_LAB_WEB_CONSOLE_PORT_MAP` | *(empty)* | Per-VM ports, e.g. `windows-build=6081,windows-victim=6082` |
| `XDR_LAB_NAT_WEB_CONSOLE_VM` | `windows-victim` | VM referenced in `nat.json` when no `PORT_MAP` |

## Related files

- `scripts/vnc_proxy_helpers.sh` — start/stop/status/verify, manifest I/O
- `scripts/xdr-lab-vm-manager.sh` — CLI dispatch (`web-console`, `windows-console`)
- `installer/lab-host-web-console-deps.sh` — `novnc`, `websockify`, `socat`
- `docs/specs/010-reverse-nat-policy/spec.md` — core DNAT vs optional web console
- `docs/windows-golden-image.md` §18 — golden-image noVNC checklist
