"""Persistent Relate graph store wrapper for CodeContext Graph."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import relate


class CodeContextStore:
    """Manages a persistent Relate embedded graph database for codebase & incident memory.

    Mode: Persistent directory store (or ``:memory:`` for ephemeral tests).
    """

    def __init__(self, db_path: str | Path = "./store/codecontext") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = relate.connect(self.db_path)

    def close(self) -> None:
        """Close the underlying Relate connection."""
        self.conn.close()

    def __enter__(self) -> CodeContextStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def execute(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a Cypher statement and return rows as plain dicts."""
        cur = self.conn.execute(cypher, params or {})
        return [row.data() for row in cur]

    def execute_with_meta(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a Cypher query and return rows plus column names."""
        cur = self.conn.execute(cypher, params or {})
        rows = [row.data() for row in cur]
        keys = list(rows[0].keys()) if rows else []
        return {"columns": keys, "rows": rows, "count": len(rows)}

    def stats(self) -> dict[str, int]:
        """Return node and relationship counts by label/type."""
        node_rows = self.execute(
            "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count"
        )
        rel_rows = self.execute(
            "MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) AS count"
        )
        return {
            "nodes": {r["label"]: r["count"] for r in node_rows if r["label"]},
            "relationships": {r["rel_type"]: r["count"] for r in rel_rows if r["rel_type"]},
            "total_nodes": sum(r["count"] for r in node_rows),
            "total_relationships": sum(r["count"] for r in rel_rows),
        }

    def clear(self) -> None:
        """Delete all nodes and relationships in the store."""
        self.conn.execute("MATCH (n) DETACH DELETE n")
