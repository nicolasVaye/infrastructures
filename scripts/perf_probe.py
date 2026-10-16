#!/usr/bin/env python3
"""URL access-time probe against a RUNNING stack (docker compose up).

Times every read endpoint the UI pages load, with an authenticated login,
and flags anything over the "perceived slowness" threshold. Pure stdlib
(no httpx/requests) so it runs on any host with python3.

Usage:
  python3 scripts/perf_probe.py                 # backend on 127.0.0.1:8000
  PERF_BASE=http://127.0.0.1:8000 PERF_USER=admin PERF_PASSWORD=... \
      PERF_SAMPLES=20 PERF_SLOW_MS=250 python3 scripts/perf_probe.py
  make perf                                     # same, via the Makefile

Feel scale used for the SLOW flag (median):
  < 150 ms  instant   |  < 500 ms  snappy
  < 1 s     loading   |  > 1 s     slow

Exit code 2 when at least one URL's p95 exceeds PERF_SLOW_MS, so a cron or
CI job can alert; 0 otherwise.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("PERF_BASE", "http://127.0.0.1:8000").rstrip("/")
FRONTEND_BASE = os.environ.get("PERF_FRONTEND_BASE", "http://localhost:8080").rstrip("/")
USER = os.environ.get("PERF_USER", "admin")
PASSWORD = os.environ.get("PERF_PASSWORD", "")
SAMPLES = int(os.environ.get("PERF_SAMPLES", "10"))
SLOW_MS = float(os.environ.get("PERF_SLOW_MS", "300"))

# Read endpoints the UI actually loads (page builders + poll timers).
URLS = [
    "/health",
    "/auth/me",
    "/users?limit=200",
    "/sessions",
    "/audit?limit=50",
    "/activity/users",
    "/activity/sessions",
    "/jobs?limit=50",
    "/roles",
    "/system/sse-stats",
    "/system/events-log?limit=50",
]
# Public frontend URLs (no auth): shell + assets reachability.
PUBLIC_URLS = [
    (FRONTEND_BASE, "/health"),
]


def _request(url: str, token: str | None, timeout: float = 10.0):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        exc.read()
        status = exc.code
    return status, (time.perf_counter() - t0) * 1000


def login() -> str:
    if not PASSWORD:
        print("PERF_PASSWORD is not set — export it (or PERF_USER/PERF_BASE) "
              "and retry.", file=sys.stderr)
        sys.exit(1)
    body = json.dumps({"username": USER, "password": PASSWORD}).encode()
    req = urllib.request.Request(
        f"{BASE}/auth/login", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        tokens = json.load(resp)
    return tokens["access_token"]


def main() -> int:
    print(f"probe target : {BASE} ({SAMPLES} samples/url, slow > {SLOW_MS:.0f} ms p95)")
    token = login()
    rows = []
    slow = []
    for url in URLS:
        full = f"{BASE}{url}"
        status, _ = _request(full, token)          # warm-up
        times, statuses = [], set()
        for _ in range(SAMPLES):
            status, ms = _request(full, token)
            statuses.add(status)
            times.append(ms)
        if statuses - {200}:
            slow.append((url, f"HTTP {sorted(statuses)}"))
            continue
        p50 = statistics.median(times)
        p95 = max(times) if SAMPLES < 20 else \
            statistics.quantiles(times, n=20)[18]
        rows.append((url, min(times), p50, p95, max(times)))
        if p95 > SLOW_MS:
            slow.append((url, f"p95 {p95:.0f} ms > {SLOW_MS:.0f} ms"))
    for base, url in PUBLIC_URLS:
        full = f"{base}{url}"
        status, _ = _request(full, None)
        if status != 200:
            slow.append((url, f"HTTP {status}"))
            continue
        times = []
        for _ in range(SAMPLES):
            _, ms = _request(full, None)
            times.append(ms)
        rows.append((f"[frontend]{url}", min(times), statistics.median(times),
                     max(times), max(times)))

    print(f"\n{'URL':<30} {'min':>8} {'p50':>8} {'p95':>8} {'max':>8}")
    print("-" * 68)
    for url, mn, p50, p95, mx in sorted(rows, key=lambda r: -r[3]):
        flag = "  <-- SLOW" if p95 > SLOW_MS else ""
        print(f"{url:<30} {mn:7.1f} {p50:7.1f} {p95:7.1f} {mx:7.1f}{flag}")
    if slow:
        print("\nthreshold violations:")
        for url, why in slow:
            print(f"  {url}: {why}")
        return 2
    print("\nall URLs under the perceived-slowness threshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
