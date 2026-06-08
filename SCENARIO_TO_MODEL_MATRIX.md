# Scenario-to-Detection-Model Matrix — Phase 5.5

**문서 버전:** 1.0.0  
**상태:** Documentation only  
**Coverage 등급:** `FULL` · `PARTIAL` · `NONE`

---

## 1. How to Read

```
Scenario → Detection Model (Vendor) → Coverage
```

- **FULL:** 핵심 신호·패턴이 모델 설계 의도와 직접 대응
- **PARTIAL:** 동일 use case family이나 볼륨·변형·연계 신호 부족
- **NONE:** 대응 시나리오 없음

**Lab note:** 아래 모든 구현 시나리오는 **S2 (DSP Traffic Validated) ✅** / **S3 (Vendor Detection Confirmed) ❌** (Adapter 미구현).

---

## 2. Primary Matrix — Implemented Scenarios

### 2.1 Stellar Cyber (NDR)

| Scenario | Stellar Detection Model | Coverage | Confidence | Notes |
|----------|------------------------|----------|------------|-------|
| `dns_tunnel` | DNS Tunnel | **FULL** | HIGH | idx-pattern FQDN, UDP/53 — 레거시 Stellar 클라이언트 정합 |
| `dga` | DGA / DNS Anomaly | **FULL** | HIGH | NXDOMAIN + resolvable 2-phase, `xdr.ooo` eTLD |
| `http_followup` | HTTP Recon | **PARTIAL** | MEDIUM | 고정 경로·저볼륨; Web Exploit Recon 일부만 |
| `http_followup` | HTTPS Recon | **PARTIAL** | MEDIUM | 443/8443 우선 포트 포함 |
| `http_followup` | Web Exploit Recon | **PARTIAL** | LOW | SQLi/시그니처 payload 없음 |
| `ssh_failure` | Failed SSH Login | **FULL** | HIGH | 다중 username, 반복 auth failure |
| `ssh_failure` | Brute-force-like Activity | **PARTIAL** | MEDIUM | Safe pubkey-only; password spray 없음 |
| `ssh_failure` | Lateral Movement-like Traffic | **NONE** | — | SSH 성공·세션 없음 — 의도적 배제 |

### 2.2 Splunk (SIEM / ES)

| Scenario | Splunk Detection Model / Use Case | Coverage | Confidence | Notes |
|----------|-----------------------------------|----------|------------|-------|
| `dns_tunnel` | DNS Exfiltration | **PARTIAL** | MEDIUM | Query-side only; exfil volume threshold 미검증 |
| `dns_tunnel` | DNS Tunneling | **PARTIAL** | MEDIUM | Subdomain entropy·길이 신호 유사 |
| `dga` | DGA Domain Activity | **PARTIAL** | MEDIUM | NXDOMAIN ratio; correlation 룰 미검증 |
| `http_followup` | Web Vulnerability Scan | **PARTIAL** | MEDIUM | Fixed path probe; full scan 아님 |
| `http_followup` | Suspicious Web Access | **PARTIAL** | LOW | UA·payload 변형 없음 |
| `ssh_failure` | Multiple Failed SSH Logins | **PARTIAL** | MEDIUM | Syslog/auth.log 연동은 Adapter 필요 |
| `ssh_failure` | SSH Brute Force | **PARTIAL** | LOW | Password auth 미사용 |

### 2.3 Microsoft Defender

| Scenario | Defender Detection Model | Coverage | Confidence | Notes |
|----------|-------------------------|----------|------------|-------|
| `dns_tunnel` | DNS tunneling | **PARTIAL** | MEDIUM | Network sensor 가시성 의존 |
| `dns_tunnel` | Anomalous DNS queries | **PARTIAL** | MEDIUM | Long subdomain 패턴 |
| `dga` | DGA / algorithmically generated domains | **PARTIAL** | MEDIUM | Endpoint DNS vs NDR 차이 |
| `http_followup` | Suspicious web connection | **PARTIAL** | LOW–MEDIUM | 저볼륨 recon |
| `http_followup` | Web exploit attempt | **NONE** | — | SQLi 시나리오 없음 |
| `ssh_failure` | SSH brute force detection | **PARTIAL** | MEDIUM | Failed login burst; true brute-force 아님 |
| `ssh_failure` | Identity — failed sign-in (SSH) | **PARTIAL** | MEDIUM | Linux auth telemetry 필요 |

### 2.4 SentinelOne

| Scenario | SentinelOne Detection Model | Coverage | Confidence | Notes |
|----------|----------------------------|----------|------------|-------|
| `dns_tunnel` | DNS anomaly (network) | **PARTIAL** | LOW | NDR depth 제한적 |
| `dga` | DGA — rare domain lookups | **PARTIAL** | MEDIUM | DNS visibility 필요 |
| `http_followup` | Suspicious network connection | **PARTIAL** | LOW | Web-specific 모델 약함 |
| `ssh_failure` | Failed authentication — SSH | **PARTIAL** | MEDIUM | Network + auth event |
| `ssh_failure` | Brute force — remote service | **PARTIAL** | LOW | Volume·password pattern 부족 |

---

## 3. Cross-Vendor Summary Matrix

| Scenario | Stellar | Splunk | Defender | SentinelOne | **Worst-Case Coverage** |
|----------|---------|--------|----------|-------------|-------------------------|
| `dns_tunnel` | FULL | PARTIAL | PARTIAL | PARTIAL | **PARTIAL** |
| `dga` | FULL | PARTIAL | PARTIAL | PARTIAL | **PARTIAL** |
| `http_followup` | PARTIAL | PARTIAL | PARTIAL | PARTIAL | **PARTIAL** |
| `ssh_failure` | FULL* | PARTIAL | PARTIAL | PARTIAL | **PARTIAL** |

\* Stellar Failed SSH Login = FULL; Brute-force-like = PARTIAL

---

## 4. Unimplemented Scenarios — Model Coverage Gap

| Detection Model (대표) | Vendor | Scenario Needed | Coverage Today |
|------------------------|--------|-----------------|----------------|
| SQL Injection (HTTP) | Stellar, Splunk, WAF | `sql_injection` | **NONE** |
| SMB Brute Force / Bad Auth | Stellar, Splunk | `smb_login_failure` | **NONE** |
| LDAP Enumeration | Stellar, Elastic | `ldap_enumeration` | **NONE** |
| Kerberos Pre-auth Failure | Defender, QRadar | `kerberos_auth_failure` | **NONE** |
| DNS TXT Exfiltration | Stellar, Splunk | `dns_txt_exfil` | **NONE** |
| Internal Port Scan / Sweep | Stellar, Darktrace | `port_sweep` | **NONE** |
| Host Discovery / Internal Recon | Stellar, Splunk | `internal_recon` | **NONE** |
| RDP Login Failure | Defender, Splunk | `rdp_login_failure` | **NONE** |
| Beaconing / HTTP Callback | Stellar, Darktrace | `http_beacon_interval` | **NONE** |
| EICAR / Static Signature | EDR vendors | `eicar_file_create` | **NONE** |

---

## 5. Signal-Type Coverage Map

| Signal Type | Implemented | Gap |
|-------------|-------------|-----|
| **NDR / DNS** | `dns_tunnel`, `dga` | `dns_txt_exfil`, `dns_new_tld` |
| **NDR / Web** | `http_followup` | `sql_injection`, WAF signature probe |
| **NDR / Identity** | `ssh_failure` | `smb_login_failure`, `kerberos_auth_failure`, `ldap_enumeration`, `rdp_login_failure` |
| **NDR / Recon** | (간접 — HTTP) | `port_sweep`, `internal_recon` |
| **EDR / Endpoint** | — | `eicar_file_create`, `process_spawn_chain` |
| **WAF / IDS** | (간접 — HTTP paths) | `sql_injection`, `ids_waf_signature_probe` |

---

## 6. Validation Layer Matrix

| Layer | DNS Tunnel | DGA | HTTP Follow-up | SSH Failure |
|-------|------------|-----|----------------|-------------|
| DSP Event Store (S2) | ✅ | ✅ | ✅ | ✅ |
| Path Equality Tests | ✅ | ✅ | ✅ | ✅ |
| E2E dry_run | ✅ | ✅ | ✅ | ✅ |
| E2E live (mocked transport) | ✅ | ✅ | ✅ | ✅ |
| Stellar live detection (S3) | ❌ | ❌ | ❌ | ❌ |
| Splunk correlation (S3) | ❌ | ❌ | ❌ | ❌ |
| Defender alert (S3) | ❌ | ❌ | ❌ | ❌ |
| SentinelOne alert (S3) | ❌ | ❌ | ❌ | ❌ |

---

## 7. Example Rows (Canonical Format)

```
DNS Tunnel → DNS Tunnel (Stellar) → FULL
DGA → DGA / DNS Anomaly (Stellar) → FULL
HTTP Follow-up → HTTP Recon (Stellar) → PARTIAL
SSH Failure → Failed SSH Login (Stellar) → FULL
SSH Failure → Brute-force-like Activity (Stellar) → PARTIAL
SQL Injection → (any vendor) → NONE [not implemented]
```

---

## 8. Related Documents

- [DETECTION_COVERAGE_REVIEW.md](./DETECTION_COVERAGE_REVIEW.md)
- [DETECTION_GAP_ANALYSIS.md](./DETECTION_GAP_ANALYSIS.md)
- [DETECTION_CATALOG.md](./DETECTION_CATALOG.md)
- [PHASE_ROADMAP.md](./PHASE_ROADMAP.md)
