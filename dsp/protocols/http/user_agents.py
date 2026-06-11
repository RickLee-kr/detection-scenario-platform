"""HTTP User-Agent pools — stellar_poc_followup.sh parity."""

from __future__ import annotations

import random
import re

# stellar_poc_followup.sh http_ua_pick_normal_local
_UA_NORMAL = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
)

# stellar_poc_followup.sh http_ua_pick_rare_scanner_local
_UA_RARE = (
    "TelemetryCollector/9.7",
    "ReconEngine/5.4",
    "SecurityAssessmentClient/3.1",
    "ThreatHunterAgent/8.2",
    "InternalAuditScanner/4.0",
    "DiscoveryProbe/7.3",
    "VulnerabilitySweep/2.6",
    "WebEnumerationFramework/11.0",
    "AssetProfiler/6.5",
    "NetworkSurveyBot/3.9",
    "Mozilla/5.0 ReconEngine/5.4",
    "Mozilla/5.0 ThreatHunterAgent/8.2",
)

_PAYLOAD_SQLI = (
    "' OR 1=1--",
    '" OR 1=1--',
    "1' OR '1'='1",
    "1 OR 2+701-701-1=0+0+0+1",
    "(select convert(int,char(65)))",
    "select pg_sleep(3)",
    "select pg_sleep(6)",
    "waitfor delay '0:0:5'",
    "waitfor delay '0:0:9'",
)

_PAYLOAD_ENC = (
    "%00%0d%0a",
    "%00%0a",
    "%0d%0a",
    "../../../../etc/passwd",
    "..%2f..%2f..%2f",
    "%252e%252e%252f",
)

_PAYLOAD_CMD = (
    ";id",
    ";whoami",
    "&&hostname",
    "|cat /etc/passwd",
)

_PAYLOAD_OTHER = (
    '12345"""};]*',
    "@@@@@@@",
    "%%%%%%%",
    "<<<<>>>>",
)

# bash remote python fallback payload_parts (subset)
_PAYLOAD_JNDI = (
    "${jndi:ldap://127.0.0.1/a}",
    "${jndi:rmi://127.0.0.1/exploit}",
    "${jndi:dns://127.0.0.1/x}",
)

_RE_SQLI = re.compile(
    r"OR 1=1|pg_sleep|waitfor delay|convert\(int|'='|2\+701",
    re.IGNORECASE,
)
_RE_ENC = re.compile(r"%00|%0d|%0a|%2f|%252e|\.\./|/etc/passwd|%%%%|@@@@|<<<<|\|\|\|\|")
_RE_CMD = re.compile(r";id|;whoami|&&hostname|\|cat ")
_RE_RARE = re.compile(
    r"TelemetryCollector|ReconEngine|ThreatHunter|DiscoveryProbe|"
    r"SecurityAssessment|AuditScanner|EnumerationFramework|AssetProfiler|"
    r"NetworkSurvey|VulnerabilitySweep",
    re.IGNORECASE,
)


def pick_normal_user_agent() -> str:
    return random.choice(_UA_NORMAL)


def pick_rare_user_agent() -> str:
    return random.choice(_UA_RARE)


def pick_payload_fragment() -> str:
    category = random.randrange(4)
    if category == 0:
        return random.choice(_PAYLOAD_SQLI)
    if category == 1:
        return random.choice(_PAYLOAD_ENC)
    if category == 2:
        return random.choice(_PAYLOAD_CMD)
    return random.choice(_PAYLOAD_OTHER)


def pick_payload_user_agent() -> str:
    """Bash pick_payload_ua — rare+payload or payload-only."""
    if random.randrange(2) == 0:
        return f"{pick_rare_user_agent()} {pick_payload_fragment()}"
    return pick_payload_fragment()


def is_scanner_user_agent(ua: str) -> bool:
    return bool(_RE_RARE.search(ua))


def is_payload_only_user_agent(ua: str) -> bool:
    if is_scanner_user_agent(ua):
        return False
    if any(marker in ua for marker in ("Chrome/120.0.0.0", "Version/17.0 Safari")):
        return False
    return bool(
        _RE_SQLI.search(ua)
        or _RE_ENC.search(ua)
        or _RE_CMD.search(ua)
        or ua in _PAYLOAD_OTHER
    )


def pick_url_scan_user_agent() -> str:
    """
    URL scan UA — scanner exact strings only; attack payload belongs in path/query.

    50% pure scanner UA, 50% scanner UA + payload suffix (never payload-only).
    """
    if random.randrange(2) == 0:
        return pick_rare_user_agent()
    return f"{pick_rare_user_agent()} {pick_payload_fragment()}"


def pick_burst_user_agent() -> str:
    """URL scan burst — scanner UA policy (no payload-only User-Agent)."""
    return pick_url_scan_user_agent()


def pick_user_agent() -> str:
    """Bash http_ua_pick_local — 10% normal, 40% rare, 50% payload."""
    roll = random.randrange(100)
    if roll < 10:
        return pick_normal_user_agent()
    if roll < 50:
        return pick_rare_user_agent()
    return pick_payload_user_agent()


def classify_user_agent(ua: str) -> str:
    """Bash http_ua_classify_local categories."""
    if any(marker in ua for marker in ("Chrome/120.0.0.0", "Version/17.0 Safari")):
        return "normal"
    if _RE_RARE.search(ua):
        if _RE_SQLI.search(ua) or _RE_ENC.search(ua) or _RE_CMD.search(ua):
            return "rare_with_payload"
        return "rare"
    if _RE_SQLI.search(ua):
        return "payload_sqli"
    if _RE_ENC.search(ua):
        return "payload_lfi"
    if _RE_CMD.search(ua):
        return "payload_cmd"
    return "payload_other"
