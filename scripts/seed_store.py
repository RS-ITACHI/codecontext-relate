"""Seed the persistent Relate store (./store/codecontext) for demo & submission."""

from pathlib import Path
from codecontext.graph_store import CodeContextStore
from codecontext.ingestor import ingest_knowledge_bundle, ingest_python_repo

ROOT = Path(__file__).resolve().parent.parent

with CodeContextStore(ROOT / "store" / "codecontext") as store:
    store.clear()
    repo_stats = ingest_python_repo(store, ROOT / "sample_repo")
    kb_stats = ingest_knowledge_bundle(store, ROOT / "sample_repo" / "knowledge_bundle.json")
    print("Seeded Relate persistent store at ./store/codecontext")
    print("Repo ingested:", repo_stats)
    print("Knowledge ingested:", kb_stats)
    print("Total stats:", store.stats())
