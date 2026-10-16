#!/usr/bin/env python3
"""Browser-level page DISPLAY timing for the NiceGUI frontend (Playwright).

Complements scripts/perf_probe.py (URL access times) by measuring what the
user actually perceives: the time from navigation start to the page's key
content being visible. A NiceGUI page loads a shell over HTTP, then builds
the DOM over a websocket — so the only faithful measure of "affichage"
needs a real browser.

Run (frontend must be UP, e.g. `make up`):
  uv run --with playwright -- python scripts/perf_ui.py
  PERF_UI_USER=admin PERF_UI_PASSWORD=... \
      PERF_UI_SLOW_MS=2000 uv run --with playwright -- python scripts/perf_ui.py
  make perf-ui        # after: uv run --with playwright -- playwright install chromium

Feel thresholds (default PERF_UI_SLOW_MS=2500, on first visit per page —
the service worker/asset cache is deliberately warmed up first so we measure
the steady state, not the cold install):
  < 1 s   instant   |  < 2.5 s  fine
  < 5 s   sluggish  |  > 5 s    broken-feeling

Exit code 2 when a page exceeds the budget, 0 otherwise.
"""

from __future__ import annotations

import os
import sys
import time

BASE = os.environ.get("PERF_UI_BASE", "http://localhost:8080").rstrip("/")
USER = os.environ.get("PERF_UI_USER", "admin")
PASSWORD = os.environ.get("PERF_UI_PASSWORD", "")
SLOW_MS = float(os.environ.get("PERF_UI_SLOW_MS", "2500"))
RUNS = int(os.environ.get("PERF_UI_RUNS", "3"))

# (path, selector that proves the page is RENDERED)
PAGES = [
    ("/",            ".page-title"),
    ("/settings",     ".tabs-bar"),
    ("/account",     ".page-title"),
    ("/jobs",         ".page-title"),
]


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed: run\n"
              "  uv run --with playwright -- playwright install chromium",
              file=sys.stderr)
        return 1
    if not PASSWORD:
        print("PERF_UI_PASSWORD is not set (default user: admin).",
              file=sys.stderr)
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        page = ctx.new_page()

        # -- login ---------------------------------------------------------
        page.goto(f"{BASE}/login", wait_until="networkidle")
        inputs = page.locator("input")
        inputs.nth(0).fill(USER)
        inputs.nth(1).fill(PASSWORD)
        page.locator("button", has_text="Sign in").first.click()
        page.wait_for_selector(".page-title", timeout=15_000)

        # Warm-up run (service worker install, static assets, websocket):
        # the budget applies to the steady state a returning user sees.
        for path, selector in PAGES:
            page.goto(f"{BASE}{path}", wait_until="domcontentloaded")
            page.wait_for_selector(selector, timeout=15_000)
            page.wait_for_timeout(300)

        results = []
        for path, selector in PAGES:
            times = []
            for _ in range(RUNS):
                t0 = time.perf_counter()
                page.goto(f"{BASE}{path}", wait_until="domcontentloaded")
                page.wait_for_selector(selector, timeout=15_000)
                times.append((time.perf_counter() - t0) * 1000)
            results.append((f"page {path}", min(times), sum(times) / len(times),
                           max(times)))

        # Settings tabs are built LAZILY on first activation: the first
        # click on each tab is what the user feels after opening /settings.
        # Tabs are clicked BY INDEX (General=0, Users=1, Roles=2, …): the
        # labels are localized (en/de/fr) and substring matching would
        # click "Users & roles" when looking for "Roles".
        page.goto(f"{BASE}/settings", wait_until="domcontentloaded")
        page.wait_for_selector(".tabs-bar", timeout=15_000)
        tab_names = {1: "users", 2: "roles", 3: "sessions", 4: "audit", 5: "idps"}
        for idx, name in tab_names.items():
            before = page.evaluate(
                "document.querySelector('.q-tab-panel')?.innerText.length ?? 0")
            t0 = time.perf_counter()
            page.locator(".q-tab").nth(idx).click()
            deadline = time.perf_counter() + 15
            while time.perf_counter() < deadline:
                # Light polling: the panel content must CHANGE (the lazy
                # build landed). No busy-loop — 150 ms steps keep the
                # websocket free to apply the incoming element diff.
                page.wait_for_timeout(150)
                now = page.evaluate(
                    "document.querySelector('.q-tab-panel')?.innerText.length ?? 0")
                if now != before:
                    break
            results.append((f"tab {name}", (time.perf_counter() - t0) * 1000,
                           0.0, (time.perf_counter() - t0) * 1000))

        page.close()
        ctx.close()
        browser.close()

    print(f"\n{'page':<14} {'min':>8} {'avg':>8} {'max':>8}   budget {SLOW_MS:.0f} ms")
    print("-" * 60)
    slow = False
    for path, mn, avg, mx in results:
        flag = ""
        if mx > SLOW_MS:
            flag = "  <-- SLOW"
            slow = True
        print(f"{path:<14} {mn:7.0f} {avg:7.0f} {mx:7.0f}{flag}")
    if slow:
        print("\nat least one page exceeds the perceived-slowness budget.")
        return 2
    print("\nevery page renders within the perceived-slowness budget.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
