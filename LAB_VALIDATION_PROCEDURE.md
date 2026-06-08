# Lab Validation Procedure — Phase 6.5

**문서 버전:** 1.0.0  
**상태:** Documentation only — repeatable Stellar S3 validation playbook  
**Audience:** Lab operator, SE, customer validation engineer

---

## 1. Purpose

DSP MVP 시나리오 5건에 대해 **S2 (Traffic Validated)** 이후 **S3 (Detection Confirmed)** 를 Stellar Cyber lab에서 반복 검증하는 절차를 정의한다.

본 절차는 **수동 검증**을 기준으로 하며, Phase 10 Detection Adapter가 동일 단계를 자동화한다.

---

## 2. Environment Prerequisites

### 2.1 Lab Topology (Minimum)

| Component | Requirement |
|-----------|-------------|
| DSP runner host | Python 3.11+; `dsp` CLI installed; egress to lab `target_net` |
| Stellar Cyber | NDR sensor licensed; analytics processing enabled |
| Target network | `10.10.10.0/24` or documented lab CIDR ([TARGET_PROVIDER_SPEC.md](./TARGET_PROVIDER_SPEC.md)) |
| DNS resolver | Reachable resolver for `dns_tunnel`, `dga` |
| Web server | HTTP/HTTPS reachable host for `http_followup`, `sql_injection` |
| SSH server | Linux host port 22 for `ssh_failure` |

### 2.2 Sensor Requirements

| Sensor | Required for | Check |
|--------|--------------|-------|
| NDR / Network sensor | All 5 scenarios | DNS + HTTP + SSH traffic visible in Stellar |
| Traffic mirror / SPAN / TAP | DNS, HTTP, SSH | Runner-to-target path mirrored |
| Identity analytics (optional) | SSH Failure enhancement | Auth failure correlation |

**Pre-flight sensor check:** Stellar → Analytics → confirm runner source IP appears in last 24h baseline traffic.

### 2.3 Network Requirements

| Rule | Detail |
|------|--------|
| `target_net_enforced` | All scenario targets must fall within configured CIDR |
| Egress path | DSP runner → targets must traverse monitored segment |
| Firewall | Allow UDP/53, TCP/443,80,8080,8000,8443,22 per scenario |
| DNS | Internal resolver or lab DNS that forwards `xdr.ooo` queries |
| No dry_run for S3 | `dry_run=false` mandatory for Stellar validation |

### 2.4 Software Prerequisites

```bash
cd detection-scenario-platform
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/dsp plugins list   # all 5 MVP scenarios ACTIVE
```

---

## 3. Execution Steps (Per Run)

### 3.1 Pre-Run Checklist

- [ ] Record lab date, operator, Stellar tenant version
- [ ] Confirm target hosts alive (`ping` or documented reachability)
- [ ] Note runner source IP (for entity correlation)
- [ ] Clear or document existing Stellar alerts in test window (optional baseline)
- [ ] Set `DSP_RUNS_DIR` to writable evidence directory

### 3.2 Single-Scenario Run (Template)

```bash
export DSP_RUNS_DIR=/path/to/lab-evidence/runs

.venv/bin/dsp run \
  --scenarios <scenario_id> \
  --target-net 10.10.10.0/24 \
  --dry-run false \
  --scenario-params '<json_params>'
```

**Recommended params for S3 (not E2E-minimal):**

| scenario_id | scenario_params (example) |
|-------------|---------------------------|
| `dns_tunnel` | `{"dns_tunnel": {"hosts": ["10.10.10.20"], "max_chunks": 100}}` |
| `dga` | `{"dga": {"resolver": "10.10.10.20", "phase1_count": 500, "phase2_count": 30}}` |
| `http_followup` | `{"http_followup": {"hosts": ["10.10.10.20"], "max_total": 20}}` |
| `ssh_failure` | `{"ssh_failure": {"hosts": ["10.10.10.21"], "max_total": 30}}` |
| `sql_injection` | `{"sql_injection": {"hosts": ["10.10.10.20"], "max_total": 20}}` |

### 3.3 Full MVP Battery (Sequential)

Run scenarios in order with **≥5 min gap** to avoid alert correlation confusion:

1. `dns_tunnel`
2. `dga`
3. `http_followup`
4. `ssh_failure`
5. `sql_injection`

Record each `run_id` from `run.json`.

### 3.4 Post-Run Immediate Actions

- [ ] Verify `validation.json` → `decision: success` (S2)
- [ ] Archive run directory: `events.db`, `report.md`, `validation.json`, `events.jsonl`
- [ ] Note `run.started_at` and `run.ended_at` (UTC)
- [ ] Start Stellar detection latency timer (**30 min** default)

---

## 4. Validation Steps (S3 — Stellar)

### 4.1 Stellar Alert Search

For each `run_id`:

1. Open Stellar → Alerts / Incidents
2. Filter time: `[run_start - 2m, run_end + 30m]`
3. Filter entity: runner source IP and/or destination target IP
4. Search alert name per [DETECTION_VALIDATION_PLAN.md](./DETECTION_VALIDATION_PLAN.md)
5. Record: Alert ID, name, severity, timestamp, entity, excerpt

### 4.2 Stellar Analytics Correlation

1. Analytics → relevant module (DNS / Web / Identity)
2. Confirm signal type matches scenario (query burst, HTTP paths, SSH failures)
3. Screenshot or export analytics view (see Evidence Catalog)

### 4.3 DSP ↔ Stellar Correlation

| DSP Artifact | Stellar Field |
|--------------|---------------|
| `run_id` | Manual correlation key in evidence spreadsheet |
| `report.md` sample URLs/FQDNs | Alert HTTP/DNS detail |
| `validation.json` metrics | Volume sanity check |
| `events.jsonl` timestamps | Timeline alignment |

### 4.4 Evidence Collection

Complete [DETECTION_EVIDENCE_CATALOG.md](./DETECTION_EVIDENCE_CATALOG.md) checklist per scenario.

Store under:

```
lab-evidence/
  YYYY-MM-DD_mvp_validation/
    <run_id>/
      dsp/          # events.db, report.md, validation.json
      stellar/      # screenshots, alert exports
      notes.md      # S3 confirmed Y/N, alert IDs
```

---

## 5. Pass / Fail Criteria

### 5.1 Per-Scenario Pass (Lab)

| Gate | Criterion |
|------|-----------|
| **S2 Pass (required)** | `validation.json` decision = `success` |
| **S3 Pass (lab goal)** | ≥1 matching Stellar alert/analytics per S3 matrix |
| **Correlation Pass** | Entity + timeline + artifact match |

### 5.2 Per-Scenario Fail

| Condition | Classification |
|-----------|----------------|
| S2 failed | **DSP execution fail** — fix targets/params before S3 |
| S2 success, S3 not_observed | **Detection tuning fail** — volume, visibility, latency |
| S3 poll error | **Infrastructure fail** — Stellar access |
| Wrong alert (unrelated) | **Not counted** — do not mark S3 confirmed |

### 5.3 MVP Battery Pass (Customer-Ready Bar)

| Level | Criteria |
|-------|----------|
| **Minimum** | 5/5 S2 success in single lab session |
| **Target** | ≥3/5 S3 confirmed (DNS Tunnel + DGA + one other) |
| **Ideal** | 5/5 S3 confirmed with documented evidence pack |

### 5.4 Exit Code Policy

Per [DETECTION_CONFIDENCE_MODEL.md](./DETECTION_CONFIDENCE_MODEL.md): DSP exit code driven by **S2 only** until `--require-detection` (Phase 10). Lab pass/fail for customer demo uses separate S3 checklist.

---

## 6. Troubleshooting

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| S2 success, no Stellar alert | Low volume / sensor gap | Increase caps; verify SPAN |
| DNS scenarios silent | Resolver off-path | Point to in-segment resolver |
| HTTP/SQLi silent | Target unreachable | Fix web server; check curl |
| SSH silent | No ssh_host / port closed | Set explicit host; open :22 |
| DGA wrong base | Resolver blocking | Allow `xdr.ooo` queries |
| Alerts delayed >30 min | Stellar processing lag | Extend poll window to 60 min once |

---

## 7. Repeatability

| Item | Standard |
|------|----------|
| Frequency | Before customer demo; after DSP scenario change |
| Version pin | Record `dsp` version + Stellar version + manifest versions |
| Regression | Compare S3 hit rate across runs; document in `notes.md` |
| Future | Phase 10 adapter automates §3–§4 |

---

## 8. Related Documents

- [DETECTION_VALIDATION_PLAN.md](./DETECTION_VALIDATION_PLAN.md)
- [S3_CONFIRMATION_MATRIX.md](./S3_CONFIRMATION_MATRIX.md)
- [DETECTION_EVIDENCE_CATALOG.md](./DETECTION_EVIDENCE_CATALOG.md)
- [PHASE_6_5_REVIEW.md](./PHASE_6_5_REVIEW.md)
