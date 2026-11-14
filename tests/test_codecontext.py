"""End-to-end tests for CodeContext Graph (Relate by Neo4j)."""

from pathlib import Path

from codecontext.agent_tools import (
    answer_with_context,
    blast_radius,
    incident_root_cause,
    record_agent_memory,
    why_exists,
)
from codecontext.graph_store import CodeContextStore
from codecontext.ingestor import ingest_knowledge_bundle, ingest_python_repo
from codecontext.mcp_server import handle_request

ROOT = Path(__file__).resolve().parent.parent


def test_persistent_store_and_multihop_reasoning(tmp_path: Path) -> None:
    db_dir = tmp_path / "relate_store"

    with CodeContextStore(db_dir) as store:
        repo_res = ingest_python_repo(store, ROOT / "sample_repo")
        assert repo_res["files"] == 2
        assert repo_res["symbols"] >= 5
        assert repo_res["call_edges"] >= 2

        kb_res = ingest_knowledge_bundle(store, ROOT / "sample_repo" / "knowledge_bundle.json")
        assert kb_res == {"decisions": 3, "incidents": 2, "rules": 2}

    # Re-open persisted Relate directory store to verify durability across restarts
    with CodeContextStore(db_dir) as store:
        br = blast_radius(store, "verify_idempotency_key")
        callers = {c["caller"] for c in br["callers"]}
        assert any("process_checkout" in c for c in callers)
        assert any("handle_payment_webhook" in c for c in callers)

        why = why_exists(store, "verify_idempotency_key")
        assert any(d["decision_id"] == "ADR-001" for d in why["decisions"])

        inc = incident_root_cause(store, "INC-204")
        assert inc["incidents"][0]["severity"] == "SEV-1"

        mem = record_agent_memory(
            store,
            "ADR-004",
            "Log Rejected Webhooks",
            "Audit all failed HMAC checks.",
            ["verify_webhook_signature"],
        )
        assert mem["linked_symbols"] >= 1

        qa = answer_with_context(store, "What is the blast radius of verify_idempotency_key?")
        assert qa["mode"] == "blast_radius"
        assert "process_checkout" in qa["answer"]


def test_mcp_server_tools() -> None:
    with CodeContextStore(":memory:") as store:
        ingest_python_repo(store, ROOT / "sample_repo")
        ingest_knowledge_bundle(store, ROOT / "sample_repo" / "knowledge_bundle.json")

        init_resp = handle_request(store, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert init_resp["result"]["serverInfo"]["name"] == "codecontext-relate-mcp"

        tools_resp = handle_request(store, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in tools_resp["result"]["tools"]}
        assert {"blast_radius", "why_exists", "incident_root_cause", "query_cypher", "record_memory"} <= names

        call_resp = handle_request(
            store,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "why_exists", "arguments": {"target": "calculate_settlement_fee"}},
            },
        )
        assert "ADR-002" in call_resp["result"]["content"][0]["text"]
