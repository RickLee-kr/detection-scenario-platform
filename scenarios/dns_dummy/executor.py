"""DNS dummy executor — mock protocol I/O, Event Store writes only."""

from __future__ import annotations

from dsp.engine.scenario_engine import RunContext, TargetSet
from dsp.protocols.dns import DnsClient, build_dns_events


def run(
    ctx: RunContext,
    targets: TargetSet,
    config: dict | None = None,
    scenario_id: str = "dns_dummy",
) -> None:
    """Execute mock DNS queries and persist protocol events."""
    params = config or {}
    query_count = int(params.get("query_count", 5))
    resolver = params.get("resolver") or (targets.hosts[0] if targets.hosts else "10.10.10.20")
    source = "dry_run" if ctx.dry_run else "local"

    client = DnsClient(dry_run=True, mock=True)

    mock_fqdns = [
        "host1.lab.example",
        "host2.lab.example",
        "host3.lab.example",
        "host4.lab.example",
        "timeout.lab.example",
    ]

    for i in range(min(query_count, len(mock_fqdns))):
        if ctx.cancelled:
            break
        fqdn = mock_fqdns[i]
        query = client.make_query(resolver, fqdn)
        outcome = client._default_mock_outcome(fqdn)
        result = client.query(resolver, fqdn, mock_outcome=outcome)
        for event in build_dns_events(
            run_id=ctx.run_id,
            scenario_id=scenario_id,
            query=query,
            result=result,
            source=source,
        ):
            ctx.event_store.append(event)
