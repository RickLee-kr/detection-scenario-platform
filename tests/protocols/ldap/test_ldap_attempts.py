"""LDAP attempt planning unit tests."""

from __future__ import annotations

from dsp.protocols.ldap.attempts import DEFAULT_SAFE_FILTERS, plan_ldap_enumeration


def test_plan_includes_connection_bind_and_searches():
    plans = plan_ldap_enumeration(
        ["10.10.10.30"],
        max_queries_per_host=2,
        ports=(389,),
    )
    action_types = [p.action_type for p in plans]
    assert action_types.count("connection") == 1
    assert action_types.count("bind") == 1
    assert action_types.count("search") == 3  # base DN + 2 queries
    search_filters = [p.search_filter for p in plans if p.action_type == "search"]
    assert search_filters[0] == "(objectClass=*)"
    assert all(f in DEFAULT_SAFE_FILTERS for f in search_filters)
