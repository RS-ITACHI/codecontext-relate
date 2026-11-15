"""FastAPI web dashboard & Cypher playground for CodeContext Graph."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from codecontext.agent_loop import review_code_change
from codecontext.agent_tools import (
    answer_with_context,
    blast_radius,
    incident_root_cause,
    record_agent_memory,
    why_exists,
)
from codecontext.graph_store import CodeContextStore

STATIC_DIR = Path(__file__).parent / "static"


def get_store() -> CodeContextStore:
    db_path = os.environ.get("CODECONTEXT_DB", "./store/codecontext")
    return CodeContextStore(db_path)


app = FastAPI(title="CodeContext Graph (Relate by Neo4j)")


class AskRequest(BaseModel):
    question: str


class CypherRequest(BaseModel):
    cypher: str


class MemoryRequest(BaseModel):
    decision_id: str
    title: str
    rationale: str
    targets: list[str] = []


class ReviewRequest(BaseModel):
    symbol: str
    proposed_change: str


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/api/stats")
def api_stats() -> dict:
    with get_store() as store:
        return store.stats()


@app.get("/api/graph")
def api_graph() -> dict:
    with get_store() as store:
        nodes = store.execute(
            "MATCH (n) RETURN elementId(n) AS id, labels(n)[0] AS label, properties(n) AS props LIMIT 150"
        )
        edges = store.execute(
            "MATCH (a)-[r]->(b) RETURN elementId(a) AS source, elementId(b) AS target, type(r) AS type LIMIT 250"
        )
        return {"nodes": nodes, "edges": edges}


@app.post("/api/ask")
def api_ask(req: AskRequest) -> dict:
    with get_store() as store:
        return answer_with_context(store, req.question)


@app.post("/api/cypher")
def api_cypher(req: CypherRequest) -> dict:
    with get_store() as store:
        try:
            return store.execute_with_meta(req.cypher)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/blast-radius/{target}")
def api_blast_radius(target: str) -> dict:
    with get_store() as store:
        return blast_radius(store, target)


@app.get("/api/why/{target}")
def api_why(target: str) -> dict:
    with get_store() as store:
        return why_exists(store, target)


@app.get("/api/incidents")
def api_incidents() -> dict:
    with get_store() as store:
        return incident_root_cause(store)


@app.post("/api/memory")
def api_memory(req: MemoryRequest) -> dict:
    with get_store() as store:
        return record_agent_memory(store, req.decision_id, req.title, req.rationale, req.targets)


@app.post("/api/review-change")
def api_review_change(req: ReviewRequest) -> dict:
    with get_store() as store:
        return review_code_change(store, req.symbol, req.proposed_change)
