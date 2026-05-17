# Windows Golden Image — operator verification checklist

> Use before and after Sysprep / qcow2 capture for integrated validation.  
> Related docs: `docs/windows-golden-image.md`, `docs/windows-sysprep-guide.md`, `docs/windows-capture-qcow2.md`, `docs/caldera-integration.md`

---

## Access / remote management

- [ ] **RDP works** — Successful 3389 session via internal IP or Reverse NAT port  
- [ ] **OpenSSH works** — `ssh` login with local admin or lab account  
- [ ] **WinRM works** — `winrs` or remote PowerShell session (auth per environment)  
- [ ] **PowerShell execution policy configured** — Matches lab standard (e.g. `RemoteSigned`)

---

## Security / logging

- [ ] **Windows Defender enabled** — Real-time protection on; policy matches intent  
- [ ] **Sysmon logging works** — Events flowing to `Microsoft-Windows-Sysmon/Operational`

---

## CALDERA / scenarios

- [ ] **CALDERA agent beacon visible** — After `bootstrap-windows.ps1`, confirm agent in UI/REST  
- [ ] **Event logs generated** — Evidence before/after scenarios in Security / Sysmon / PowerShell, etc.

---

## Infrastructure / console / network

- [ ] **noVNC console works** — `PORT_MAP=windows-build=6081,windows-victim=6082`; verify `http://127.0.0.1:6081/` and `6082/` after `lab web-console start`  
- [ ] **Reverse NAT works** — DNAT path for declared RDP/WinRM ports from outside (`docs/skills/reverse-nat-skill.md`)  
- [ ] **Browser installed** — Edge plus additional browser per policy  
- [ ] **Web download test works** — HTTP(S) smoke download to CALDERA/lab-allowed URL  
- [ ] **SMB reachable** — If SMB enabled: access `\\host\XdrLabPublic` etc. from another host on lab subnet

---

## Image lifecycle

- [ ] **Snapshot create/revert works** — Create baseline snapshot and verify revert  
- [ ] **Sysprep completed** — `sysprep /generalize /oobe /shutdown` (or equivalent GUI) succeeds; no log anomalies  
- [ ] **qcow2 exported** — `qemu-img convert`, optional zstd, sha256, update `images-manifest.json`

---

## Optional

- [ ] **(Optional) Atomic Red Team** — Sample `Invoke-AtomicTest` run after install and correlate logs

---

After completing checks, record **build ID, owner, and date** in a changelog or internal wiki.
