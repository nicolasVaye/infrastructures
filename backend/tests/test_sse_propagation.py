"""SSE propagation contract: what one browser does must reach the others.

The frontend tabs are SSE-driven REFRESH SIGNALS, not data pushes: a login,
a profile/avatar change or a logout bumps a counter in app.storage.user and
the open tab re-fetches. These tests pin the BACKEND half of that contract:
a subscriber (the same asyncio.Queue registry GET /events pushes to, see
app.events._subscribers) must receive the right event types when ANOTHER
session logs in, changes its avatar and logs out, and the Audit tab's data
source (GET /audit) must contain the rows those actions write. If an event
type changes or an endpoint stops notifying, an admin's open /settings
stops updating — this is the regression test for exactly that.

Note on transport: httpx's ASGITransport buffers the whole ASGI response
(it awaits the app to completion), so GET /events cannot be streamed in
tests. Subscribing to events._subscribers tests the endpoint → notify_event
→ _fanout → subscriber chain end to end; the SSE wire format, replay and
resync are covered separately by test_sse_events.py (which drives
_event_stream directly).

Runs on the SQLite in-process path (notify_event fans out directly in the
same event loop), which exercises the same fanout code the Postgres LISTEN
bridge uses.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

import app.events as events

_AVATAR_PNG = ("data:image/png;base64,"
               "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42"
               "mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


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


async def _login(http: AsyncClient, **extra) -> dict:
    r = await http.post("/auth/login",
                        json={"username": "admin", "password": "admin", **extra})
    assert r.status_code == 200, r.text
    return r.json()


class _EventWatcher:
    """One subscriber, exactly like the queue GET /events holds per tab."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        events._subscribers.add(self.queue)

    def close(self) -> None:
        events._subscribers.discard(self.queue)

    async def next_of(self, etype: str, timeout: float = 5.0) -> dict:
        """Next event of the given type (other types are skipped)."""
        deadline = asyncio.get_event_loop().time() + timeout
        pending = []
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            assert remaining > 0, f"no {etype!r} event within {timeout}s"
            try:
                _seq, raw = await asyncio.wait_for(self.queue.get(), remaining)
            except asyncio.TimeoutError:
                for e in pending:
                    self.queue.put_nowait(e)
                raise AssertionError(
                    f"no {etype!r} event within {timeout}s") from None
            evt = json.loads(raw)
            if evt.get("type") == etype:
                return evt
            pending.append((_seq, raw))


async def test_login_avatar_logout_reach_sse_subscribers(client):
    # The "admin browser": a subscriber exactly like services/events_client
    # holds per open tab.
    watcher = _EventWatcher()

    # 1) ANOTHER session logs in (a second browser of the same user, or
    #    any user): the Sessions tab must see it appear live.
    actor = await _login(client, client="pytest-actor")
    evt = await watcher.next_of("sessions_changed")
    assert evt, "login must emit sessions_changed for the open admin tab"

    # 2) The actor changes their avatar: the Users tab (and the header of
    #    every browser of that user) must re-render the new avatar.
    r = await client.patch("/me/profile", json={"avatar": _AVATAR_PNG},
                           headers={"Authorization":
                                    f"Bearer {actor['access_token']}"})
    assert r.status_code == 200, r.text
    evt = await watcher.next_of("user_updated")
    assert evt.get("user_id") == 1, "avatar change must carry the user id"

    # 3) The actor logs out: the session must disappear from the Sessions
    #    tab (session_revoked + sessions_changed) — visible to every admin.
    r = await client.post("/auth/logout",
                          headers={"Authorization":
                                   f"Bearer {actor['access_token']}"})
    assert r.status_code == 200
    evt = await watcher.next_of("session_revoked")
    assert evt.get("session_id"), "logout must identify the revoked session"
    await watcher.next_of("sessions_changed")

    # 4) The Audit tab renders GET /audit: the trail of what just happened
    #    (login + logout, the rows the SSE refresh signals announce).
    admin = await _login(client, client="pytest-admin")
    rows = (await client.get("/audit?limit=50",
                             headers={"Authorization":
                                      f"Bearer {admin['access_token']}"})).json()
    actions = {row["action"] for row in rows}
    assert {"login", "logout"} <= actions, (
        "the audit trail must contain the login/logout rows the Audit tab "
        f"shows after its SSE refresh (got: {sorted(actions)})")

    watcher.close()


async def test_avatar_version_bumps_for_users_tab_urls(client):
    """The Users tab busts the browser cache with ?v=avatar_version: the
    value must actually move when the avatar changes, or every admin keeps
    seeing the OLD image after an avatar update."""
    tokens = await _login(client, client="pytest")
    me1 = (await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})).json()
    r = await client.patch("/me/profile", json={"avatar": _AVATAR_PNG},
                           headers={"Authorization":
                                    f"Bearer {tokens['access_token']}"})
    assert r.status_code == 200
    me2 = (await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})).json()
    assert me2["avatar_version"] == me1["avatar_version"] + 1
    assert me2["has_avatar"] is True
    assert "data:image" not in str(me2), "never re-embed the bytes"
