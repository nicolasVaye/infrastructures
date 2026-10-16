"""Avatar isolation + user pagination (the payload-size fix).

UserOut must never embed the base64 image; the dedicated
GET /users/{id}/avatar serves it, access-checked (self or admin).
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
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


_AVATAR = ("data:image/png;base64,"
           "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


async def _admin_headers(client: AsyncClient):
    tokens = (await client.post("/auth/login",
                                json={"username": "admin", "password": "admin"})).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def test_userout_has_no_avatar_bytes(client):
    auth = await _admin_headers(client)
    # Upload an avatar for the admin (self-service profile).
    r = await client.patch("/me/profile", headers=auth, json={"avatar": _AVATAR})
    assert r.status_code == 200, r.text
    # /auth/me and /users must carry the FLAG, never the data URL.
    me = (await client.get("/auth/me", headers=auth)).json()
    assert me["has_avatar"] is True
    assert me["avatar_version"] >= 1
    assert "data:image" not in str(me)
    users = (await client.get("/users", headers=auth)).json()
    assert all("data:image" not in str(u) for u in users)
    assert all("has_avatar" in u for u in users)


async def test_avatar_route_serves_bytes_access_checked(client):
    auth = await _admin_headers(client)
    me = (await client.get("/auth/me", headers=auth)).json()
    await client.patch("/me/profile", headers=auth, json={"avatar": _AVATAR})

    img = await client.get(f"/users/{me['id']}/avatar", headers=auth)
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/png"
    assert img.content.startswith(b"\x89PNG")

    # A user without an avatar answers 404, not an error.
    missing = await client.get("/users/999/avatar", headers=auth)
    assert missing.status_code == 404

    # Unauthenticated access is refused.
    anon = await client.get(f"/users/{me['id']}/avatar")
    assert anon.status_code == 401


async def test_users_pagination(client):
    auth = await _admin_headers(client)
    created = []
    for i in range(7):
        r = await client.post("/users", headers=auth,
                              json={"username": f"user{i:02d}", "role": "user"})
        assert r.status_code == 201, r.text
        created.append(r.json()["id"])

    page1 = (await client.get("/users?limit=5&offset=0", headers=auth)).json()
    page2 = (await client.get("/users?limit=5&offset=5", headers=auth)).json()
    assert len(page1) == 5
    assert len(page2) >= 3  # admin + 7 users = 8 total
    ids1 = {u["id"] for u in page1}
    ids2 = {u["id"] for u in page2}
    assert not ids1 & ids2, "pages must not overlap"

    # limit bounds are enforced (422 outside 1..500).
    assert (await client.get("/users?limit=0", headers=auth)).status_code == 422
    assert (await client.get("/users?limit=501", headers=auth)).status_code == 422
