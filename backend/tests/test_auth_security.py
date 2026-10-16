"""Auth security invariants: refresh rotation, replay revocation, rate limit.

These are the regressions an attacker would benefit from most:
- a refresh token reused after rotation must kill the whole session;
- the login rate limiter must lock an IP out after the configured number
  of failures, and it must count failures across replicas via the audit
  table (simulated here by a fresh in-process audit-backed check).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/t.db")
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
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _login(client: AsyncClient, username="admin", password="admin"):
    return await client.post("/auth/login", json={"username": username, "password": password})


async def test_refresh_rotation_and_replay_revokes_session(client):
    tokens = (await _login(client)).json()
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}

    # Rotate: the first refresh gives a NEW pair.
    r1 = await client.post("/auth/refresh",
                           json={"refresh_token": tokens["refresh_token"]})
    assert r1.status_code == 200, r1.text
    rotated = r1.json()
    assert rotated["access_token"] != tokens["access_token"]

    # The OLD refresh token is now a replay → session revoked everywhere.
    r2 = await client.post("/auth/refresh",
                           json={"refresh_token": tokens["refresh_token"]})
    assert r2.status_code == 401

    # The access token bound to the revoked session no longer works.
    me = await client.get("/auth/me", headers=auth)
    assert me.status_code == 401


async def test_login_rate_limit_locks_out_after_failures(client):
    # 10 failures (the configured _LOGIN_MAX_FAILURES) from the same
    # username → the 11th attempt is refused with 429 even with the
    # CORRECT password: the lockout is keyed before password work.
    for _ in range(10):
        r = await _login(client, password="wrong-password")
        assert r.status_code == 401
    r = await _login(client)  # correct credentials, locked out
    assert r.status_code == 429
