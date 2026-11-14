"""Minimal stdio MCP (Model Context Protocol) server exposing Relate graph memory tools."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from codecontext.agent_tools import (
    blast_radius,
    incident_root_cause,
    record_agent_memory,
    why_exists,
)
from codecontext.graph_store import CodeContextStore

TOOLS = [
    {
        "name": "blast_radius",
        "description": "Find upstream callers, rules, and past incidents for a code symbol using Relate.",
        "inputSchema": {
            "type": "object",
            "properties": {"target": {"type": "string", "description": "Function, class, or method name"}},
            "required": ["target"],
        },
    },
    {
        "name": "why_exists",
        "description": "Trace Architecture Decisions (ADRs) and Incidents explaining why a symbol/file exists.",
        "inputSchema": {
            "type": "object",
            "properties": {"target": {"type": "string", "description": "Symbol or file name"}},
            "required": ["target"],
        },
    },
    {
        "name": "incident_root_cause",
        "description": "Inspect connected incident root causes, affected symbols, and mitigating decisions.",
        "inputSchema": {
            "type": "object",
            "properties": {"incident_id": {"type": "string", "description": "Optional incident ID"}},
        },
    },
    {
        "name": "query_cypher",
        "description": "Run a read-only Cypher query against the embedded Relate graph store.",
        "inputSchema": {
            "type": "object",
            "properties": {"cypher": {"type": "string"}},
            "required": ["cypher"],
        },
    },
    {
        "name": "record_memory",
        "description": "Persist a new architectural Decision into the Relate store.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "decision_id": {"type": "string"},
                "title": {"type": "string"},
                "rationale": {"type": "string"},
                "targets": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["decision_id", "title", "rationale"],
        },
    },
]


def handle_request(store: CodeContextStore, req: dict[str, Any]) -> dict[str, Any] | None:
    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "codecontext-relate-mcp", "version": "1.0.0"},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "blast_radius":
            out = blast_radius(store, args["target"])
        elif name == "why_exists":
            out = why_exists(store, args["target"])
        elif name == "incident_root_cause":
            out = incident_root_cause(store, args.get("incident_id"))
        elif name == "query_cypher":
            out = store.execute_with_meta(args["cypher"])
        elif name == "record_memory":
            out = record_agent_memory(
                store,
                args["decision_id"],
                args["title"],
                args["rationale"],
                args.get("targets"),
            )
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {name}"},
            }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": json.dumps(out, indent=2)}]},
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    db_path = os.environ.get("CODECONTEXT_DB", "./store/codecontext")
    with CodeContextStore(db_path) as store:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            req = json.loads(line)
            resp = handle_request(store, req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    main()
