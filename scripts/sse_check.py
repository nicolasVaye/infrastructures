#!/usr/bin/env python3
"""Browser-level acceptance test of the SSE live updates (Playwright).

Encodes the live-update contract as seen from an open /settings page (the
"admin browser"), WITHOUT any page reload:

  1. a user logs in           -> Sessions tab: the session count grows live
  2. that user changes avatar -> Users tab: the avatar <img> appears live
     (has_avatar false -> true re-renders the user cell)
  3. that user logs out       -> Sessions tab: the count shrinks live,
                                  Users tab: the badge flips to Offline,
                                  Audit tab: a new row appears live
     (audit refresh is driven by the sessions/users SSE counters)

The "other browser" is the REST API (login / PATCH /me/profile / logout),
so the whole chain runs: backend mutation -> notify_event -> SSE stream ->
events_client counter -> tab re-fetch -> per-cell re-render.

Run (stack must be UP):
  PERF_UI_PASSWORD=... uv run --with playwright -- python scripts/sse_check.py
  make test-sse-ui
Exit code 2 when a scenario fails, 0 otherwise.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("PERF_UI_BASE", "http://localhost:8080").rstrip("/")
API = os.environ.get("PERF_API_BASE", "http://127.0.0.1:8000").rstrip("/")
PASSWORD = os.environ.get("PERF_UI_PASSWORD", "")
SETTLE_MS = int(os.environ.get("SSE_CHECK_SETTLE_MS", "5000"))

# Tab indexes in the /settings hub: 0 General, 1 Users, 2 Roles,
# 3 Sessions, 4 Audit, 5 Providers
TAB_USERS, TAB_SESSIONS, TAB_AUDIT = 1, 3, 4


def _api(method: str, path: str, token: str | None = None,
         body: dict | None = None):
    req = urllib.request.Request(f"{API}{path}", method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data=data, timeout=10) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def _open_tab(page, tab_index: int):
    """Activate a tab and return (pager range, panel text).

    The tab body builds lazily on first activation (fetch + render), so the
    read settles 1.5 s — reading too early returns the PREVIOUS panel's
    text during the swap.
    """
    page.locator(".q-tab").nth(tab_index).click()
    page.wait_for_timeout(1500)
    txt = page.evaluate(
        "document.querySelector('.q-tab-panel')?.innerText || ''")
    m = re.search(r"Showing (\d+)[–-](\d+) of (\d+)", txt)
    return (m.groups() if m else None), txt


def _row_probe(page, username: str, js: str):
    """Run a JS probe scoped to the table ROW of the given user."""
    return page.evaluate(f"""(name) => {{
        const rows = [...document.querySelectorAll(
            '.q-tab-panel .w-full.items-center.px-4')];
        const row = rows.find(r => r.innerText.includes(name));
        if (!row) return null;
        {js}
    }}""", username)


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright missing: run\n  uv run --with playwright -- "
              "playwright install chromium", file=sys.stderr)
        return 1
    if not PASSWORD:
        print("PERF_UI_PASSWORD is not set.", file=sys.stderr)
        return 1

    failures: list[str] = []
    actor = None
    created_id = None
    admin_tok = None

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context().new_page()

        # -- the "admin browser": logged in, /settings open -----------------
        page.goto(f"{BASE}/login", wait_until="networkidle")
        inputs = page.locator("input")
        inputs.nth(0).fill("admin")
        inputs.nth(1).fill(PASSWORD)
        page.locator("button", has_text="Sign in").first.click()
        page.wait_for_selector(".page-title", timeout=15_000)
        page.goto(f"{BASE}/settings", wait_until="domcontentloaded")
        page.wait_for_selector(".tabs-bar", timeout=15_000)

        admin_tok = _api("POST", "/auth/login",
                         body={"username": "admin", "password": PASSWORD})

        # Left-over from a previous crashed run? Clean it first — POST
        # /users would 409 on the username.
        existing = [u for u in _api("GET", "/users?limit=500",
                                    token=admin_tok["access_token"])
                    if u["username"] == "sse-check"]
        for u in existing:
            _api("DELETE", f"/users/{u['id']}",
                 token=admin_tok["access_token"])

        # A distinct throw-away user plays the "other browser".
        created = _api("POST", "/users", token=admin_tok["access_token"],
                       body={"username": "sse-check", "role": "user"})
        created_id = created["id"]
        try:
            # 1) LOGIN: the Sessions tab total must grow live.
            (rng, _) = _open_tab(page, TAB_SESSIONS)
            before = int(rng[2]) if rng else 0
            actor = _api("POST", "/auth/login",
                         body={"username": "sse-check",
                               "password": created["initial_password"],
                               "client": "sse-check"})
            page.wait_for_timeout(SETTLE_MS)
            (rng, _) = _open_tab(page, TAB_SESSIONS)
            after = int(rng[2]) if rng else 0
            ok = after == before + 1
            print(f"1) login visible in Sessions tab:  "
                  f"{before} -> {after}  {'OK' if ok else 'FAIL'}")
            if not ok:
                failures.append("login not visible in Sessions tab")

            # 2) AVATAR: with the Users tab OPEN, the change must re-render
            #    the user cell live (no avatar -> avatar <img>).
            _open_tab(page, TAB_USERS)
            _api("PATCH", "/me/profile", token=actor["access_token"],
                 body={"avatar": "data:image/png;base64,"
                      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
                      "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="})
            page.wait_for_timeout(SETTLE_MS)
            src = _row_probe(
                page, "sse-check",
                "const img = row.querySelector('img');"
                "return img ? img.getAttribute('src') : 'no-image';")
            ok = bool(src and "avatar" in src)
            print(f"2) avatar visible in Users tab:    {src!r}  "
                  f"{'OK' if ok else 'FAIL'}")
            if not ok:
                failures.append("avatar not visible in Users tab")

            # 3) LOGOUT: sessions total shrinks, users badge flips Offline,
            #    and a fresh audit row appears while the Audit tab is open.
            _api("POST", "/auth/logout", token=actor["access_token"])
            actor = None
            page.wait_for_timeout(SETTLE_MS)
            (rng, _) = _open_tab(page, TAB_SESSIONS)
            logged_out = int(rng[2]) if rng else 0
            ok = logged_out == after - 1
            print(f"3a) logout in Sessions tab:        "
                  f"{after} -> {logged_out}  {'OK' if ok else 'FAIL'}")
            if not ok:
                failures.append("logout not visible in Sessions tab")

            _open_tab(page, TAB_USERS)
            badge = _row_probe(
                page, "sse-check",
                "const badges = [...row.querySelectorAll('.badge')];"
                "const b = badges.find(x => /Online|Offline|—/.test("
                "x.innerText)); return b ? b.innerText.trim() : null;")
            ok = bool(badge and "Offline" in badge)
            print(f"3b) Users tab badge after logout: {badge!r}  "
                  f"{'OK' if ok else 'FAIL'}")
            if not ok:
                failures.append(
                    f"users tab badge is {badge!r}, expected Offline")

            (rng, _) = _open_tab(page, TAB_AUDIT)
            audit_t1 = int(rng[2]) if rng else 0
            # One more login while the Audit tab is OPEN: the audit row must
            # appear live (SSE-driven refresh, not the 60s fallback poll).
            _api("POST", "/auth/login",
                 body={"username": "admin", "password": PASSWORD})
            page.wait_for_timeout(SETTLE_MS)
            (rng, _) = _open_tab(page, TAB_AUDIT)
            audit_t2 = int(rng[2]) if rng else 0
            ok = audit_t2 > audit_t1
            print(f"3c) audit row appears live:        "
                  f"{audit_t1} -> {audit_t2}  {'OK' if ok else 'FAIL'}")
            if not ok:
                failures.append("audit tab did not refresh live")

            # 4) IDENTITY LEAVES: app.storage.user is per-BROWSER (shared by
            #    every tab). When the browser stops being admin — logout
            #    from another tab, or a same-browser login as a lesser user
            #    — the /settings role watcher must CLOSE this admin-built
            #    page instead of letting it hammer admin endpoints with
            #    an unprivileged/absent token (403 storm).
            page2 = page.context.new_page()
            page2.goto(f"{BASE}/", wait_until="networkidle")
            # The logout item lives in the header account dropdown: open it.
            page2.wait_for_selector(".header-account-btn", timeout=15_000)
            page2.wait_for_timeout(500)  # let the button handlers attach
            page2.locator(".header-account-btn").first.click()
            page2.wait_for_selector(".account-menu-item.logout", timeout=5_000)
            page2.locator(".account-menu-item.logout").first.click()
            page2.wait_for_timeout(2000)  # logout clears the browser storage
            page2.close()
            page.wait_for_timeout(8000)   # watcher runs every 5s
            url = page.evaluate("window.location.pathname")
            ok = url != "/settings"
            print(f"4) admin page closed when identity left: "
                  f"now at {url!r}  {'OK' if ok else 'FAIL'}")
            if not ok:
                failures.append(
                    "admin-built /settings survived losing the admin identity")
        finally:
            if actor:
                try:
                    _api("POST", "/auth/logout", token=actor["access_token"])
                except urllib.error.URLError:  # noqa: BLE001
                    pass
            if created_id is not None and admin_tok:
                try:
                    _api("DELETE", f"/users/{created_id}",
                         token=admin_tok["access_token"])
                except urllib.error.HTTPError:  # noqa: BLE001 — best effort
                    pass
                try:
                    _api("POST", "/auth/logout",
                         token=admin_tok["access_token"])
                except urllib.error.URLError:  # noqa: BLE001
                    pass

        page.close()
        page.context.close()
        browser.close()

    if failures:
        print("\nFAILED scenarios:")
        for f in failures:
            print(f"  - {f}")
        return 2
    print("\nall SSE live-update scenarios passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
