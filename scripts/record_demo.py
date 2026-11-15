"""Automated Playwright screen-recording script for CodeContext Graph demo."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "demo_recording"
OUT_DIR.mkdir(exist_ok=True)


def wait_for_server(url: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("Server did not start in time")


def main() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["CODECONTEXT_DB"] = str(ROOT / "store" / "codecontext")

    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "codecontext.web:app", "--host", "127.0.0.1", "--port", "8765"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        wait_for_server("http://127.0.0.1:8765/")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                record_video_dir=str(OUT_DIR),
                record_video_size={"width": 1280, "height": 720},
            )
            page = context.new_page()
            page.goto("http://127.0.0.1:8765/", wait_until="networkidle")
            say = lambda txt: page.evaluate(
                "(t) => { const el = document.getElementById('narration'); el.style.display='block'; el.textContent=t; }",
                txt,
            )

            say("1/5 Embedded Relate persistent store loaded (zero external DB server).")
            page.wait_for_timeout(3500)

            say("2/5 Multi-hop Blast Radius: tracing 1..3-hop callers, ADRs, Rules & Incidents.")
            page.get_by_role("button", name="Blast Radius").click()
            page.wait_for_timeout(3500)

            say("3/5 Tracing Why ADR?: connecting code symbols back to INC-204 & ADR-001.")
            page.get_by_role("button", name="Why ADR?").click()
            page.wait_for_timeout(3500)

            say("4/5 Agentic PR Guardrail: Relate blocks risky changes before they ship.")
            page.get_by_role("button", name="Run Agentic Guardrail").click()
            page.wait_for_timeout(4000)

            say("5/5 Live Cypher Playground + Interactive Connected Context Graph.")
            cypher_box = page.locator("#cypher")
            cypher_box.fill(
                "MATCH (r:Rule)-[:APPLIES_TO]->(s:Symbol)<-[:CALLS]-(caller:Symbol) "
                "RETURN r.id, r.constraint, s.name, caller.name"
            )
            page.get_by_role("button", name="Run Cypher").click()
            page.wait_for_timeout(2500)

            page.evaluate("window.scrollTo({top: 480, behavior: 'smooth'})")
            page.wait_for_timeout(4500)

            video_path = page.video.path()
            context.close()
            browser.close()

        target = OUT_DIR / "codecontext_demo.webm"
        if target.exists():
            target.unlink()
        Path(video_path).rename(target)
        print(f"Saved screen recording: {target}")
    finally:
        server.terminate()
        server.wait(timeout=5)


if __name__ == "__main__":
    main()
