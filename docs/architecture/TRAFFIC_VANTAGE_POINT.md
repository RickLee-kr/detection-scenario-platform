# Traffic Vantage Point — Local vs Webshell Execution

**문서 버전:** 1.0.0  
**상태:** Operational guidance for StellarCyber detection validation  
**관련:** `EXECUTION_MODEL_SPEC.md`, `EXECUTION_PROVIDER_DECISION_RECORD.md`

---

## 1. Purpose

StellarCyber 센서는 **트래픽의 출발지(srcip)와 관측 위치**에 따라 동일한 시나리오라도 탐지 결과가 달라질 수 있다. DSP v1.3.2 timing audit 이후에도 User-Agent anomaly, URL scan, IP/Port scan 미탐지가 지속되면 **실행 위치(vantage point) 차이**를 먼저 확인해야 한다.

---

## 2. Execution Modes

| Mode | CLI | Traffic origin | Typical srcip |
|------|-----|----------------|---------------|
| **Local** | `--execution-provider local` (default) | DSP 프로세스가 실행 중인 호스트 NIC | datarelay / DSP host IP |
| **Webshell** | `--execution-provider webshell` | 원격 피해 호스트(webshell) NIC | compromised host IP inside target segment |

---

## 3. Bash Stellar PoC Reference

기존 bash Stellar PoC(`stellar_poc.sh`, `stellar_poc_followup.sh`)는 **대부분의 내부 스캔·HTTP·SSH follow-up**을 webshell 호스트에서 `run_webshell_*`로 실행했다.

| Bash stage | Typical execution location |
|------------|---------------------------|
| Service discovery / port scan | webshell host → target-net |
| HTTP URL scan / UA anomaly | webshell host → discovered HTTP targets |
| SSH auth failure burst | webshell host → ssh_hosts |
| DNS tunnel | webshell host → dns resolver |
| Pre-WebShell URL scan | **operator/local** (attacker-side recon to webshell URL only) |

Bash discovery 실패 시 경고: *"verify remote scan from webshell host (not operator host)"*.

---

## 4. DSP Default (Local Mode)

현재 lab 환경에서 DSP는 **datarelay local**에서 실행되는 경우가 많다.

```
datarelay (DSP local) ──TCP/HTTP──► target-net (221.139.249.0/24)
         │
         └── StellarCyber sensor must observe THIS path
```

**Implications:**

- Port sweep srcip = datarelay IP (not webshell host IP)
- HTTP User-Agent / URL path는 **평문 HTTP(80/8080/…)** 일 때만 L7 센서가 payload를 볼 수 있음
- HTTPS(443/8443)는 TLS로 path/UA가 암호화되어 URL scan / UA anomaly 탐지 불가할 수 있음
- Sensor tap/mirror 위치가 webshell→target 경로만 커버하면 local mode 트래픽은 **미관측**

---

## 5. Verification Checklist

1. **출발지 IP 확인:** Event Store `port_probe_sent` / `http_request_sent` evidence의 source + run metadata `traffic_origin_host`
2. **StellarCyber raw log:** srcip가 datarelay인지 webshell host인지 확인
3. **HTTP scheme:** traffic_summary `schemes_used` — `http` only expected for URL/UA detection
4. **동일 위치 재검증:** bash와 동일 vantage point가 필요하면:
   ```bash
   dsp run --target-net <CIDR> --profile normal --scenarios port_sweep \
     --execution-provider webshell --webshell-url <URL>
   ```

---

## 6. Scenario-Specific Notes

### IP/Port Scan

- 탐지 임계값은 **probe rate(probes/sec)** 와 **horizontal spread(/24)** 에 민감
- v1.3.2: normal profile port_sweep concurrency=32 (bash `FALLBACK_SCAN_PARALLELISM` parity)
- traffic_summary: `duration_sec`, `probes_per_second`, `concurrency` 확인

### URL Scan / User-Agent Anomaly

- **HTTP 평문 포트 우선:** 80, 8080, 8000, 8888, 9000, 9090
- HTTPS는 `https_fallback=true`일 때만 사용
- `responses_received=0`이면 센서 L7 parser까지 도달하지 못한 것 — target/service 문제 가능

### SSH Login Failure

- ssh_hosts discovery bucket 필요
- vantage point가 다르면 ssh_hosts 선택·srcip 모두 달라질 수 있음

---

## 7. Recommended Isolated Runs

각 탐지 유형을 분리 검증:

```bash
# A. IP/Port Scan only
dsp run --target-net 221.139.249.0/24 --profile normal --scenarios port_sweep

# B. HTTP URL / User-Agent only
dsp run --target-net 221.139.249.0/24 --profile normal --scenarios http_followup

# C. SSH login failure only
dsp run --target-net 221.139.249.0/24 --profile normal --scenarios ssh_failure
```

Event Store + `traffic_summary.json`만 SOT — StellarCyber API/alert 조회는 별도 운영 절차.
