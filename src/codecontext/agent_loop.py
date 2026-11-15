"""Autonomous Agentic PR / Code-Change Guardrail Reviewer backed by Relate."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Any

from codecontext.agent_tools import blast_radius, why_exists
from codecontext.graph_store import CodeContextStore


def _optional_llm_synthesis(prompt: str) -> str | None:
    """Optionally enrich the grounded Relate verdict using Gemini if GEMINI_API_KEY is set."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={api_key}"
    )
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return None


def review_code_change(
    store: CodeContextStore,
    symbol_name: str,
    proposed_change: str,
) -> dict[str, Any]:
    """Multi-step agentic guardrail that checks Relate before approving a code change."""
    br = blast_radius(store, symbol_name)
    why = why_exists(store, symbol_name)

    ctx = br["context"][0] if br["context"] else {}
    rules = [r for r in ctx.get("rules", []) if r]
    incidents = [i for i in ctx.get("incidents", []) if i]
    decisions = [d for d in ctx.get("decisions", []) if d]
    callers = [c["caller"] for c in br["callers"]]

    lower_change = proposed_change.lower()
    violations: list[str] = []

    if any("idempotency" in r.lower() for r in rules) and any(
        w in lower_change for w in ("remove", "skip", "bypass", "disable")
    ):
        violations.append("Violates RULE-01 / ADR-001 (Mandatory Idempotency Key check — caused INC-204 SEV-1).")

    if any("float" in r.lower() or "integer" in r.lower() for r in rules) and any(
        w in lower_change for w in ("float", "decimal", "round(")
    ):
        violations.append("Violates RULE-02 / ADR-002 (Integer-Cents Only — caused INC-219 SEV-2).")

    if "signature" in symbol_name.lower() and any(
        w in lower_change for w in ("==", "bypass", "skip", "disable")
    ):
        violations.append("Violates ADR-003 (Constant-Time HMAC Verification).")

    if violations:
        verdict = "BLOCKED"
    elif incidents or callers:
        verdict = "CAUTION"
    else:
        verdict = "APPROVED"

    grounded_summary = (
        f"[{verdict}] Symbol `{symbol_name}` has {len(callers)} upstream caller(s), "
        f"{len(decisions)} governing ADR(s), {len(incidents)} past incident(s), and {len(rules)} rule(s)."
    )

    llm_note = _optional_llm_synthesis(
        f"You are a senior code reviewer. Grounded Relate graph facts:\n{grounded_summary}\n"
        f"Violations: {violations}\nProposed change: {proposed_change}\n"
        f"Give a 2-sentence actionable review."
    )

    return {
        "symbol": symbol_name,
        "verdict": verdict,
        "violations": violations,
        "upstream_callers": callers,
        "decisions": decisions,
        "incidents": incidents,
        "rules": rules,
        "why_details": why["decisions"],
        "summary": llm_note or grounded_summary,
        "elapsed_ms": br["elapsed_ms"],
    }


def _extract_diff_targets(store: CodeContextStore, diff_text: str) -> tuple[list[str], list[str]]:
    """Extract changed files and impacted graph symbols from a unified git diff."""
    files = re.findall(r"^\+\+\+\s+b/(.+)$", diff_text, flags=re.MULTILINE)
    known = [
        r["name"]
        for r in store.execute("MATCH (s:Symbol) RETURN s.name AS name")
        if r.get("name")
    ]
    # Match either explicit `def <name>` in diff/hunk headers or direct references to known symbols
    explicit_defs = set(re.findall(r"(?:@@[^@]*@@\s*def\s+|^[+-]\s*def\s+)([A-Za-z_]\w*)", diff_text, flags=re.MULTILINE))
    impacted = [s for s in known if s in explicit_defs or re.search(rf"\b{re.escape(s)}\b", diff_text)]
    if not impacted and explicit_defs:
        impacted = sorted(explicit_defs)
    return files, impacted


def review_pr_diff(store: CodeContextStore, diff_text: str) -> dict[str, Any]:
    """Analyze a unified git diff across all impacted symbols using Relate multi-hop context."""
    files, impacted = _extract_diff_targets(store, diff_text)
    if not impacted:
        return {
            "verdict": "APPROVED",
            "risk_score": 5,
            "files": files,
            "impacted_symbols": [],
            "reviews": [],
            "markdown_comment": "### CodeContext Graph PR Guardrail: `APPROVED` (Risk 5/100)\nNo governed graph symbols were impacted by this diff.",
        }

    # Focus proposed_change on added/removed lines so unchanged context lines don't false-trigger
    changed_lines = "\n".join(
        line[1:]
        for line in diff_text.splitlines()
        if (line.startswith("+") or line.startswith("-"))
        and not line.startswith("+++")
        and not line.startswith("---")
    )
    reviews = [review_code_change(store, sym, changed_lines or diff_text) for sym in impacted]

    verdicts = {r["verdict"] for r in reviews}
    overall_verdict = "BLOCKED" if "BLOCKED" in verdicts else ("CAUTION" if "CAUTION" in verdicts else "APPROVED")

    total_callers = sum(len(r["upstream_callers"]) for r in reviews)
    total_incidents = sum(len(r["incidents"]) for r in reviews)
    total_violations = sum(len(r["violations"]) for r in reviews)
    risk_score = min(100, 10 + total_violations * 45 + total_incidents * 15 + total_callers * 8)

    lines = [
        f"### CodeContext Graph PR Guardrail: `{overall_verdict}` (Risk {risk_score}/100)",
        f"- **Files:** {', '.join(files) if files else 'patch snippet'}",
        f"- **Impacted Symbols:** {', '.join(f'`{s}`' for s in impacted)}",
    ]
    for r in reviews:
        lines.append(f"\n#### `{r['symbol']}` -> **{r['verdict']}**")
        if r["violations"]:
            for v in r["violations"]:
                lines.append(f"- **Violation:** {v}")
        if r["upstream_callers"]:
            lines.append(f"- **Upstream Callers:** {', '.join(r['upstream_callers'])}")
        if r["decisions"]:
            lines.append(f"- **Governing ADRs:** {', '.join(r['decisions'])}")
        if r["incidents"]:
            lines.append(f"- **Linked Incidents:** {', '.join(r['incidents'])}")

    return {
        "verdict": overall_verdict,
        "risk_score": risk_score,
        "files": files,
        "impacted_symbols": impacted,
        "reviews": reviews,
        "markdown_comment": "\n".join(lines),
    }
