# Detection Scenario Platform — Protocol Library Specification

**문서 버전:** 1.0.0 (Phase 0.5 — **FROZEN**)  
**상태:** Canonical contract for shared protocol implementations

---

## 1. Purpose

시나리오 executor 간 **중복 프로토콜 로직 방지**.  
DNS·HTTP·SSH 등은 `dsp/protocols/`에서 한 번 구현하고 시나리오는 조합만 한다.

| Without protocol lib | With protocol lib |
|---------------------|-------------------|
| 50 scenarios × DNS encode | 1 `dns.py` |
| divergent timeout/error handling | consistent events |
| copy-paste from legacy clients | controlled port from legacy |

---

## 2. Ownership Boundaries (Frozen)

```
┌─────────────────────────────────────────────────────────┐
│  dsp/protocols/          ← SHARED (platform team)       │
│    dns.py, http.py, ssh.py                              │
├─────────────────────────────────────────────────────────┤
│  scenarios/<id>/executor.py  ← SCENARIO (plugin author) │
│    orchestration, FQDN patterns, volume, event mapping    │
├─────────────────────────────────────────────────────────┤
│  scenarios/<id>/scenario.py  ← lifecycle only             │
└─────────────────────────────────────────────────────────┘
```

| Layer | Owns | Must NOT own |
|-------|------|--------------|
| **Protocol library** | socket/encode/send/recv, timeouts | FQDN patterns, scenario thresholds |
| **Executor** | pattern generation, event append, batching | raw struct.pack DNS header |
| **Scenario** | prepare/execute/summarize flow | duplicate protocol primitives |

---

## 3. Directory Layout (Frozen)

```
dsp/protocols/
├── __init__.py
├── base.py              # ProtocolError, timeout defaults
├── dns.py               # DNS UDP/TCP client
├── http.py              # HTTP/HTTPS client
├── ssh.py               # SSH auth attempts (safe)
├── types.py             # DnsQuery, HttpRequest, SshAttempt
└── future/
    ├── smb.py           # Phase 4+
    ├── ldap.py
    └── kerberos.py
```

---

## 4. DNS Protocol Abstraction

**Legacy reference:** `stellar_dns_tunnel_file_client.py`, `stellar_dga_model_client.py`

### 4.1 Public API (Frozen surface)

```python
# dsp/protocols/dns.py — conceptual

@dataclass
class DnsQueryResult:
    fqdn: str
    qtype: str
    outcome: str          # sent | nxdomain | response | timeout | error
    rcode: int | None
    response_summary: dict | None


def encode_qname(fqdn: str) -> bytes: ...

def build_query(fqdn: str, qtype: int = 1) -> tuple[int, bytes]: ...

def send_udp_query(
    resolver: str,
    fqdn: str,
    *,
    port: int = 53,
    timeout: float = 0.05,
    recv: bool = True,
) -> DnsQueryResult: ...

def read_system_resolver() -> str | None: ...
```

### 4.2 Responsibilities

| In dns.py | In executor |
|-----------|-------------|
| QNAME encode, header pack | idx-pattern FQDN generation |
| UDP sendto / recv | session strt/idx/end sequencing |
| RCODE parse | volume caps, sleep jitter |
| timeout handling | event evidence fields |

### 4.3 Event mapping (executor duty)

Protocol returns `DnsQueryResult` → executor maps to `event=query_sent`, `status=outcome`.

---

## 5. HTTP Protocol Abstraction

**Legacy reference:** HTTP follow-up caps (≤20 req, fixed paths)

### 5.1 Public API (Frozen surface)

```python
@dataclass
class HttpResponseResult:
    url: str
    method: str
    status_code: int | None
    outcome: str          # response | timeout | connection_refused | dns_failure
    headers: dict | None


def send_request(
    url: str,
    *,
    method: str = "GET",
    timeout: float = 10.0,
    verify_tls: bool = False,
    headers: dict | None = None,
) -> HttpResponseResult: ...
```

### 5.2 Responsibilities

| In http.py | In executor |
|------------|-------------|
| Connection, TLS, timeout | URL list, path rotation |
| Status code extraction | SQLi payload in query string |
| redirect policy (no follow by default) | max request cap |

### 5.3 SQL Injection executor

Uses `send_request()` with crafted query strings — **no** separate HTTP stack.

---

## 6. SSH Protocol Abstraction

**Legacy reference:** `invaliduser@`, BatchMode, PasswordAuthentication=no

### 6.1 Public API (Frozen surface)

```python
@dataclass
class SshAttemptResult:
    target: str
    port: int
    username: str
    outcome: str          # attempted | auth_failed | connection_refused | timeout | error


def attempt_auth_failure(
    host: str,
    *,
    port: int = 22,
    username: str = "invaliduser",
    timeout: float = 10.0,
) -> SshAttemptResult: ...
```

### 6.2 Safety (Frozen)

| Rule | |
|------|--|
| Default username `invaliduser` only | |
| No password auth enabled | |
| No valid key file | |
| No command execution after connect | |

---

## 7. Future Protocol Categories

| Category | Module | Phase | Scenarios using |
|----------|--------|-------|-----------------|
| SMB | `smb.py` | 4 | smb_login_failure |
| LDAP | `ldap.py` | 4 | ldap_enumeration |
| Kerberos | `kerberos.py` | 4 | kerberos_auth_failure |
| RDP | `rdp.py` | 4 | rdp_login_failure |
| Raw TCP | `tcp.py` | 3 | port_sweep |

New category = new file in `dsp/protocols/` — **not** new copy in scenario.

---

## 8. Reusable Components

| Component | Location | Used by |
|-----------|----------|---------|
| `encode_qname` | dns.py | dns_tunnel, dga, dns_txt_exfil |
| `send_udp_query` | dns.py | dns_tunnel, dga |
| `send_request` | http.py | http_followup, sql_injection |
| `attempt_auth_failure` | ssh.py | ssh_failure |
| `base.retry_policy` | base.py | optional executors |
| `base.rate_limit` | base.py | volume-controlled scenarios |

---

## 9. Error Handling (Frozen)

| ProtocolError | Executor maps to |
|---------------|-------------------|
| `TimeoutError` | event status `timeout` |
| `ConnectionRefusedError` | `connection_refused` |
| `DnsResolutionError` | `dns_failure` |
| Other | `error` + evidence.message |

Protocol library MUST NOT write Event Store — return result objects only.

---

## 10. Testing (Phase 1+)

| Layer | Test approach |
|-------|---------------|
| protocols/ | unit tests with mock socket / responses |
| executor | integration with dry-run + event assertions |
| no protocol logic in validation tests | |

---

## 11. Legacy Port Policy

| Legacy file | Port to |
|-------------|---------|
| `stellar_dns_tunnel_file_client.py` | `dsp/protocols/dns.py` + `scenarios/dns_tunnel/executor.py` |
| `stellar_dga_model_client.py` | same dns.py + `scenarios/dga/executor.py` |

Copy **algorithm**, not file structure or stdout markers.

---

## 12. Versioning

`protocol_library_version: 1.0.0` — bump MINOR for backward-compatible API add; MAJOR for signature break.

---

## 13. Related Documents

- [SCENARIO_INTERFACE_FREEZE.md](./SCENARIO_INTERFACE_FREEZE.md)
- [SCENARIO_MANIFEST_SPEC.md](./SCENARIO_MANIFEST_SPEC.md) — `supported_protocols`
- [docs/adr/0001-python-over-bash.md](./docs/adr/0001-python-over-bash.md)
