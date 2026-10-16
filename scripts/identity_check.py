#!/usr/bin/env python3
"""Browser-level test: identity swap from a second tab must not leave a
stale page behind (Playwright).

Exact user protocol (both tabs' /login pages are opened BEFORE logging in —
that is how a second login is possible at all, since the login view bounces
already-authenticated navigations):

  tab 1: login admin        -> sidebar shows the admin 'App Settings' link
  tab 2: login idcheck(user)-> storage.user (per-browser) now holds idcheck
  tab 1 WITHOUT F5: the page must reload by itself within the watcher
                     period and show idcheck's UI: no 'App Settings' link,
                     account dropdown name = idcheck, /account = idcheck.

Before the fix, tab 1 kept the admin-built header/nav (wrong name in the
dropdown, admin links present) until a manual F5 — the user has no reason
to guess a refresh is needed.

Run (stack must be UP):
  PERF_UI_PASSWORD=... uv run --with playwright -- python scripts/identity_check.py
  make test-identity-ui
Exit code 2 on failure, 0 otherwise.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("PERF_UI_BASE", "http://localhost:8080").rstrip("/")
API = os.environ.get("PERF_API_BASE", "http://127.0.0.1:8000").rstrip("/")
PASSWORD = os.environ.get("PERF_UI_PASSWORD", "")
SETTLE_S = float(os.environ.get("IDENTITY_CHECK_SETTLE_S", "7"))
USER = "idcheck"


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


def _login(page, username: str, password: str) -> None:
    inputs = page.locator("input")
    inputs.nth(0).fill(username)
    inputs.nth(1).fill(password)
    page.locator("button", has_text="Sign in").first.click()


def _has_settings_link(page) -> bool:
    return page.evaluate(
        "document.body.innerText.includes('App Settings')")


def _account_name(page) -> str | None:
    page.wait_for_selector(".header-account-btn", timeout=10_000)
    page.locator(".header-account-btn").first.click()
    try:
        page.wait_for_selector(".account-name", timeout=5_000)
        return page.evaluate(
            "(document.querySelector('.account-name')||{}).innerText || null")
    finally:
        page.keyboard.press("Escape")
        page.locator("body").click(position={"x": 5, "y": 5})


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

    admin_tok = _api("POST", "/auth/login",
                     body={"username": "admin", "password": PASSWORD})
    # Left-over from a previous crashed run? POST /users would 409.
    for u in _api("GET", "/users?limit=500", token=admin_tok["access_token"]):
        if u["username"] == USER:
            _api("DELETE", f"/users/{u['id']}", token=admin_tok["access_token"])
    created = _api("POST", "/users", token=admin_tok["access_token"],
                   body={"username": USER, "role": "user",
                         "must_change_password": False})

    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        # CRUCIAL: both /login forms must be open BEFORE any login happens.
        tab1 = ctx.new_page()
        tab1.goto(f"{BASE}/login", wait_until="networkidle")
        tab2 = ctx.new_page()
        tab2.goto(f"{BASE}/login", wait_until="networkidle")

        try:
            # -- step 1: tab 1 signs in as admin ------------------------
            _login(tab1, "admin", PASSWORD)
            tab1.wait_for_selector(".page-title", timeout=15_000)
            tab1.goto(f"{BASE}/", wait_until="domcontentloaded")
            tab1.wait_for_timeout(1500)
            if not _has_settings_link(tab1):
                failures.append("precondition: admin sidebar has no "
                                "'App Settings' link")
                raise AssertionError("precondition failed")
            print("1) tab1 signed in as admin: 'App Settings' link present")

            # -- step 2: tab 2 signs in as idcheck (swap!) ---------------
            _login(tab2, USER, created["initial_password"])
            tab2.wait_for_selector(".page-title", timeout=15_000)
            tab2.goto(f"{BASE}/", wait_until="domcontentloaded")
            tab2.wait_for_timeout(1000)
            print(f"2) tab2 signed in as {USER}: storage now holds {USER}")

            # -- step 3: tab 1 must reload and match the new identity ---
            tab1.wait_for_timeout(SETTLE_S * 1000)
            path = tab1.evaluate("window.location.pathname")
            has_settings = _has_settings_link(tab1)
            name = _account_name(tab1)
            print(f"3) tab1 after swap: path={path!r} "
                  f"settings_link={has_settings} account_name={name!r}")
            ok = path == "/" and not has_settings and name == USER
            if not ok:
                failures.append(
                    "tab1 shows a stale page after the identity swap "
                    f"(path={path!r}, settings_link={has_settings}, "
                    f"account_name={name!r})")
            else:
                print("   -> tab1 reloaded itself, UI is consistent")

            # -- step 4: /account shows the CURRENT storage identity ----
            tab1.goto(f"{BASE}/account", wait_until="domcontentloaded")
            tab1.wait_for_timeout(1500)
            username = tab1.evaluate("""() => {
                const inputs = [...document.querySelectorAll('input[readonly]')];
                return inputs.length ? inputs[0].value : null;
            }""")
            ok = username == USER
            print(f"4) /account username shown: {username!r}  "
                  f"{'OK' if ok else 'FAIL'}")
            if not ok:
                failures.append(f"/account shows {username!r}, "
                                 f"expected {USER!r}")
        finally:
            try:
                _api("DELETE", f"/users/{created['id']}",
                     token=admin_tok["access_token"])
            except urllib.error.HTTPError:  # noqa: BLE001 — best effort
                pass
            ctx.close()
            browser.close()

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 2
    print("\nidentity propagation across tabs works: no stale page left.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
