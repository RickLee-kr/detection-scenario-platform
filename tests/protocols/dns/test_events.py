"""DNS event mapping unit tests."""

from __future__ import annotations

from dsp.protocols.dns import (
    DNS_QUERY_CREATED,
    DNS_QUERY_SENT,
    DNS_RESPONSE_RECEIVED,
    DNS_TIMEOUT,
    build_dns_events,
    map_outcome_to_event,
)
from dsp.protocols.dns.client import DnsClient
from dsp.protocols.types import DnsQuery


def test_map_outcome_to_event():
    assert map_outcome_to_event("response") == (DNS_RESPONSE_RECEIVED, "response")
    assert map_outcome_to_event("timeout") == (DNS_TIMEOUT, "timeout")


def test_build_dns_events_response():
    client = DnsClient(dry_run=True, mock=True)
    query = client.make_query("10.10.10.20", "host.example.com")
    result = client.query("10.10.10.20", "host.example.com")
    events = build_dns_events(
        run_id="run1",
        scenario_id="dns_dummy",
        query=query,
        result=result,
    )
    event_names = [e.event for e in events]
    assert event_names == [DNS_QUERY_CREATED, DNS_QUERY_SENT, DNS_RESPONSE_RECEIVED]
    assert events[1].status == "sent"
    assert events[2].status == "response"


def test_build_dns_events_timeout():
    client = DnsClient(dry_run=True, mock=True)
    query = DnsQuery(fqdn="timeout.test", resolver="10.10.10.20")
    result = client.query("10.10.10.20", "timeout.test", mock_outcome="timeout")
    events = build_dns_events(
        run_id="run1",
        scenario_id="dns_dummy",
        query=query,
        result=result,
    )
    assert events[-1].event == DNS_TIMEOUT
    assert events[-1].status == "timeout"
