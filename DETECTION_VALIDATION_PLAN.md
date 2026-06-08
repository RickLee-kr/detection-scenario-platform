# Detection Validation Plan — Phase 6.5

**문서 버전:** 1.0.0  
**상태:** Documentation only — 구현·Adapter·시나리오 변경 금지  
**목적:** MVP 5 시나리오에 대한 Stellar S3 (Detection Confirmed) 검증 정의  
**전제:** S1·S2 완료 (DSP Event Store). S3는 본 문서 및 후속 Adapter Phase에서 증명.

---

## 1. Scope

| In scope | Out of scope |
|----------|--------------|
| Stellar Cyber NDR (1차 검증 타겟) | Splunk/Defender/SentinelOne Adapter 구현 |
| Manual + future automated S3 poll 설계 | DSP 코드·아키텍처 변경 |
| Per-scenario alert/analytics/entity/evidence 정의 | Legacy `stellar_poc*.sh` 수정 |
| Lab validation handoff to `LAB_VALIDATION_PROCEDURE.md` | Customer deployment automation |

**Canonical reference:** [DETECTION_CONFIDENCE_MODEL.md](./DETECTION_CONFIDENCE_MODEL.md) — S3는 S2를 대체하지 않음.

---

## 2. Global S3 Validation Method (Stellar)

| Step | Method | Authority |
|------|--------|-----------|
| 1 | DSP `dsp run` with `dry_run=false`, live targets | S2 source |
| 2 | Confirm S2 `decision=success` in `validation.json` | DSP |
| 3 | Wait detection latency window (default **15–30 min** post-run) | Lab policy |
| 4 | Query Stellar: Alerts + Analytics + Entity timeline | S3 source |
| 5 | Correlate Stellar evidence to DSP `run_id` time window ±5 min | Human or future adapter |
| 6 | Record `DetectionConfirmation` artifact (manual spreadsheet → Phase 10 adapter) | S3 record |

**S3 Confirmed minimum bar:**

- At least **one** Stellar Alert **or** Analytics incident whose name/rule family matches §3–§7 below, **and**
- Entity (source IP / host) matches DSP executor host, **and**
- Timestamp overlaps DSP run `started_at`–`ended_at` + latency window.

**S3 Not Observed:** S2 success + Stellar poll OK + zero matching alerts (does **not** fail DSP exit code per Phase 1–3 policy).

---

## 3. DNS Tunnel (`dns_tunnel`)

| Field | Definition |
|-------|------------|
| **Scenario** | `dns_tunnel` |
| **Target Stellar Detection** | DNS Tunnel |
| **Expected Alert Name** | `DNS Tunnel` (primary); alternate: `DNS Exfiltration`, `Anomalous DNS Query` |
| **Expected Analytics** | DNS analytics: high-volume UDP/53; long subdomain labels; `idx-######-` label pattern; entropy/length anomaly on query names |
| **Expected Entity** | Source: DSP runner host IP (or webshell egress IP if remote executor). Destination: configured DNS resolver. Artifact: FQDN matching `idx-{seq:06d}-{base32}.*` |
| **Expected Evidence** | Stellar DNS query log samples; alert detail showing subdomain length; DSP `dns_tunnel_query_sent_count` ≥ 1; `events.jsonl` with `dns_tunnel_query_sent` |
| **Validation Method** | (1) S2 success. (2) Stellar Alert search: `DNS Tunnel` within 30 min. (3) Analytics → DNS → filter source IP + time. (4) Confirm idx-pattern FQDN in alert evidence or raw DNS events. |
| **Known Risks** | DNS mirror/SPAN not covering runner path; resolver off-net; low chunk count in test params → below Stellar threshold; dry_run never produces live DNS |
| **Confidence Level** | **HIGH** — strongest Stellar alignment; legacy PoC validated pattern |

**Recommended live params for S3 lab:** `max_chunks` at production default (not E2E-minimal); resolver = lab internal DNS or 10.10.10.x in `target_net`.

---

## 4. DGA (`dga`)

| Field | Definition |
|-------|------------|
| **Scenario** | `dga` |
| **Target Stellar Detection** | DGA / DNS Anomaly |
| **Expected Alert Name** | `DGA`; alternate: `DNS Anomaly`, `Algorithmically Generated Domain` |
| **Expected Analytics** | NXDOMAIN ratio spike; rare/new domain lookups; mixed NXDOMAIN + resolvable under same eTLD (`xdr.ooo` / `live.xdr.ooo`) |
| **Expected Entity** | Source: runner/egress IP. Resolver: manifest target. Artifacts: `*.xdr.ooo` (NXDOMAIN), `*.live.xdr.ooo` (resolvable) |
| **Expected Evidence** | Phase 1 NXDOMAIN count; Phase 2 resolvable count; DSP metrics `dga_nxdomain_observed_count`, `dga_resolved_observed_count`; Stellar DNS anomaly timeline |
| **Validation Method** | (1) S2 success with both nxdomain and resolvable metrics. (2) Stellar alert `DGA` or DNS Anomaly. (3) Verify domain suffix `xdr.ooo` in alert context. (4) Cross-check DSP `dga_completed` evidence `base_domain`. |
| **Known Risks** | E2E uses reduced `phase1_count`/`phase2_count` — may not meet Stellar volume threshold (legacy: nxdomain ≥ 300); external resolver may not see traffic; `live.xdr.ooo` resolvable phase needs DNS infra |
| **Confidence Level** | **HIGH** at full defaults; **MEDIUM** at reduced test volume |

**Recommended live params for S3 lab:** `phase1_count=500`, `phase2_count=30` (manifest defaults).

---

## 5. HTTP Follow-up (`http_followup`)

| Field | Definition |
|-------|------------|
| **Scenario** | `http_followup` |
| **Target Stellar Detection** | HTTP Recon / HTTPS Recon / Web Exploit Recon |
| **Expected Alert Name** | `HTTP Recon`, `HTTPS Recon`, or `Web Exploit Recon` (Stellar naming varies by rule pack) |
| **Expected Analytics** | Sequential GET to fixed paths (`/login`, `/admin`, `/api`, …); multi-port web access (443/80/8080); low-and-slow scan pattern |
| **Expected Entity** | Source: runner IP. Destination: `http_host`/`https_host` targets (max 2). URLs in evidence |
| **Expected Evidence** | DSP `http_request_sent_count`; sample URLs in `http_followup_completed`; Stellar HTTP transaction log; optional WAF log if in path |
| **Validation Method** | (1) S2 success. (2) Search Stellar for HTTP/HTTPS Recon family alerts. (3) Match destination host + path list from DSP report. (4) Confirm ≥1 response event optional (not required for S3). |
| **Known Risks** | **Low request volume** (≤20) may fall below recon threshold; unreachable web targets → connection errors only; no abnormal User-Agent (legacy probe differ); PARTIAL model coverage |
| **Confidence Level** | **MEDIUM** — signal family correct; volume/tuning sensitive |

**Tuning note:** May require `max_total=20` on **reachable** lab web server; preflight HTTP reachability recommended.

---

## 6. SSH Login Failure (`ssh_failure`)

| Field | Definition |
|-------|------------|
| **Scenario** | `ssh_failure` |
| **Target Stellar Detection** | Failed SSH Login / Brute-force-like Activity |
| **Expected Alert Name** | `Failed SSH Login` (primary); alternate: `Brute-force-like Activity`, `Multiple SSH Authentication Failures` |
| **Expected Analytics** | Repeated TCP/22 connections; multiple usernames; auth failure burst; no successful session |
| **Expected Entity** | Source: runner IP. Destination: SSH target:22. Usernames: `admin`, `root`, `test`, `ubuntu`, `user` (from Event Store evidence) |
| **Expected Evidence** | DSP `ssh_auth_attempt_count`, `ssh_auth_failed_count`; Stellar Identity/Network alert; optional target auth.log correlation (out-of-band) |
| **Validation Method** | (1) S2 success. (2) Stellar alert for SSH auth failure. (3) Confirm destination port 22 + failure count in analytics. (4) Time-correlate with DSP run window. |
| **Known Risks** | DSP uses **safe pubkey-only** (`PasswordAuthentication=no`) — may map to `Failed SSH Login` but not full `Brute-force`; SSH target must be reachable; legacy PoC skipped when no `ssh_host`; Identity sensor on Linux auth logs may differ from NDR-only path |
| **Confidence Level** | **MEDIUM–HIGH** for Failed SSH Login; **MEDIUM** for Brute-force-like |

**Recommended live params for S3 lab:** `max_per_host=30`, explicit `hosts=[ssh_target]`; ensure port 22 open on lab Linux host.

---

## 7. SQL Injection (`sql_injection`)

| Field | Definition |
|-------|------------|
| **Scenario** | `sql_injection` |
| **Target Stellar Detection** | SQL Injection / Web Application Attack |
| **Expected Alert Name** | `SQL Injection`; alternate: `Web Application Attack`, `SQLi Attempt`, WAF-adjacent `Web Exploit` |
| **Expected Analytics** | GET requests with SQL metacharacters in query string (`'`, `OR`, `UNION`, `--`); paths `/login`, `/admin`, `/api`, `/search` |
| **Expected Entity** | Source: runner IP. Destination: web target. Payloads in URL query (DSP `sample_payloads` in completed event) |
| **Expected Evidence** | DSP `sql_payload_generated_count`, `sql_request_sent_count`; Stellar HTTP alert with query string; optional WAF block log |
| **Validation Method** | (1) S2 success. (2) Stellar SQL Injection or Web Attack alert. (3) Match payload substring (`UNION SELECT`, `OR '1'='1`) in alert HTTP detail. (4) Correlate URL from DSP report. |
| **Known Risks** | Safe payloads only — may trigger signature-based NDR but not full WAF block; low volume (≤20); target app may not reflect SQL errors in response; first MVP lab run — **S3 unproven** |
| **Confidence Level** | **MEDIUM** — strong signature signal; volume and target dependency |

---

## 8. Cross-Scenario Validation Summary

| Scenario | S3 Confidence | Primary Tuning Risk |
|----------|---------------|---------------------|
| DNS Tunnel | HIGH | DNS visibility / volume |
| DGA | HIGH (full volume) | NXDOMAIN count threshold |
| HTTP Follow-up | MEDIUM | Low volume + target reachability |
| SSH Failure | MEDIUM–HIGH | Safe auth vs brute-force naming |
| SQL Injection | MEDIUM | WAF/NDR path + payload visibility |

---

## 9. Future Adapter Mapping (Documentation Only)

When Phase 10 Adapter is implemented, each row above becomes:

```yaml
detection_model_id: stellar.dns_tunnel  # example
poll_window_min: 30
match_rules:
  alert_name_contains: ["DNS Tunnel"]
  entity_source_ip: "${run.source_ip}"
  time_after_run_end_min: 5
```

No adapter code in Phase 6.5.

---

## 10. Related Documents

- [S3_CONFIRMATION_MATRIX.md](./S3_CONFIRMATION_MATRIX.md)
- [LAB_VALIDATION_PROCEDURE.md](./LAB_VALIDATION_PROCEDURE.md)
- [DETECTION_EVIDENCE_CATALOG.md](./DETECTION_EVIDENCE_CATALOG.md)
- [DETECTION_CONFIDENCE_MODEL.md](./DETECTION_CONFIDENCE_MODEL.md)
- [DETECTION_CATALOG.md](./DETECTION_CATALOG.md)
