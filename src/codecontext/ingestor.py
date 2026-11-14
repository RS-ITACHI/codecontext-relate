"""AST-based codebase & ADR/Incident knowledge ingestor for Relate."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from codecontext.graph_store import CodeContextStore


def _extract_calls(node: ast.AST) -> list[str]:
    """Return function/method names called inside an AST node."""
    calls: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                calls.append(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                calls.append(child.func.attr)
    return sorted(set(calls))


def ingest_python_repo(store: CodeContextStore, repo_root: str | Path) -> dict[str, int]:
    """Parse Python files in ``repo_root`` and upsert File/Symbol/Call nodes into Relate."""
    root = Path(repo_root).resolve()
    files_count = 0
    symbols_count = 0
    calls_to_link: list[tuple[str, str]] = []

    for py_file in sorted(root.rglob("*.py")):
        if any(part.startswith(".") or part in {"__pycache__", "node_modules", ".venv"} for part in py_file.parts):
            continue
        rel_path = py_file.relative_to(root).as_posix()
        source = py_file.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(source, filename=rel_path)
        except SyntaxError:
            continue

        files_count += 1
        module_doc = ast.get_docstring(tree) or ""
        store.execute(
            """
            MERGE (f:File {path: $path})
            SET f.language = 'python', f.lines = $lines, f.summary = $summary
            """,
            {"path": rel_path, "lines": len(source.splitlines()), "summary": module_doc[:240]},
        )

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fqn = f"{rel_path}::{node.name}"
                doc = ast.get_docstring(node) or ""
                store.execute(
                    """
                    MERGE (s:Symbol {fqn: $fqn})
                    SET s.name = $name, s.kind = 'function', s.line = $line, s.doc = $doc
                    WITH s
                    MATCH (f:File {path: $path})
                    MERGE (f)-[:DEFINES]->(s)
                    """,
                    {"fqn": fqn, "name": node.name, "line": node.lineno, "doc": doc[:240], "path": rel_path},
                )
                symbols_count += 1
                for callee in _extract_calls(node):
                    calls_to_link.append((fqn, callee))

            elif isinstance(node, ast.ClassDef):
                cls_fqn = f"{rel_path}::{node.name}"
                doc = ast.get_docstring(node) or ""
                store.execute(
                    """
                    MERGE (s:Symbol {fqn: $fqn})
                    SET s.name = $name, s.kind = 'class', s.line = $line, s.doc = $doc
                    WITH s
                    MATCH (f:File {path: $path})
                    MERGE (f)-[:DEFINES]->(s)
                    """,
                    {"fqn": cls_fqn, "name": node.name, "line": node.lineno, "doc": doc[:240], "path": rel_path},
                )
                symbols_count += 1
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        m_fqn = f"{rel_path}::{node.name}.{item.name}"
                        m_doc = ast.get_docstring(item) or ""
                        store.execute(
                            """
                            MERGE (s:Symbol {fqn: $fqn})
                            SET s.name = $name, s.kind = 'method', s.line = $line, s.doc = $doc
                            WITH s
                            MATCH (f:File {path: $path})
                            MERGE (f)-[:DEFINES]->(s)
                            """,
                            {
                                "fqn": m_fqn,
                                "name": item.name,
                                "line": item.lineno,
                                "doc": m_doc[:240],
                                "path": rel_path,
                            },
                        )
                        symbols_count += 1
                        for callee in _extract_calls(item):
                            calls_to_link.append((m_fqn, callee))

    links_count = 0
    for caller_fqn, callee_name in calls_to_link:
        rows = store.execute(
            """
            MATCH (caller:Symbol {fqn: $caller_fqn}), (callee:Symbol {name: $callee_name})
            WHERE caller.fqn <> callee.fqn
            MERGE (caller)-[:CALLS]->(callee)
            RETURN count(*) AS linked
            """,
            {"caller_fqn": caller_fqn, "callee_name": callee_name},
        )
        if rows:
            links_count += int(rows[0].get("linked", 0))

    return {"files": files_count, "symbols": symbols_count, "call_edges": links_count}


def ingest_knowledge_bundle(store: CodeContextStore, bundle_path: str | Path) -> dict[str, int]:
    """Ingest Decisions (ADRs), Incidents, and Guardrail Rules from a JSON bundle into Relate."""
    data: dict[str, Any] = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
    decisions = data.get("decisions", [])
    incidents = data.get("incidents", [])
    rules = data.get("rules", [])

    for d in decisions:
        store.execute(
            """
            MERGE (dec:Decision {id: $id})
            SET dec.title = $title, dec.rationale = $rationale, dec.status = $status, dec.date = $date
            """,
            {
                "id": d["id"],
                "title": d["title"],
                "rationale": d["rationale"],
                "status": d.get("status", "accepted"),
                "date": d.get("date", "2026-11-01"),
            },
        )
        for target in d.get("targets", []):
            store.execute(
                """
                MATCH (dec:Decision {id: $id}), (s:Symbol)
                WHERE s.name = $target OR s.fqn CONTAINS $target
                MERGE (dec)-[:GOVERNS]->(s)
                """,
                {"id": d["id"], "target": target},
            )
            store.execute(
                """
                MATCH (dec:Decision {id: $id}), (f:File)
                WHERE f.path CONTAINS $target
                MERGE (dec)-[:GOVERNS]->(f)
                """,
                {"id": d["id"], "target": target},
            )

    for inc in incidents:
        store.execute(
            """
            MERGE (i:Incident {id: $id})
            SET i.title = $title, i.severity = $severity, i.root_cause = $root_cause, i.fix = $fix
            """,
            {
                "id": inc["id"],
                "title": inc["title"],
                "severity": inc.get("severity", "SEV-2"),
                "root_cause": inc["root_cause"],
                "fix": inc["fix"],
            },
        )
        for sym in inc.get("affected_symbols", []):
            store.execute(
                """
                MATCH (i:Incident {id: $id}), (s:Symbol)
                WHERE s.name = $sym OR s.fqn CONTAINS $sym
                MERGE (i)-[:CAUSED_BY]->(s)
                """,
                {"id": inc["id"], "sym": sym},
            )
        if dec_id := inc.get("fixed_by_decision"):
            store.execute(
                """
                MATCH (i:Incident {id: $inc_id}), (dec:Decision {id: $dec_id})
                MERGE (i)-[:MITIGATED_BY]->(dec)
                """,
                {"inc_id": inc["id"], "dec_id": dec_id},
            )

    for rule in rules:
        store.execute(
            """
            MERGE (r:Rule {id: $id})
            SET r.title = $title, r.constraint = $constraint, r.level = $level
            """,
            {
                "id": rule["id"],
                "title": rule["title"],
                "constraint": rule["constraint"],
                "level": rule.get("level", "MUST"),
            },
        )
        for target in rule.get("applies_to", []):
            store.execute(
                """
                MATCH (r:Rule {id: $id}), (s:Symbol)
                WHERE s.name = $target OR s.fqn CONTAINS $target
                MERGE (r)-[:APPLIES_TO]->(s)
                """,
                {"id": rule["id"], "target": target},
            )

    return {"decisions": len(decisions), "incidents": len(incidents), "rules": len(rules)}
