"""Volume + latency sentinel tests for the endpoints the UI pages read.

These load a database with THOUSANDS of rows (users, sessions, audit,
activity, jobs) and assert that the endpoints the frontend renders stay
under generous latency thresholds. They are sentinels against algorithmic
regressions (N+1 queries, missing indexes, payload blowups like a base64
avatar sneaking back into /users), NOT millisecond benchmarks: the numbers
are deliberately high so the suite does not flake on slow CI runners, while
a real regression blows through them by an order of magnitude.

Thresholds double as the "perceived slowness" budget for the pages:
- < 150 ms  feels instant
- < 500 ms  feels snappy
- < 1 s     starts to feel like loading
- > 1 s     the user perceives the page as slow

SQLite in-process is FASTER than the production Postgres over TCP for
these volumes, so a threshold exceeded here almost always means a query-
shape problem, not hardware.
"""

from __future__ import annotations

import statistics
import time
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

# -- seeded volumes (the "thousands of records" scenario) --------------------
N_USERS = 450      # > 2 pages of 200 via the pagination loop
N_SESSIONS = 600
N_AUDIT = 3000
N_ACTIVITY = 2500
N_JOBS = 150

# Median-latency budgets in ms (see module docstring for the feel scale).
THRESHOLD_MS = {
    "/health": 150,
    "/auth/me": 300,
    "/users?limit=200": 500,
    "/sessions": 800,        # one row per session, sparkline feed
    "/audit?limit=50": 500,
    "/activity/users": 1000,   # GROUP BY over N_ACTIVITY rows
    "/activity/sessions": 1000,
    "/jobs?limit=50": 500,
    "/system/sse-stats": 300,
    "/system/events-log?limit=50": 500,
}

# A /users page of 200 rows must stay tiny: UserOut carries flags only
# (no base64 avatar). 200 * ~350 bytes ≈ 70 KB; 250 KB leaves headroom.
MAX_USERS_PAGE_BYTES = 250_000


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/perf.db")
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("INSECURE_DEV", "1")
    from app.core import config
    config.get_settings.cache_clear()
    import app.core.db as db
    db._engine = None
    db._session_factory = None

    # ASGITransport does not run the lifespan: create schema + seed admin.
    from app.bootstrap import ensure_schema
    await ensure_schema()
    await _seed_volume()

    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _seed_volume() -> None:
    """Bulk-insert the volume fixtures in ONE transaction (SQLite fast path)."""
    from app.core.db import (ActivityRecord, AuditLogRecord, JobRecord,
                             SessionRecord, UserRecord, get_session_factory,
                             utcnow)

    async with get_session_factory()() as session:
        from sqlalchemy import select

        from app.core.db import RoleRecord
        role = (await session.scalars(
            select(RoleRecord).where(RoleRecord.name == "user"))).first()
        role_id = role.id

        users = [UserRecord(username=f"perf{i:04d}", password_hash="!x!x!x!x",
                            role_id=role_id, is_active=True,
                            must_change_password=False)
                 for i in range(N_USERS)]
        session.add_all(users)
        await session.flush()  # assign user ids

        now = utcnow()
        sessions = []
        for i in range(N_SESSIONS):
            sessions.append(SessionRecord(
                user_id=1 + (i % N_USERS),
                client="web", ip="127.0.0.1", user_agent="perf-seed",
                expires_at=now + timedelta(hours=1),
            ))
        session.add_all(sessions)

        audit = [AuditLogRecord(action="login", username=f"perf{i % N_USERS:04d}",
                                user_id=1 + (i % N_USERS), ip="127.0.0.1")
                 for i in range(N_AUDIT)]
        session.add_all(audit)

        activity = [ActivityRecord(user_id=1 + (i % N_USERS),
                                   session_id=f"sess{i % 50:04d}",
                                   path=f"/page{i % 12}")
                    for i in range(N_ACTIVITY)]
        session.add_all(activity)

        jobs = [JobRecord(job_type="demo.sleep", params={"seconds": 0.01},
                          status="succeeded", created_by="admin")
                for _ in range(N_JOBS)]
        session.add_all(jobs)
        await session.commit()


async def _login(client: AsyncClient) -> dict:
    r = await client.post("/auth/login",
                          json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _median_ms(client: AsyncClient, path: str, auth: dict,
                     n: int = 5) -> float:
    """Median latency over n calls, after one warm-up (caches, sqlite pages)."""
    await client.get(path, headers=auth)
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        r = await client.get(path, headers=auth)
        times.append((time.perf_counter() - t0) * 1000)
        assert r.status_code == 200, f"{path} -> {r.status_code}"
    return statistics.median(times)


async def test_read_endpoints_stay_fast_at_volume(client):
    auth = await _login(client)
    worst = []
    for path, budget_ms in THRESHOLD_MS.items():
        med = await _median_ms(client, path, auth)
        worst.append((med, path))
        print(f"\n{path:<28} median {med:7.1f} ms  (budget {budget_ms} ms)")
        assert med < budget_ms, (
            f"{path} median {med:.0f} ms exceeds the {budget_ms} ms "
            f"perceived-slowness budget at volume "
            f"({N_USERS} users, {N_SESSIONS} sessions, {N_AUDIT} audit, "
            f"{N_ACTIVITY} activity rows)"
        )
    slowest, slowest_path = max(worst)
    print(f"worst endpoint: {slowest_path} at {slowest:.1f} ms")


async def test_users_pagination_loop_at_volume(client):
    """The frontend fetches users page by page (200/req): the full loop
    must collect every user without a payload blowup."""
    auth = await _login(client)
    seen: set[int] = set()
    t0 = time.perf_counter()
    offset = 0
    total_bytes = 0
    while True:
        r = await client.get(f"/users?limit=200&offset={offset}", headers=auth)
        assert r.status_code == 200
        page = r.json()
        total_bytes += len(r.content)
        seen.update(u["id"] for u in page)
        if len(page) < 200:
            break
        offset += 200
    elapsed_ms = (time.perf_counter() - t0) * 1000
    # seeded admin + N_USERS volume users
    assert len(seen) == N_USERS + 1
    # generous budget: 3 requests, each < 500 ms
    assert elapsed_ms < 1500, f"pagination loop took {elapsed_ms:.0f} ms"
    assert total_bytes / len(seen) < MAX_USERS_PAGE_BYTES / 200, (
        "payload per user grew — check that no avatar base64 leaked back "
        "into UserOut"
    )


async def test_sessions_order_is_stable_at_volume(client):
    """Two consecutive /sessions calls must return the SAME order: the UI
    diffs rows per cell and a shuffled order rebuilds the whole table."""
    auth = await _login(client)
    r1 = await client.get("/sessions", headers=auth)
    r2 = await client.get("/sessions", headers=auth)
    ids1 = [s["id"] for s in r1.json()]
    ids2 = [s["id"] for s in r2.json()]
    assert len(ids1) >= N_SESSIONS  # + the login session itself
    assert ids1 == ids2, "unstable ordering makes the sessions table rebuild"


async def test_users_page_has_no_avatar_bytes_at_volume(client):
    """The avatar-isolation invariant, checked at 200 users per page: any
    leak multiplies the payload by ~10 KB per avatar."""
    auth = await _login(client)
    r = await client.get("/users?limit=200", headers=auth)
    body = str(r.json())
    assert "data:image" not in body
    assert len(r.content) < MAX_USERS_PAGE_BYTES
