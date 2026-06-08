"""DNS transport dummy executor — live UDP/53 or mock fallback."""

from __future__ import annotations

from dsp.engine.scenario_engine import RunContext, TargetSet
from dsp.protocols.dns import DnsClient, build_dns_events


def run(
    ctx: RunContext,
    targets: TargetSet,
    config: dict | None = None,
    scenario_id: str = "dns_transport_dummy",
) -> None:
    """Execute DNS queries and persist transport events to Event Store."""
    params = config or {}
    query_count = int(params.get("query_count", 1))
    resolver = params.get("resolver") or (targets.hosts[0] if targets.hosts else "10.10.10.20")
    source = "dry_run" if ctx.dry_run else "local"
    mode = "mock" if ctx.dry_run else "live"

    client = DnsClient(mode=mode)

    fqdns = [
        "transport.lab.example",
    ]

    for i in range(min(query_count, len(fqdns))):
        if ctx.cancelled:
            break
        fqdn = fqdns[i]
        query = client.make_query(resolver, fqdn)
        if mode == "mock":
            result = client.query(resolver, fqdn, mock_outcome="response")
        else:
            result = client.query(resolver, fqdn)
        for event in build_dns_events(
            run_id=ctx.run_id,
            scenario_id=scenario_id,
            query=query,
            result=result,
            source=source,
        ):
            ctx.event_store.append(event)
