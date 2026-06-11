"""Bash-parity curl transport tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dsp.protocols.http.curl_transport import build_curl_command, send_request_curl


def test_build_curl_command_get_bash_parity():
    argv = build_curl_command(
        "http://10.10.10.20/admin?id=%00%00%00",
        method="GET",
        timeout=2.0,
        headers={
            "Host": "10.10.10.20",
            "User-Agent": "ThreatHunterAgent/8.2",
            "X-External-URL-Recon": "camp123",
            "X-PoC-Mode": "external_url_scan",
            "X-PoC-Campaign": "camp123",
        },
    )
    assert argv[0] == "curl"
    assert "-A" in argv
    assert "ThreatHunterAgent/8.2" in argv
    assert "-H" in argv
    assert any("X-PoC-Campaign: camp123" in part for part in argv)
    assert argv[-1] == "http://10.10.10.20/admin?id=%00%00%00"
    assert "--max-time" in argv


def test_build_curl_command_post_includes_data():
    argv = build_curl_command(
        "http://10.10.10.20/",
        method="POST",
        timeout=2.0,
        headers={"User-Agent": "ReconEngine/5.4"},
        body="probe=camp123",
    )
    assert "-X" in argv
    assert "POST" in argv
    assert "--data" in argv
    assert "probe=camp123" in argv


def test_send_request_curl_parses_status():
    with patch("dsp.protocols.http.curl_transport.subprocess.run") as run:
        proc = MagicMock()
        proc.stdout = "302|0"
        proc.returncode = 0
        run.return_value = proc
        result = send_request_curl(
            "http://10.10.10.20/WEB-INF/web.xml",
            method="GET",
            timeout=2.0,
            headers={"User-Agent": "TelemetryCollector/9.7"},
        )
    assert result.outcome == "response"
    assert result.status_code == 302
    assert result.evidence.get("transport") == "curl"
