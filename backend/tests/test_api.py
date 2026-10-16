"""End-to-end smoke test of the backend API (SQLite, in-process ASGI)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("INSECURE_DEV", "1")

    # reset cached settings/engine so env changes take effect
    from app.core import config
    config.get_settings.cache_clear()
    import app.core.db as db
    db._engine = None
    db._session_factory = None

    # httpx ASGITransport does NOT run the app lifespan, so the schema and
    # the seed admin are created here exactly like startup does.
    from app.bootstrap import ensure_schema
    await ensure_schema()

    from app.main import app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def test_login_flow_and_jobs(client: AsyncClient):
    # health
    resp = await client.get("/health")
    assert resp.status_code == 200

    # login with seeded admin
    resp = await client.post(
        "/auth/login", json={"username": "admin", "password": "admin"},
        headers={"X-Client-Label": "pytest"},
    )
    assert resp.status_code == 200, resp.text
    tokens = resp.json()
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}

    # me
    resp = await client.get("/auth/me", headers=auth)
    assert resp.status_code == 200
    me = resp.json()
    assert me["username"] == "admin"
    assert me["role"] == "admin"

    # roles
    resp = await client.get("/roles", headers=auth)
    assert resp.status_code == 200
    assert {r["name"] for r in resp.json()} == {"admin", "operator", "user"}

    # heartbeat → session connected
    resp = await client.put("/auth/heartbeat", json={"client": "pytest"}, headers=auth)
    assert resp.status_code == 200

    # who is connected (admin)
    resp = await client.get("/sessions", headers=auth)
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) == 1
    assert sessions[0]["username"] == "admin"
    assert sessions[0]["client"] == "pytest"

    # submit a job, it appears queued
    resp = await client.post(
        "/jobs", json={"job_type": "demo.sleep", "params": {"seconds": 1}}, headers=auth
    )
    assert resp.status_code == 202
    job = resp.json()
    assert job["status"] == "queued"

    # audit recorded login + job submission
    resp = await client.get("/audit?limit=50", headers=auth)
    actions = {a["action"] for a in resp.json()}
    assert "login" in actions
    assert "job_submitted" in actions

    # wrong password → 401
    resp = await client.post("/auth/login", json={"username": "admin", "password": "nope"})
    assert resp.status_code == 401

    # logout revokes the session
    resp = await client.post("/auth/logout", headers=auth)
    assert resp.status_code == 200
    resp = await client.get("/sessions", headers=auth)  # revoked session → 401
    assert resp.status_code == 401
