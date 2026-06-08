# Detection Gap Analysis — Phase 5.5

**문서 버전:** 1.0.0  
**상태:** Documentation only  
**목적:** 미구현 탐지 후보의 우선순위·근거·의존성 분석

---

## 1. Current Coverage Snapshot

| 영역 | 구현 시나리오 | 미구현 (Catalog 등재) |
|------|--------------|----------------------|
| DNS | `dns_tunnel`, `dga` | `dns_txt_exfil`, `dns_new_tld` |
| Web / HTTP | `http_followup` | `sql_injection`, `webshell_callback`, `http_beacon_interval` |
| Auth / Identity | `ssh_failure` | `smb_login_failure`, `rdp_login_failure`, `kerberos_auth_failure`, `ldap_enumeration` |
| Recon | (간접) | `port_sweep`, `internal_recon` |
| Endpoint | — | `eicar_file_create`, `process_spawn_chain` |
| Adapter | — | Detection Adapter Layer (전 벤더 S3) |

**핵심 격차:** Catalog MVP 5건 중 **1건만 미구현** (`sql_injection`).  
그러나 Catalog Future 15+건과 벤더 S3 확인은 **광범위한 격차**로 남음.

---

## 2. Gap Analysis — Requested Candidates

### 2.1 SQL Injection

| Attribute | Value |
|-----------|-------|
| **Priority** | **HIGH** |
| **Target Detection** | Stellar: SQL injection attempt (HTTP) · Splunk: SQLi web attack · Defender: Web exploit · WAF/ModSecurity |
| **Expected Signal** | GET query string payload (`?id=1' OR '1'='1`, `UNION SELECT`); HTTP anomaly; WAF block/alert |
| **Why Gap Matters** | Catalog **P0** 유일 미구현 MVP; HTTP Follow-up이 Web Exploit Recon을 **PARTIAL**만 커버; WAF/NDR Web 공격 축 공백 |
| **Implementation Readiness** | **HIGH** — `dsp/protocols/http/` 재사용, `send_request()` + crafted URLs |
| **Dependencies** | HTTP client, web target, optional WAF in path |
| **Risk** | Destructive SQL·data exfil 금지 (safety manifest) |
| **Estimated Effort** | Low (Phase 6 — HTTP Follow-up 패턴 복제) |

---

### 2.2 SMB Login Failure

| Attribute | Value |
|-----------|-------|
| **Priority** | **HIGH** |
| **Target Detection** | Stellar: SMB Recon / bad auth · Splunk: SMB brute force · Defender: SMB authentication failure |
| **Expected Signal** | TCP/445 연결; NTLM auth failure burst; Windows Identity analytics |
| **Why Gap Matters** | Identity 축이 SSH만으로는 불충분; 레거시 PoC `smb_hosts.txt`·Windows Telemetry stage와 정합 |
| **Implementation Readiness** | **MEDIUM** — `dsp/protocols/smb/` 신규; impacket 또는 safe stub 필요 |
| **Dependencies** | `windows_host`, SMB port 445 reachable, lab AD/SMB target |
| **Risk** | 실제 credential 사용 금지; account lockout 유발 방지 |
| **Estimated Effort** | Medium (Phase 7) |

---

### 2.3 LDAP Enumeration

| Attribute | Value |
|-----------|-------|
| **Priority** | **MEDIUM** |
| **Target Detection** | Stellar: AD Discovery / LDAP enumeration · Elastic: LDAP anonymous bind |
| **Expected Signal** | TCP/389·636; anonymous/bind enumeration; query burst |
| **Why Gap Matters** | Windows/AD lab의 Identity·Recon 커버; 레거시 Windows Telemetry stage 보완 |
| **Implementation Readiness** | **MEDIUM** — `dsp/protocols/ldap/` 신규 |
| **Dependencies** | `domain_controller`, `ldap_host`, AD lab topology |
| **Risk** | AD 변경·lockout 없는 read-only enumeration만 |
| **Estimated Effort** | Medium–High (Phase 8) |

---

### 2.4 Kerberos Failure

| Attribute | Value |
|-----------|-------|
| **Priority** | **MEDIUM** |
| **Target Detection** | Defender: Kerberos pre-auth failure · QRadar: Kerberos anomaly · Stellar: Kerberos Activity (failure subset) |
| **Expected Signal** | UDP/88 pre-auth failure burst; invalid principal; AS-REQ without valid key |
| **Why Gap Matters** | Enterprise Identity 탐지의 핵심; Defender/QRadar 차별화 |
| **Implementation Readiness** | **LOW–MEDIUM** — `dsp/protocols/kerberos/` 신규, crypto·AD 의존 |
| **Dependencies** | Domain Controller, Kerberos realm, Windows lab |
| **Risk** | 높음 — 잘못된 구현 시 DC 부하; strict volume cap 필요 |
| **Estimated Effort** | High (Phase 9) |

---

### 2.5 DNS TXT Exfil

| Attribute | Value |
|-----------|-------|
| **Priority** | **MEDIUM** |
| **Target Detection** | Stellar: DNS exfil variant · Splunk: DNS TXT exfiltration |
| **Expected Signal** | TXT record query/response with encoded payload; distinct from A-record idx tunnel |
| **Why Gap Matters** | `dns_tunnel`이 A-record idx 패턴만 커버; TXT 채널 탐지 모델 미검증 |
| **Implementation Readiness** | **HIGH** — `dsp/protocols/dns/` 확장, tunnel.py 패턴 재사용 |
| **Dependencies** | DNS resolver, optional authoritative DNS |
| **Risk** | Low — UDP query only, 기존 DNS safety 정책 적용 |
| **Estimated Effort** | Medium (DNS family Phase 4+ branch) |

---

### 2.6 Internal Recon

| Attribute | Value |
|-----------|-------|
| **Priority** | **MEDIUM** |
| **Target Detection** | Stellar: Host Reconnaissance / Discovery Activity · Splunk: Internal recon composite |
| **Expected Signal** | Host discovery + service enum + follow-up 접속 복합; MITRE T1046/T1018 |
| **Why Gap Matters** | HTTP Follow-up 단독은 Recon **PARTIAL**; 레거시 PoC는 Host/Network/Service Discovery 선행 |
| **Implementation Readiness** | **LOW** — composite scenario; Target Provider·다중 executor 조합 |
| **Dependencies** | `port_sweep`, target discovery, multi-protocol |
| **Risk** | Scope creep — "composite" 시나리오 프레임워크 검증 필요 |
| **Estimated Effort** | High (Phase 8+ 또는 port_sweep 이후) |

---

### 2.7 Port Sweep

| Attribute | Value |
|-----------|-------|
| **Priority** | **HIGH** |
| **Target Detection** | Stellar: Internal Port Scan / Service Discovery · Darktrace: Port scan · Splunk: Network scan |
| **Expected Signal** | TCP connect sweep across key ports; internal subnet; scan burst |
| **Why Gap Matters** | Recon 축의 atomic building block; HTTP/SSH follow-up의 선행 단계; Catalog P1 |
| **Implementation Readiness** | **HIGH** — `dsp/protocols/tcp/` 또는 nmap-safe wrapper |
| **Dependencies** | `alive_host`, target_net, rate limit |
| **Risk** | Lab noise·IDS saturation — volume cap·rate limit 필수 |
| **Estimated Effort** | Low–Medium (Phase 7–8, SMB와 병렬 가능) |

---

## 3. Priority Ranking Summary

| Priority | Scenario / Initiative | Rationale |
|----------|----------------------|-----------|
| **HIGH** | SQL Injection | MVP 마지막 1건; HTTP stack 재사용; WAF/NDR Web gap |
| **HIGH** | Port Sweep | Recon 기반; HTTP PARTIAL 보완; 구현 난이도 낮음 |
| **HIGH** | SMB Login Failure | Identity 2번째 프로토콜; Windows lab 필수 커버 |
| **MEDIUM** | LDAP Enumeration | AD lab Identity; SMB 이후 자연 확장 |
| **MEDIUM** | Kerberos Failure | 고가치이나 구현·운영 복잡도 높음 |
| **MEDIUM** | DNS TXT Exfil | DNS family 확장; tunnel과 상보 |
| **MEDIUM** | Internal Recon | Composite — atomic 시나리오 선행 후 |
| **LOW** | (Phase 10 이전) Adapter 없는 추가 시나리오만 무한 확장 | S3 확인 불가 반복 |

---

## 4. Gap by Vendor Priority

### Stellar (P0)

| Gap | Priority |
|-----|----------|
| SQL Injection | HIGH |
| SMB / Port Sweep | HIGH |
| DNS TXT Exfil | MEDIUM |

### Splunk (P1)

| Gap | Priority |
|-----|----------|
| SQL Injection | HIGH |
| Detection Adapter (S3 poll) | HIGH |
| SMB + SSH syslog correlation | MEDIUM |

### Defender / SentinelOne (P2)

| Gap | Priority |
|-----|----------|
| SQL Injection (EDR web) | HIGH |
| Kerberos / SMB (Identity) | MEDIUM |
| Endpoint scenarios (EICAR) | LOW (별도 축) |

---

## 5. Architectural Gaps (Non-Scenario)

| Gap | Impact | Priority |
|-----|--------|----------|
| **Detection Adapter Layer** | S3 전무; "validated" 주장 불가 | **HIGH** (Phase 10) |
| **Target Provider (live discovery)** | SSH/SMB skip (no targets) — 레거시 리포트 사례 | MEDIUM |
| **detection_mappings in manifest** | Catalog ↔ scenario 연결 미반영 | LOW |
| **Live lab CI** | Stellar/Splunk regression 없음 | MEDIUM |

---

## 6. Recommended Next Scenario

**Phase 6: SQL Injection**

| Criterion | Score |
|-----------|-------|
| Catalog priority | P0 (MVP 완성) |
| Protocol reuse | HTTP library 100% |
| Coverage impact | Stellar Web Exploit NONE → PARTIAL+; WAF 축 신규 |
| Implementation risk | Low (GET-only, safety manifest) |
| Test pattern | HTTP Follow-up E2E 복제 |

**Runner-up:** Port Sweep (Recon atomic) 또는 SMB Login Failure (Identity 확장) — Phase 7.

---

## 7. Related Documents

- [DETECTION_COVERAGE_REVIEW.md](./DETECTION_COVERAGE_REVIEW.md)
- [SCENARIO_TO_MODEL_MATRIX.md](./SCENARIO_TO_MODEL_MATRIX.md)
- [PHASE_ROADMAP.md](./PHASE_ROADMAP.md)
- [DETECTION_CATALOG.md](./DETECTION_CATALOG.md) §4 Future Scenarios
