"""DNS Tunnel executor — chunk generation, FQDN encoding, UDP/53 transmission."""

from __future__ import annotations

import time
import uuid

from dsp.engine.scenario_engine import RunContext, TargetSet
from dsp.protocols.dns import DnsClient, build_dns_events
from dsp.protocols.dns.tunnel import (
    CHUNK_SIZE_DEFAULT,
    PAYLOAD_MB_DEFAULT,
    TUNNEL_DOMAIN_DEFAULT,
    build_tunnel_fqdn,
    chunk_to_b32_label,
    iter_payload_chunks,
    plan_chunk_count,
)
from dsp.protocols.dns.tunnel_events import (
    build_tunnel_chunk_created_event,
    build_tunnel_completed_event,
    build_tunnel_query_sent_event,
    build_tunnel_started_event,
)
from dsp.protocols.dns.volume_profiles import apply_volume_profile


def select_tunnel_targets(
    targets: TargetSet,
    config: dict,
    *,
    max_hosts: int = 2,
) -> list[str]:
    """Select up to max_hosts alive targets without resolver discovery."""
    if config.get("targets"):
        return [str(t) for t in config["targets"]][:max_hosts]
    if targets.hosts:
        return list(targets.hosts)[:max_hosts]
    return ["10.10.10.20"]


def run(
    ctx: RunContext,
    targets: TargetSet,
    config: dict | None = None,
    scenario_id: str = "dns_tunnel",
) -> None:
    """Generate tunnel chunks, transmit DNS queries, append events to Event Store."""
    params = apply_volume_profile(config or {}, dry_run=ctx.dry_run)
    payload_mb = float(params.get("payload_mb", PAYLOAD_MB_DEFAULT))
    chunk_size = int(params.get("chunk_size", CHUNK_SIZE_DEFAULT))
    domain = str(params.get("domain", TUNNEL_DOMAIN_DEFAULT))
    max_hosts = int(params.get("max_hosts", 2))
    max_chunks = params.get("max_chunks")
    source = "dry_run" if ctx.dry_run else "local"
    mode = "mock" if ctx.dry_run else "live"
    client = DnsClient(mode=mode, timeout=0.05)

    host_targets = select_tunnel_targets(targets, params, max_hosts=max_hosts)
    total_planned = plan_chunk_count(payload_mb, chunk_size)
    if max_chunks is not None:
        total_planned = min(total_planned, int(max_chunks))

    session_id = uuid.uuid4().hex[:6]
    sample_fqdns: list[str] = []

    for target in host_targets:
        if ctx.cancelled:
            break

        started_evidence = {
            "session_id": session_id,
            "payload_mb": payload_mb,
            "chunk_size": chunk_size,
            "domain": domain,
            "planned_chunks": total_planned,
            "mode": mode,
        }
        ctx.event_store.append(
            build_tunnel_started_event(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                target=target,
                source=source,
                evidence=started_evidence,
            )
        )

        chunks_sent = 0
        bytes_encoded = 0
        t0 = time.monotonic()

        for seq, chunk in enumerate(iter_payload_chunks(payload_mb, chunk_size), start=1):
            if ctx.cancelled:
                break
            if seq > total_planned:
                break

            b32_label = chunk_to_b32_label(chunk)
            fqdn = build_tunnel_fqdn(seq, b32_label, domain)
            if len(sample_fqdns) < 3:
                sample_fqdns.append(fqdn)

            chunk_evidence = {
                "session_id": session_id,
                "seq": seq,
                "chunk_bytes": len(chunk),
                "label_length": len(b32_label),
                "domain": domain,
            }
            ctx.event_store.append(
                build_tunnel_chunk_created_event(
                    run_id=ctx.run_id,
                    scenario_id=scenario_id,
                    target=target,
                    fqdn=fqdn,
                    source=source,
                    evidence=chunk_evidence,
                )
            )

            query = client.make_query(target, fqdn)
            if mode == "mock":
                result = client.query(target, fqdn, mock_outcome="response")
            else:
                result = client.query(target, fqdn)

            query_evidence = {
                "session_id": session_id,
                "seq": seq,
                "qtype": query.qtype,
                "resolver": target,
                "port": query.port,
                "query_id": result.query_id,
                "outcome": result.outcome,
                "label_length": len(b32_label),
            }
            ctx.event_store.append(
                build_tunnel_query_sent_event(
                    run_id=ctx.run_id,
                    scenario_id=scenario_id,
                    target=target,
                    fqdn=fqdn,
                    source=source,
                    evidence=query_evidence,
                )
            )

            for event in build_dns_events(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                query=query,
                result=result,
                source=source,
                include_created=False,
            ):
                ctx.event_store.append(event)

            chunks_sent += 1
            bytes_encoded += len(chunk)

        elapsed = round(time.monotonic() - t0, 3)
        completed_evidence = {
            "session_id": session_id,
            "chunks_sent": chunks_sent,
            "bytes_encoded": bytes_encoded,
            "duration_sec": elapsed,
            "targets": host_targets,
            "sample_fqdns": sample_fqdns,
            "domain": domain,
        }
        ctx.event_store.append(
            build_tunnel_completed_event(
                run_id=ctx.run_id,
                scenario_id=scenario_id,
                target=target,
                source=source,
                evidence=completed_evidence,
            )
        )
