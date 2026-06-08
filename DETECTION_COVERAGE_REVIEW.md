# Detection Coverage Review — Phase 5.5

**문서 버전:** 1.0.0  
**상태:** Documentation only — 구현 금지  
**평가 기준일:** 2026-06-05  
**평가 대상:** DSP 구현 완료 시나리오 4종 (DNS Tunnel, DGA, HTTP Follow-up, SSH Login Failure)

---

## 1. Executive Summary

DSP는 현재 **4개 트래픽 시나리오**를 Event Store SOT 아키텍처로 구현했다.  
각 시나리오는 **S2 (Traffic Validated)** 까지는 DSP 내부 테스트로 증명되나, **S3 (Detection Confirmed)** 는 Detection Adapter Layer가 없어 **어떤 벤더에서도 아직 확인되지 않았다**.

| 시나리오 | Stellar 커버리지 (추정) | Splunk / Defender / SentinelOne (추정) | S2 Lab Status | S3 Lab Status |
|----------|------------------------|----------------------------------------|---------------|---------------|
| DNS Tunnel | **FULL** | PARTIAL | ✅ DSP validated | ❌ 미확인 |
| DGA | **FULL** | PARTIAL | ✅ DSP validated | ❌ 미확인 |
| HTTP Follow-up | **PARTIAL** | PARTIAL | ✅ DSP validated | ❌ 미확인 |
| SSH Login Failure | **FULL** (신호 유형) / **PARTIAL** (강도) | PARTIAL | ✅ DSP validated | ❌ 미확인 |

**전체 커버리지 요약:** Stellar NDR 중심 **DNS·Web·Auth 3축**의 핵심 use case 4건에 대응 가능.  
Identity(SMB/Kerberos/LDAP), Web 공격(SQLi), 정찰(Port Sweep/Internal Recon), DNS 변형(TXT Exfil)은 **미구현**.

---

## 2. 평가 방법론

### 2.1 상태 정의 (DETECTION_CONFIDENCE_MODEL.md)

| 상태 | 의미 | 본 리뷰에서의 사용 |
|------|------|-------------------|
| **S1** | Executor 실행 완료 (비권위) | 참고만 |
| **S2** | Event Store aggregate → ValidationEngine success | **Lab Validation Status** 기준 |
| **S3** | Vendor/SIEM에서 탐지 alert 확인 | Detection Adapter 필요 — 현재 전 시나리오 **미확인** |

### 2.2 Confidence 등급

| 등급 | 정의 |
|------|------|
| **HIGH** | 트래픽 패턴이 Stellar 레거시 PoC·Catalog와 1:1 대응, NDR/DNS/Identity 신호 유형 일치 |
| **MEDIUM** | 동일 use case family이나 볼륨·패턴·프로토콜 세부가 다름 |
| **LOW** | 간접 신호만 유발 가능, 벤더별 모델명·룰셋 불일치 가능성 큼 |

### 2.3 Coverage 등급

| 등급 | 정의 |
|------|------|
| **FULL** | 주요 탐지 모델의 핵심 신호를 의도적으로 재현 |
| **PARTIAL** | 일부 신호만 재현; 볼륨·변형·연계 행위 부족 |
| **NONE** | 해당 모델에 대응하는 시나리오 없음 |

---

## 3. 시나리오별 상세 평가

### 3.1 DNS Tunnel (`dns_tunnel`)

| 항목 | 내용 |
|------|------|
| **Target Detection** | Stellar: **DNS Tunnel** · Splunk: DNS Exfiltration / DNS Tunneling · Defender: DNS tunneling / anomalous DNS queries · Elastic/QRadar: DNS exfil / anomaly |
| **Expected Signal** | UDP/53 DNS query burst; `idx-{seq:06d}-{base32}.<domain>` 형태의 긴 서브도메인 라벨; 청크 단위 반복 조회; NDR DNS analytics 트리거 |
| **Confidence** | Stellar **HIGH** · Splunk **MEDIUM** · Defender **MEDIUM** · SentinelOne **LOW** (DNS depth 제한) |
| **Known Limitations** | (1) 응답 수신 불필요 — 단방향 query만으로 검증; 일부 벤더는 응답 볼륨도 참조. (2) idx-pattern 비율·청크 수는 테스트에서 축소 가능. (3) 실제 C2 응답 채널·TXT 레코드 변형 미포함. (4) S3 미확인 — Adapter 없음. (5) 레거시 Stellar PoC 실행 리포트(2026-06-05)에서 DNS Tunnel stage failed 사례 존재(DSP와 별개 레거시 경로). |
| **Lab Validation Status** | **S2: PASS** — E2E dry_run/live, path equality, Event Store metrics (`dns_tunnel_query_sent_count >= 1`). **S3: NOT RUN** — Detection Adapter 미구현. |

---

### 3.2 DGA (`dga`)

| 항목 | 내용 |
|------|------|
| **Target Detection** | Stellar: **DGA / DNS Anomaly** · Splunk: DGA domain activity · Defender: DGA / algorithmically generated domains · SentinelOne: DGA — rare domain lookups |
| **Expected Signal** | Phase 1: `*.xdr.ooo` NXDOMAIN burst (기본 500건); Phase 2: `*.live.xdr.ooo` resolvable (기본 30건); 동일 eTLD 내 NX+resolvable 혼합 — Stellar 2-phase DGA 모델과 정합 |
| **Confidence** | Stellar **HIGH** · Splunk **MEDIUM** · Defender **MEDIUM** · SentinelOne **MEDIUM** |
| **Known Limitations** | (1) 테스트/E2E는 축소 볼륨(phase1_count/phase2_count 파라미터). (2) 실제 악성 DGA 알고리즘·시드 기반 재현 아님 — 랜덤 라벨 시뮬레이션. (3) `entropy_only_dga` 레거시 모델은 의도적 배제. (4) DNS resolver 가용성에 live 모드 의존. (5) S3 미확인. |
| **Lab Validation Status** | **S2: PASS** — `dga_nxdomain_observed_count`, `dga_resolved_observed_count` threshold 충족. **S3: NOT RUN**. |

---

### 3.3 HTTP Follow-up (`http_followup`)

| 항목 | 내용 |
|------|------|
| **Target Detection** | Stellar: **HTTP Recon / HTTPS Recon / Web Exploit Recon** (레거시 PoC 매핑) · Splunk: Web vulnerability scan · Defender: Suspicious web connection · WAF: fixed-path probe |
| **Expected Signal** | 포트 우선순위 443/8443/80/8080/8000; 고정 경로 10종 (`/login`, `/admin`, `/api` 등); 최대 2호스트 × 10요청, 총 20요청; HTTP/HTTPS GET, redirect 미추적 |
| **Confidence** | Stellar **MEDIUM** (Recon family에 속하나 "Follow-up" 전용 모델명 없음) · Splunk **MEDIUM** · Defender **LOW–MEDIUM** · SentinelOne **LOW** |
| **Known Limitations** | (1) 취약점 스캐너 아님 — SQLi/XSS payload 없음. (2) 비정상 User-Agent·IDS/WAF 시그니처 프로브 없음(레거시 `ids_waf_signature_probe` 미이식). (3) 응답 200만으로 success — 4xx/5xx 탐지 시나리오 미포함. (4) Host discovery·reachability 선행 단계 없음(Target stub). (5) S3 미확인. |
| **Lab Validation Status** | **S2: PASS** — `http_request_sent_count >= 1`. **S3: NOT RUN**. |

---

### 3.4 SSH Login Failure (`ssh_failure`)

| 항목 | 내용 |
|------|------|
| **Target Detection** | Stellar: **Failed SSH Login / Brute-force-like Activity** · Splunk: Multiple failed SSH logins · Defender: SSH brute force detection · SentinelOne: Failed authentication — SSH |
| **Expected Signal** | TCP/22 반복 연결; 다중 username (`admin`, `root`, `test`, `ubuntu`, `user`); 인증 실패 이벤트; 기본 30 attempts/host, max 60 total; NDR·Identity analytics |
| **Confidence** | Stellar **HIGH** (Failed SSH Login) / **MEDIUM** (Brute-force-like — 실제 password spray 아님) · Splunk **MEDIUM** · Defender **MEDIUM** · SentinelOne **MEDIUM** |
| **Known Limitations** | (1) **Safe pubkey-only** — `PasswordAuthentication=no`, `BatchMode=yes`; 진짜 brute-force·password spray 아님. (2) Dummy password는 Event Store evidence 전용. (3) `invaliduser@` 레거시 패턴 대신 고정 username 리스트 사용 — 일부 SIEM correlation 룰과 차이 가능. (4) SSH target discovery stub — hosts 미지정 시 default IP. (5) 레거시 PoC 리포트에서 SSH Auth Burst skipped (no SSH targets) — DSP live lab 미연동. (6) S3 미확인. |
| **Lab Validation Status** | **S2: PASS** — `ssh_auth_attempt_count >= 1`, `ssh_auth_failed_count >= 1`. **S3: NOT RUN**. |

---

## 4. 벤더별 종합 커버리지

### 4.1 Stellar Cyber (NDR — 1차 타겟)

| 탐지 모델 (Stellar) | DSP 시나리오 | Coverage | Confidence |
|-------------------|-------------|----------|------------|
| DNS Tunnel | `dns_tunnel` | FULL | HIGH |
| DGA / DNS Anomaly | `dga` | FULL | HIGH |
| HTTP Recon / Web Exploit Recon | `http_followup` | PARTIAL | MEDIUM |
| Failed SSH Login / Brute-force-like | `ssh_failure` | FULL (신호) / PARTIAL (강도) | HIGH / MEDIUM |

**Stellar 커버 비율 (Catalog MVP 5건 기준):** 4/5 시나리오 구현 → **80% traffic coverage**; SQL Injection 미구현.

### 4.2 Splunk (SIEM — 2차 타겟)

| 탐지 use case | Coverage | Confidence |
|--------------|----------|------------|
| DNS Exfiltration / Tunneling | PARTIAL (`dns_tunnel`) | MEDIUM |
| DGA domain activity | PARTIAL (`dga`) | MEDIUM |
| Web vulnerability scan | PARTIAL (`http_followup`) | MEDIUM |
| Multiple failed SSH logins | PARTIAL (`ssh_failure`) | MEDIUM |
| SQLi web attack | NONE | — |

Splunk는 **동일 신호 유형에 대응 가능**하나, CIM·ES correlation·볼륨 threshold는 Adapter + live lab으로만 검증 가능.

### 4.3 Microsoft Defender (EDR/NDR — 3차 타겟)

| 탐지 use case | Coverage | Confidence |
|--------------|----------|------------|
| DNS tunneling / anomalous DNS | PARTIAL | MEDIUM |
| DGA domains | PARTIAL | MEDIUM |
| Suspicious web connection | PARTIAL | LOW–MEDIUM |
| SSH brute force | PARTIAL | MEDIUM |
| Web exploit / SQLi | NONE | — |

Defender는 **endpoint-heavy** 모델이 많아 NDR-only 시나리오는 네트워크 가시성에 의존.

### 4.4 SentinelOne (EDR — 3차 타겟)

| 탐지 use case | Coverage | Confidence |
|--------------|----------|------------|
| DGA — rare domain lookups | PARTIAL (`dga`) | MEDIUM |
| Failed authentication — SSH | PARTIAL (`ssh_failure`) | MEDIUM |
| DNS / HTTP anomaly | PARTIAL | LOW |
| Process / file telemetry | NONE | — |

현재 DSP 시나리오는 **네트워크 행위 중심** — SentinelOne 강점(프로세스·파일) 미커버.

---

## 5. 아키텍처적 관찰

1. **Scenario ≠ Detection:** 4 시나리오 모두 S2는 증명, S3는 전부 공백. Catalog `validated` 상태는 **Stellar live 탐지 확인 전**이며 DSP 구현 완료와 동일시하면 안 됨.
2. **Path Equality 유지:** Execution = Validation = Reporting — 벤더 Adapter 추가 시에도 S2 경로 변경 불필요.
3. **신호 축:** DNS 2건 + Web 1건 + Auth 1건 = **NDR 핵심 4축** 초기 커버. Identity 확장(SMB/Kerberos/LDAP)과 Web 공격(SQLi)이 다음 격차.

---

## 6. 권장 다음 단계 (요약)

| 우선순위 | 항목 | 근거 |
|----------|------|------|
| 1 | **SQL Injection** (Phase 6) | Catalog P0, HTTP 프로토콜 재사용, WAF/NDR 공백 해소 |
| 2 | **Detection Adapter Layer** (Phase 10) | S3 확인 없이는 "validated" 주장 불가 |
| 3 | **SMB Login Failure** (Phase 7) | Identity 축 확장, Windows telemetry 연계 |
| 4 | **Port Sweep / Internal Recon** | HTTP Follow-up의 PARTIAL Recon 보완 |

상세 매트릭스: [SCENARIO_TO_MODEL_MATRIX.md](./SCENARIO_TO_MODEL_MATRIX.md)  
격차 분석: [DETECTION_GAP_ANALYSIS.md](./DETECTION_GAP_ANALYSIS.md)  
로드맵: [PHASE_ROADMAP.md](./PHASE_ROADMAP.md)

---

## 7. Related Documents

- [DETECTION_CATALOG.md](./DETECTION_CATALOG.md)
- [DETECTION_CONFIDENCE_MODEL.md](./DETECTION_CONFIDENCE_MODEL.md)
- [SCENARIO_TO_MODEL_MATRIX.md](./SCENARIO_TO_MODEL_MATRIX.md)
- [DETECTION_GAP_ANALYSIS.md](./DETECTION_GAP_ANALYSIS.md)
- [PHASE_ROADMAP.md](./PHASE_ROADMAP.md)
