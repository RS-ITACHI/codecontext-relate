"""Benchmark embedded Relate (Neo4j) multi-hop query latency and ingestion speed."""

from __future__ import annotations

import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from codecontext.agent_loop import review_pr_diff
from codecontext.agent_tools import blast_radius, why_exists
from codecontext.graph_store import CodeContextStore
from codecontext.ingestor import ingest_knowledge_bundle, ingest_python_repo


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_dir = Path(tmp) / "bench_store"

        t0 = time.perf_counter()
        with CodeContextStore(db_dir) as store:
            r1 = ingest_python_repo(store, ROOT / "sample_repo")
            r2 = ingest_python_repo(store, ROOT / "src" / "codecontext")
            kb = ingest_knowledge_bundle(store, ROOT / "sample_repo" / "knowledge_bundle.json")
            stats = store.stats()
        ingest_ms = (time.perf_counter() - t0) * 1000

        # Re-open persisted store from disk and benchmark 50 multi-hop queries
        latencies_ms: list[float] = []
        with CodeContextStore(db_dir) as store:
            for _ in range(25):
                q0 = time.perf_counter()
                blast_radius(store, "verify_idempotency_key")
                latencies_ms.append((time.perf_counter() - q0) * 1000)

                q1 = time.perf_counter()
                why_exists(store, "verify_idempotency_key")
                latencies_ms.append((time.perf_counter() - q1) * 1000)

            d0 = time.perf_counter()
            diff_res = review_pr_diff(
                store,
                "--- a/sample_repo/payments.py\n+++ b/sample_repo/payments.py\n"
                "@@ -12,2 +12,2 @@ def verify_idempotency_key(key: str):\n"
                "+    # bypass idempotency check\n",
            )
            diff_ms = (time.perf_counter() - d0) * 1000

        latencies_ms.sort()
        p50 = statistics.median(latencies_ms)
        p95 = latencies_ms[int(len(latencies_ms) * 0.95) - 1]
        print(f"Ingested: {r1['files'] + r2['files']} files, {r1['symbols'] + r2['symbols']} symbols, {kb}")
        print(f"Store stats: {stats['total_nodes']} nodes, {stats['total_relationships']} relationships")
        print(f"Cold ingest time: {ingest_ms:.2f} ms")
        print(f"Multi-hop Cypher (50 runs): p50={p50:.2f} ms, p95={p95:.2f} ms")
        print(f"Full PR Diff Guardrail: {diff_ms:.2f} ms -> {diff_res['verdict']} (Risk {diff_res['risk_score']}/100)")


if __name__ == "__main__":
    main()
