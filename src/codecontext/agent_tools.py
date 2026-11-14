"""Agentic multi-hop Cypher reasoning tools backed by Relate."""

from __future__ import annotations

import time
from typing import Any

from codecontext.graph_store import CodeContextStore


def blast_radius(store: CodeContextStore, target: str) -> dict[str, Any]:
    """Find callers, governed decisions, incidents, and rules connected to a symbol."""
    t0 = time.perf_counter()
    cypher_callers = """
    MATCH (caller:Symbol)-[:CALLS*1..3]->(target:Symbol)
    WHERE target.name = $target OR target.fqn CONTAINS $target
    OPTIONAL MATCH (f:File)-[:DEFINES]->(caller)
    RETURN DISTINCT target.fqn AS target, caller.fqn AS caller, caller.kind AS kind, f.path AS file
    """
    callers = store.execute(cypher_callers, {"target": target})

    cypher_context = """
    MATCH (target:Symbol)
    WHERE target.name = $target OR target.fqn CONTAINS $target
    OPTIONAL MATCH (d:Decision)-[:GOVERNS]->(target)
    OPTIONAL MATCH (i:Incident)-[:CAUSED_BY]->(target)
    OPTIONAL MATCH (r:Rule)-[:APPLIES_TO]->(target)
    RETURN target.fqn AS target,
           collect(DISTINCT d.id + ': ' + d.title) AS decisions,
           collect(DISTINCT i.id + ' (' + i.severity + '): ' + i.title) AS incidents,
           collect(DISTINCT r.id + ' [' + r.level + ']: ' + r.constraint) AS rules
    """
    context = store.execute(cypher_context, {"target": target})
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "target": target,
        "callers": callers,
        "context": context,
        "cypher": cypher_callers.strip(),
        "elapsed_ms": elapsed_ms,
    }


def why_exists(store: CodeContextStore, target: str) -> dict[str, Any]:
    """Trace Decisions and Incidents explaining why a symbol or file exists."""
    t0 = time.perf_counter()
    cypher = """
    MATCH (d:Decision)-[:GOVERNS]->(n)
    WHERE n.name = $target OR n.fqn CONTAINS $target OR n.path CONTAINS $target
    OPTIONAL MATCH (i:Incident)-[:MITIGATED_BY]->(d)
    RETURN DISTINCT d.id AS decision_id, d.title AS title, d.rationale AS rationale,
           d.status AS status, collect(DISTINCT i.id + ': ' + i.root_cause) AS related_incidents
    """
    rows = store.execute(cypher, {"target": target})
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "target": target,
        "decisions": rows,
        "cypher": cypher.strip(),
        "elapsed_ms": elapsed_ms,
    }


def incident_root_cause(store: CodeContextStore, incident_id: str | None = None) -> dict[str, Any]:
    """Return full connected trace for an incident (or all incidents)."""
    t0 = time.perf_counter()
    if incident_id:
        cypher = """
        MATCH (i:Incident {id: $id})
        OPTIONAL MATCH (i)-[:CAUSED_BY]->(s:Symbol)<-[:DEFINES]-(f:File)
        OPTIONAL MATCH (i)-[:MITIGATED_BY]->(d:Decision)
        RETURN i.id AS id, i.title AS title, i.severity AS severity,
               i.root_cause AS root_cause, i.fix AS fix,
               collect(DISTINCT s.fqn) AS symbols,
               collect(DISTINCT f.path) AS files,
               collect(DISTINCT d.id + ': ' + d.title) AS mitigating_decisions
        """
        rows = store.execute(cypher, {"id": incident_id})
    else:
        cypher = """
        MATCH (i:Incident)
        OPTIONAL MATCH (i)-[:CAUSED_BY]->(s:Symbol)
        OPTIONAL MATCH (i)-[:MITIGATED_BY]->(d:Decision)
        RETURN i.id AS id, i.title AS title, i.severity AS severity,
               i.root_cause AS root_cause, i.fix AS fix,
               collect(DISTINCT s.name) AS symbols,
               collect(DISTINCT d.id) AS mitigating_decisions
        ORDER BY i.id
        """
        rows = store.execute(cypher)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    return {"incidents": rows, "cypher": cypher.strip(), "elapsed_ms": elapsed_ms}


def record_agent_memory(
    store: CodeContextStore,
    decision_id: str,
    title: str,
    rationale: str,
    targets: list[str] | None = None,
) -> dict[str, Any]:
    """Persist a new architectural Decision from an AI agent directly into Relate."""
    store.execute(
        """
        MERGE (d:Decision {id: $id})
        SET d.title = $title, d.rationale = $rationale, d.status = 'accepted', d.date = '2026-11-15'
        """,
        {"id": decision_id, "title": title, "rationale": rationale},
    )
    linked = 0
    for t in targets or []:
        rows = store.execute(
            """
            MATCH (d:Decision {id: $id}), (s:Symbol)
            WHERE s.name = $t OR s.fqn CONTAINS $t
            MERGE (d)-[:GOVERNS]->(s)
            RETURN count(*) AS c
            """,
            {"id": decision_id, "t": t},
        )
        if rows:
            linked += int(rows[0].get("c", 0))
    return {"saved": decision_id, "linked_symbols": linked}


def answer_with_context(store: CodeContextStore, question: str) -> dict[str, Any]:
    """Route a natural-language question to deterministic multi-hop Relate Cypher queries."""
    q = question.lower().strip()

    # Extract candidate symbol/keyword tokens
    symbols = [r["name"] for r in store.execute("MATCH (s:Symbol) RETURN DISTINCT s.name AS name")]
    matched_symbol = next((s for s in symbols if s.lower() in q), None)

    if any(k in q for k in ("blast", "break", "impact", "depend", "caller", "change")) and matched_symbol:
        res = blast_radius(store, matched_symbol)
        caller_names = [c["caller"] for c in res["callers"]]
        ctx = res["context"][0] if res["context"] else {}
        summary = (
            f"Changing `{matched_symbol}` affects {len(caller_names)} upstream caller(s): "
            f"{', '.join(caller_names) or 'none'}. "
            f"Rules: {', '.join(ctx.get('rules', [])) or 'none'}. "
            f"Past incidents: {', '.join(ctx.get('incidents', [])) or 'none'}."
        )
        return {"mode": "blast_radius", "answer": summary, "data": res}

    if any(k in q for k in ("why", "decision", "adr", "rationale")) and matched_symbol:
        res = why_exists(store, matched_symbol)
        decs = res["decisions"]
        if decs:
            summary = " | ".join(f"{d['decision_id']} ({d['title']}): {d['rationale']}" for d in decs)
        else:
            summary = f"No explicit Decision node linked to `{matched_symbol}` yet."
        return {"mode": "why_exists", "answer": summary, "data": res}

    if any(k in q for k in ("incident", "outage", "bug", "sev", "root cause")):
        res = incident_root_cause(store)
        incs = res["incidents"]
        summary = f"Found {len(incs)} recorded incident(s) in Relate: " + "; ".join(
            f"{i['id']} [{i['severity']}] {i['title']} -> root cause: {i['root_cause']}" for i in incs
        )
        return {"mode": "incident_root_cause", "answer": summary, "data": res}

    if matched_symbol:
        res = blast_radius(store, matched_symbol)
        return {
            "mode": "symbol_lookup",
            "answer": f"Connected graph context for `{matched_symbol}` retrieved in {res['elapsed_ms']} ms.",
            "data": res,
        }

    # Fallback: return graph overview
    stats = store.stats()
    return {
        "mode": "overview",
        "answer": (
            f"Relate store has {stats['total_nodes']} nodes and {stats['total_relationships']} relationships. "
            f"Try asking about blast radius, why a symbol exists, or incident root causes."
        ),
        "data": stats,
    }
