"""DGA scenario E2E tests."""

from __future__ import annotations

import json
import socket
import struct
from unittest.mock import MagicMock, patch

import pytest

from dsp.protocols.dns.client import encode_qname
from dsp.runner import RunManager

DGA_TEST_PARAMS = {
    "dga": {
        "phase1_count": 3,
        "phase2_count": 2,
        "effective_tld": "xdr.ooo",
        "resolver": "10.10.10.20",
    }
}


def _build_dns_response(txn_id: int, *, rcode: int = 0, ancount: int = 1) -> bytes:
    flags = 0x8180 | rcode
    header = struct.pack("!HHHHHH", txn_id, flags, 1, ancount, 0, 0)
    question = encode_qname("test.xdr.ooo") + struct.pack("!HH", 1, 1)
    answer = b""
    if ancount:
        answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 300, 4) + bytes([10, 10, 10, 1])
    return header + question + answer


@pytest.fixture
def mock_dga_dns_socket():
    response_holder: dict[str, int | str] = {}

    def make_socket(*args, **kwargs):
        sock = MagicMock()

        def sendto(data, addr):
            response_holder["txn_id"] = struct.unpack("!H", data[:2])[0]
            qname_end = data.index(b"\x00", 12)
            labels = []
            pos = 12
            while pos < qname_end:
                length = data[pos]
                pos += 1
                labels.append(data[pos : pos + length].decode("ascii"))
                pos += length
            response_holder["fqdn"] = ".".join(labels)

        def recvfrom(size):
            txn_id = int(response_holder.get("txn_id", 0))
            fqdn = str(response_holder.get("fqdn", ""))
            rcode = 3 if ".live." not in fqdn else 0
            ancount = 0 if rcode == 3 else 1
            return (_build_dns_response(txn_id, rcode=rcode, ancount=ancount), ("10.10.10.20", 53))

        sock.sendto.side_effect = sendto
        sock.recvfrom.side_effect = recvfrom
        return sock

    with patch("socket.socket", side_effect=make_socket):
        yield


def test_dga_dry_run_e2e(tmp_runs_dir):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["dga"],
        target_net="10.10.10.0/24",
        dry_run=True,
        scenario_params=DGA_TEST_PARAMS,
    )

    assert run.status.value == "completed"
    assert exit_code == 0
    assert (run_dir / "events.db").exists()
    assert (run_dir / "validation.json").exists()
    assert (run_dir / "report.md").exists()

    validation = json.loads((run_dir / "validation.json").read_text())
    result = validation["results"][0]
    assert result["scenario_id"] == "dga"
    assert result["decision"] == "success"
    assert result["metrics"]["dga_domain_generated_count"] == 5
    assert result["metrics"]["dga_nxdomain_observed_count"] == 3
    assert result["metrics"]["dga_resolved_observed_count"] == 2

    report = (run_dir / "report.md").read_text()
    assert "## DGA Details" in report
    assert "dga_domain_generated_count" in report
    assert "xdr.ooo" in report
    assert ".live.xdr.ooo" in report or "live" in report


def test_dga_live_e2e(tmp_runs_dir, mock_dga_dns_socket):
    manager = RunManager(runs_dir=tmp_runs_dir)
    run, run_dir, exit_code = manager.run(
        scenario_ids=["dga"],
        target_net="10.10.10.0/24",
        dry_run=False,
        scenario_params=DGA_TEST_PARAMS,
    )

    assert run.status.value == "completed"
    assert exit_code == 0

    validation = json.loads((run_dir / "validation.json").read_text())
    result = validation["results"][0]
    assert result["decision"] == "success"
    assert result["metrics"]["dga_nxdomain_observed_count"] == 3
    assert result["metrics"]["dga_resolved_observed_count"] == 2


def test_dga_plugins_list():
    from dsp.plugins import PluginLoader, PluginStatus

    registry = PluginLoader().discover_and_load()
    record = registry.get("dga")
    assert record is not None
    assert record.status == PluginStatus.ACTIVE
