"""Tests for the identity-provider (OIDC) management layer.

The full OIDC code flow needs a live IdP; here we cover what can be tested
in-process: the signed anti-CSRF state tokens, the admin CRUD over /idps,
and that a local login is rejected for federated-style accounts (no local
password hash).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")

    from app.core import config
    config.get_settings.cache_clear()
    import app.core.db as db
    db._engine = None
    db._session_factory = None

    from app.main import app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def _admin_auth(client: AsyncClient) -> dict:
    resp = await client.post(
        "/auth/login", json={"username": "admin", "password": "admin"},
        headers={"X-Client-Label": "pytest"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_oidc_state_sign_and_verify_roundtrip():
    from app.core import oidc
    state = oidc.sign_state(42)
    oidc.verify_state(state, 42)  # must not raise
    with pytest.raises(Exception):
        oidc.verify_state(state, 7)  # wrong provider
    with pytest.raises(Exception):
        oidc.verify_state("garbage", 42)


async def test_idp_crud_requires_admin(client: AsyncClient):
    payload = {
        "name": "Keycloak Test",
        "issuer_url": "https://keycloak.example/realms/test",
        "client_id": "infra",
        "client_secret": "s3cret",
    }
    # unauthenticated → 401
    resp = await client.post("/idps", json=payload)
    assert resp.status_code == 401

    auth = await _admin_auth(client)

    # create
    resp = await client.post("/idps", json=payload, headers=auth)
    assert resp.status_code == 201, resp.text
    idp = resp.json()
    assert idp["name"] == "Keycloak Test"
    assert "client_secret" not in idp  # never exposed

    # list
    resp = await client.get("/idps", headers=auth)
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # public providers list reflects enabled providers
    resp = await client.get("/auth/providers")
    assert resp.status_code == 200
    assert [p["name"] for p in resp.json()] == ["Keycloak Test"]

    # duplicate name → 409
    resp = await client.post("/idps", json=payload, headers=auth)
    assert resp.status_code == 409

    # update (partial)
    resp = await client.patch(f"/idps/{idp['id']}",
                              json={"enabled": False, "default_role": "operator"},
                              headers=auth)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
    assert resp.json()["default_role"] == "operator"

    # disabled provider disappears from the public login list
    resp = await client.get("/auth/providers")
    assert resp.json() == []

    # delete
    resp = await client.delete(f"/idps/{idp['id']}", headers=auth)
    assert resp.status_code == 204


async def test_local_login_rejects_passwordless_accounts(client: AsyncClient, monkeypatch):
    """A user without a local password hash (OIDC) cannot log in locally."""
    auth = await _admin_auth(client)

    # insert an OIDC-style user directly through the DB layer
    from app.core.db import (RoleRecord, UserRecord, get_session_factory)
    from sqlalchemy import select
    async with get_session_factory()() as session:
        role = (await session.scalars(
            select(RoleRecord).where(RoleRecord.name == "user"))).first()
        session.add(UserRecord(
            username="keycloak.jane", password_hash=None, role_id=role.id,
            is_active=True, must_change_password=False,
            auth_provider="oidc", external_subject="sub-123",
        ))
        await session.commit()

    resp = await client.post(
        "/auth/login", json={"username": "keycloak.jane", "password": "whatever"},
        headers={"X-Client-Label": "pytest"},
    )
    assert resp.status_code == 401
