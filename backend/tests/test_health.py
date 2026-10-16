"""Health endpoint: must reflect the DATABASE, not just the process."""

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
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_health_ok_with_database(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "ok"}


async def test_health_degraded_when_database_down(monkeypatch, tmp_path):
    import os
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("INSECURE_DEV", "1")
    from app.core import config
    config.get_settings.cache_clear()
    import app.core.db as db
    db._engine = None
    db._session_factory = None
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # Break the engine: any query now raises → /health must 503.
        async def _boom():
            raise RuntimeError("database gone")
        db.get_session_factory = _boom  # type: ignore[assignment]
        r = await c.get("/health")
        assert r.status_code == 503
        assert r.json()["database"] == "unreachable"
