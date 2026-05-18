# Windows VM Web Console (noVNC + websockify)

Optional **management access** for `windows-victim`. This path is separate from
the Reverse-NAT / iptables DNAT contract (SSH, RDP). QEMU VNC stays bound to
`127.0.0.1`; only **websockify** serves a browser UI. The default web console
bind is also localhost, so remote access should use SSH tunneling or ngrok.

## Architecture

```
Browser  →  127.0.0.1:6080 (websockify/noVNC)  →  127.0.0.1:5902 (QEMU VNC)
```

| Layer | Bind | Role |
| --- | --- | --- |
| QEMU VNC | `127.0.0.1:5902` (`display=:2`, `autoport=no`) | Libvirt graphic console (not exposed externally) |
| websockify | `XDR_LAB_WEB_CONSOLE_BIND` (default `127.0.0.1`) on port `6080` | WebSocket proxy + static noVNC UI |
| noVNC | served under `${XDR_RUNTIME_DIR}/web-console/www/` | Browser UI (`/` → `vnc.html`) |

Constraints (by design):

- **No nginx/apache** — websockify serves noVNC directly.
- **No iptables DNAT** for web console — not part of `nat_state.py` authoritative DNAT table.
- **Per-VM manifests** — `${XDR_RUNTIME_DIR}/web-console/<vm>.json` (PID, ports, target).
- **Fixed default ports** — `windows-victim` uses QEMU VNC `127.0.0.1:5902` and web console `127.0.0.1:6080`.

## Fixed Ports

Default contract:

| VM | websockify/noVNC | QEMU VNC target | Browser URL |
| --- | --- | --- | --- |
| `windows-victim` | `127.0.0.1:6080` | `127.0.0.1:5902` (display `:2`) | `http://127.0.0.1:6080/vnc.html` |

`XDR_LAB_WEB_CONSOLE_BIND=0.0.0.0` is supported for deliberate off-host
exposure, but the recommended default is `127.0.0.1` with a tunnel.

SSH tunnel example:

```bash
ssh -p 17859 -L 6080:127.0.0.1:6080 aella@0.tcp.ap.ngrok.io
```

Browser:

```text
http://127.0.0.1:6080/vnc.html
```

## Operator commands

Install host packages once (root):

```bash
sudo installer/lab-host-web-console-deps.sh
```

Start / check / enable / verify:

```bash
aella_cli lab web-console enable windows-victim
aella_cli lab web-console start windows-victim
aella_cli lab web-console status windows-victim
aella_cli lab web-console stop windows-victim
aella_cli lab web-console disable windows-victim
aella_cli lab web-console verify windows-victim
```

Equivalent:

```bash
bash scripts/xdr-lab-vm-manager.sh web-console start windows-victim
bash scripts/xdr-lab-vm-manager.sh windows-console windows-victim
```

## Runtime manifest

Path: `${XDR_RUNTIME_DIR}/web-console/<vm>.json`

Example (`windows-victim` on port 6080):

```json
{
  "vm": "windows-victim",
  "websockify_pid": 12345,
  "listen_bind": "127.0.0.1",
  "listen_port": 6080,
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
| Appliance bundle | `${XDR_ROOT}/bootstrap/validate-appliance.sh --strict` (reports web console as WARN if down; it does not gate core lab readiness) |

`nat verify` (full, without `--iptables-only`) may still record web-console listener
state in `nat.json` for observability; treat it as **optional management**, not
core lab egress/DNAT.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `XDR_LAB_WEB_CONSOLE_DIR` | `${XDR_RUNTIME_DIR}/web-console` | Manifests + `www/` webroot |
| `XDR_LAB_WEB_CONSOLE_BIND` | `127.0.0.1` | websockify listen address (`0.0.0.0` for explicit off-host exposure) |
| `XDR_LAB_WEB_CONSOLE_PORT` | `6080` | websockify/noVNC listen port |
| `XDR_LAB_WEB_CONSOLE_PORT_MAP` | *(empty)* | Optional per-VM port overrides for non-default labs |
| `XDR_LAB_WEB_CONSOLE_RETRY_SECS` | `10` | systemd service retry interval while the VM is stopped |
| `XDR_LAB_WINDOWS_VICTIM_VNC_PORT` | `5902` | fixed QEMU VNC TCP target for `windows-victim` |
| `XDR_LAB_NAT_WEB_CONSOLE_VM` | `windows-victim` | VM referenced in `nat.json` when no `PORT_MAP` |

## Related files

- `scripts/vnc_proxy_helpers.sh` — start/stop/status/verify, manifest I/O
- `scripts/xdr-lab-vm-manager.sh` — CLI dispatch (`web-console`, `windows-console`)
- `installer/xdr-lab-web-console@.service` — boot-time websockify/noVNC service template
- `installer/lab-host-web-console-deps.sh` — `novnc`, `websockify`, `socat`
- `docs/specs/010-reverse-nat-policy/spec.md` — core DNAT vs optional web console
- `docs/windows-golden-image.md` §18 — golden-image noVNC checklist
