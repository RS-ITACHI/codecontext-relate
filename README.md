# CodeContext Graph — Agentic Codebase & Incident Memory (Relate by Neo4j)

> **Built for the Relate by Neo4j Hackathon**  
> **GitHub Topics:** `relate`, `relate-neo4j-hackathon`

## Why This Exists
AI coding agents often hallucinate or break invariants because they only see flat text snippets—not **connected facts** (who calls what, which ADR governs a function, and which SEV-1 incident a guardrail prevents).

**CodeContext Graph** uses **Relate** (`relate-db`) as an embedded, zero-server property-graph memory layer that connects:
- `File` —[`DEFINES`]→ `Symbol` —[`CALLS`]→ `Symbol`
- `Decision` (ADR) —[`GOVERNS`]→ `Symbol` / `File`
- `Incident` —[`CAUSED_BY`]→ `Symbol` and `Incident` —[`MITIGATED_BY`]→ `Decision`
- `Rule` —[`APPLIES_TO`]→ `Symbol`

## How Relate Is Used (Mode & Persistence)
- **Relate Mode:** **Persistent Directory Store** (`./store/codecontext`), committed directly in this repository so judges can inspect the live graph immediately.
- **Engine:** `relate-db` (`import relate`, PEP 249 DB-API + native Rust Cypher engine) running embedded in-process with zero external database servers.
- **Agentic Interfaces:**
  1. **Multi-hop Cypher Reasoning Tools** (`src/codecontext/agent_tools.py`): `blast_radius`, `why_exists`, `incident_root_cause`, `record_agent_memory`.
  2. **MCP Server** (`src/codecontext/mcp_server.py`): Stdio Model Context Protocol server so any AI agent (Cursor, Claude, Antigravity) can query and persist decisions in Relate.
  3. **Interactive Web Dashboard & Cypher Playground** (`src/codecontext/web.py`): Visualizes the connected graph and executes live Cypher queries.

## Quickstart

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Seed the persistent Relate store (already pre-seeded at ./store/codecontext)
$env:PYTHONPATH="src"
python scripts/seed_store.py

# 3. Run tests
pytest -v

# 4. Launch the interactive Web UI & Cypher Playground
uvicorn codecontext.web:app --reload
# Open http://127.0.0.1:8000
```

## MCP Configuration (for AI Coding Agents)
```json
{
  "mcpServers": {
    "codecontext-relate": {
      "command": "python",
      "args": ["-m", "codecontext.mcp_server"],
      "env": { "PYTHONPATH": "src", "CODECONTEXT_DB": "./store/codecontext" }
    }
  }
}
```
