# Detection Scenario Platform — Detection Catalog

**문서 버전:** 0.1.0 (Phase 0.1)  
**상태:** Catalog only — **구현 금지**  
**목적:** Scenario ↔ Detection Model ↔ Vendor 매핑의 중앙 레지스트리

---

## 1. How to Read This Catalog

| Column | Meaning |
|--------|---------|
| **Scenario** | DSP traffic/behavior plugin ID (`scenarios/<id>/`) |
| **Target Detection** | Vendor/SIEM에서 기대하는 탐지 use case 이름 |
| **Vendor** | 제품 또는 플랫폼 |
| **Status** | `validated` · `planned` · `candidate` · `retired` |
| **Priority** | P0 (MVP) · P1 · P2 · P3 |
| **Difficulty** | `low` · `medium` · `high` — 구현·운영 복잡도 |
| **Expected Signal Type** | NDR · EDR · SIEM · WAF · DNS · Identity · … |

**중요:** Scenario(트래픽 생성) ≠ Detection Model(탐지 확인). 매핑은 1:N — 하나의 Scenario가 여러 Vendor detection에 대응할 수 있다.

---

## 2. Architecture Relationship

```
Scenario Plugin          Detection Catalog (this doc)       Detection Adapter (future)
─────────────────        ───────────────────────────        ──────────────────────────
dns_tunnel        ───►   Stellar DNS Tunnel          ───►   stellar.poll()
                  ───►   Splunk DNS Exfil            ───►   splunk.search()
                  ───►   Defender DNS Anomaly        ───►   defender.poll()
```

Catalog 변경은 **문서만** — 코드 등록은 Phase 3+ adapter 구현 시 참조.

---

## 3. Current Scenarios (MVP)

### 3.1 DNS Tunnel

| Scenario | Target Detection | Vendor | Status | Priority | Difficulty | Expected Signal Type |
|----------|------------------|--------|--------|----------|------------|-------------------|
| `dns_tunnel` | DNS Tunnel — idx-pattern exfil | Stellar Cyber (Stellar) | validated | P0 | medium | NDR, DNS |
| `dns_tunnel` | DNS Tunnel / DNS Exfiltration | Splunk (ES/UCE) | planned | P1 | medium | SIEM, DNS |
| `dns_tunnel` | DNS tunneling / anomalous DNS queries | Microsoft Defender for Endpoint | candidate | P2 | medium | EDR, DNS |
| `dns_tunnel` | DNS exfiltration use case | Elastic Security | candidate | P2 | medium | SIEM, NDR |
| `dns_tunnel` | DNS anomaly — long subdomain labels | Darktrace | candidate | P3 | high | NDR |
| `dns_tunnel` | DNS tunnel detection | QRadar | candidate | P3 | medium | SIEM |

**Traffic pattern:** `idx-{seq:06d}-{b32}.domain`, UDP/53, response optional  
**Validation metric:** `query_sent >= 1`, `idx_pattern_ratio >= 0.8`

---

### 3.2 DGA

| Scenario | Target Detection | Vendor | Status | Priority | Difficulty | Expected Signal Type |
|----------|------------------|--------|--------|----------|------------|-------------------|
| `dga` | DGA — NX + resolvable same eTLD | Stellar Cyber | validated | P0 | medium | NDR, DNS |
| `dga` | DGA domain activity | Microsoft Defender | candidate | P2 | medium | EDR, DNS |
| `dga` | DGA / algorithmically generated domains | Splunk | planned | P1 | medium | SIEM |
| `dga` | DGA — rare domain lookups | SentinelOne | candidate | P2 | medium | EDR |
| `dga` | DNS DGA | Elastic | candidate | P2 | medium | SIEM |

**Traffic pattern:** `*.xdr.ooo` NXDOMAIN + `*.live.xdr.ooo` resolvable  
**Validation metric:** `nxdomain >= 300`, `resolvable >= 10`, `base_domain == xdr.ooo`

---

### 3.3 HTTP Follow-up

| Scenario | Target Detection | Vendor | Status | Priority | Difficulty | Expected Signal Type |
|----------|------------------|--------|--------|----------|------------|-------------------|
| `http_followup` | Web scanning / suspicious URL access | Stellar Cyber | validated | P0 | low | NDR, WAF |
| `http_followup` | Web vulnerability scan | Splunk | planned | P1 | low | SIEM, WAF |
| `http_followup` | Suspicious web connection | Microsoft Defender | candidate | P2 | low | EDR, NDR |
| `http_followup` | Unusual web request patterns | Darktrace | candidate | P3 | medium | NDR |

**Traffic pattern:** ports 443/8443/80/8080/8000, fixed path list, ≤20 requests  
**Validation metric:** `attempted >= 1`, `responses >= 1`

---

### 3.4 SSH Login Failure

| Scenario | Target Detection | Vendor | Status | Priority | Difficulty | Expected Signal Type |
|----------|------------------|--------|--------|----------|------------|-------------------|
| `ssh_failure` | SSH brute force / auth failure burst | Stellar Cyber | planned | P1 | low | NDR, Identity |
| `ssh_failure` | Multiple failed SSH logins | Splunk | planned | P1 | low | SIEM |
| `ssh_failure` | SSH brute force detection | Microsoft Defender | candidate | P2 | medium | EDR |
| `ssh_failure` | Failed authentication — SSH | SentinelOne | candidate | P2 | low | EDR |
| `ssh_failure` | SSH login failure anomaly | QRadar | candidate | P3 | low | SIEM |

**Traffic pattern:** `invaliduser@`, BatchMode, no password auth  
**Validation metric:** `auth_attempted >= 1`

---

### 3.5 SQL Injection Simulation

| Scenario | Target Detection | Vendor | Status | Priority | Difficulty | Expected Signal Type |
|----------|------------------|--------|--------|----------|------------|-------------------|
| `sql_injection` | SQL injection attempt (HTTP) | Stellar Cyber | planned | P0 | low | WAF, NDR |
| `sql_injection` | SQLi — web application attack | Splunk | planned | P1 | low | SIEM, WAF |
| `sql_injection` | Web exploit / SQL injection | Microsoft Defender | candidate | P2 | medium | EDR, WAF |
| `sql_injection` | SQL injection signature | ModSecurity / WAF | candidate | P1 | low | WAF |

**Traffic pattern:** `?id=1' OR '1'='1`, `UNION SELECT`, GET primary  
**Validation metric:** `injection_request_sent >= 1`

---

## 4. Future Scenarios (Candidates)

구현하지 않음 — Catalog 등록만.

### 4.1 Network / Identity

| Scenario | Target Detection | Vendor | Status | Priority | Difficulty | Expected Signal Type |
|----------|------------------|--------|--------|----------|------------|-------------------|
| `smb_login_failure` | SMB brute force / bad auth | Stellar, Splunk | candidate | P1 | medium | NDR, Identity |
| `rdp_login_failure` | RDP brute force | Microsoft Defender, Splunk | candidate | P1 | medium | NDR, Identity |
| `kerberos_auth_failure` | Kerberos pre-auth failure burst | Microsoft Defender, QRadar | candidate | P2 | high | Identity, SIEM |
| `ldap_enumeration` | LDAP anonymous/bind enumeration | Stellar, Elastic | candidate | P2 | medium | NDR, Identity |
| `port_sweep` | Internal port scan / sweep | Stellar, Darktrace | candidate | P1 | low | NDR |
| `internal_recon` | Host discovery + service enum composite | Stellar, Splunk | candidate | P2 | medium | NDR, EDR |

### 4.2 DNS / Exfil

| Scenario | Target Detection | Vendor | Status | Priority | Difficulty | Expected Signal Type |
|----------|------------------|--------|--------|----------|------------|-------------------|
| `dns_txt_exfil` | DNS TXT exfiltration | Stellar, Splunk | candidate | P2 | medium | NDR, DNS |
| `dns_new_tld` | Newly registered TLD lookups | Stellar | candidate | P2 | low | NDR, DNS |

### 4.3 Web / C2

| Scenario | Target Detection | Vendor | Status | Priority | Difficulty | Expected Signal Type |
|----------|------------------|--------|--------|----------|------------|-------------------|
| `webshell_callback` | Outbound callback / beacon | Stellar, Defender | candidate | P2 | high | NDR, EDR |
| `http_beacon_interval` | Periodic HTTP beacon | Darktrace, Splunk | candidate | P3 | high | NDR |
| `suspicious_user_agent` | Anomalous User-Agent scanning | WAF, Stellar | candidate | P2 | low | WAF, NDR |

### 4.4 Endpoint (Safe)

| Scenario | Target Detection | Vendor | Status | Priority | Difficulty | Expected Signal Type |
|----------|------------------|--------|--------|----------|------------|-------------------|
| `eicar_file_create` | AV static signature (no execute) | EDR vendors | candidate | P2 | low | EDR |
| `process_spawn_chain` | Suspicious parent-child (benign binary) | Defender, SentinelOne | candidate | P3 | high | EDR |

### 4.5 Retired / Explicitly Excluded

| Scenario | Reason | Status |
|----------|--------|--------|
| `icmp_tunnel` | Legacy zero-event failure, not viable | retired |
| `dns_visibility_gate` | dig/nslookup preflight blocker — not a scenario | retired |
| `entropy_only_dga` | Replaced by `dga` 2-phase model | retired |

---

## 5. Vendor Coverage Matrix (Summary)

| Vendor | Validated Scenarios | Planned | Candidate Total |
|--------|---------------------|---------|-----------------|
| Stellar Cyber | dns_tunnel, dga, http_followup | ssh_failure, sql_injection | 15+ |
| Splunk | — | dns_tunnel, dga, http, ssh, sql_injection | 12+ |
| Microsoft Defender | — | — | 10+ |
| SentinelOne | — | — | 5+ |
| Elastic | — | — | 5+ |
| Darktrace | — | — | 4+ |
| QRadar | — | — | 4+ |

---

## 6. Catalog Maintenance Rules

1. **새 Scenario 추가** — `DETECTION_CATALOG.md`에 행 추가 + `scenarios/<id>/manifest.yaml` (Phase 1+)
2. **새 Vendor adapter** — Catalog에 detection mapping 추가, adapter는 `adapters/<vendor>/` (Phase 3+)
3. **Status 전환** — `candidate` → `planned` → `validated` (live lab 증거 후)
4. **코어 수정 불필요** — Catalog는 문서; 50 시나리오는 50 plugin folder
5. **Detection ≠ Traffic success** — Catalog의 Vendor column은 **confirmation target**, traffic validation은 Event Store

---

## 7. Priority Roadmap (Scenario Implementation)

| Phase | Scenarios | Count |
|-------|-----------|-------|
| Phase 1 | dns_tunnel | 1 |
| Phase 2 | dga, http_followup | +2 |
| Phase 3 | ssh_failure, sql_injection | +2 |
| Phase 4+ | smb_login_failure, port_sweep, ldap_enumeration, … | +N (from §4) |

**3년 목표:** 30–50 scenarios in Catalog, 10–15 `validated`, adapters for 3+ vendors.

---

## 8. Related Documents

- [ARCHITECTURE_SPEC.md](./ARCHITECTURE_SPEC.md) — §16 Scenario vs Detection Model
- [SCENARIO_FRAMEWORK_SPEC.md](./SCENARIO_FRAMEWORK_SPEC.md)
- [DETECTION_CATALOG.md](./DETECTION_CATALOG.md) — this file
- [docs/adr/0003-scenario-plugin-architecture.md](./docs/adr/0003-scenario-plugin-architecture.md)
