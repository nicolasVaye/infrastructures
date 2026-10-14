"""Real-time change events: Postgres LISTEN/NOTIFY bridge + SSE endpoint.

Pattern
-------
Every mutating endpoint calls :func:`notify_event` INSIDE its transaction
(``pg_notify``). Postgres delivers the notification exactly when the
transaction commits — no phantom events from rolled-back writes, and every
backend replica hears every write (its own and the other replicas').

A background task started from the app lifespan LISTENs on the channel and
fans the events out to connected SSE subscribers (``GET /events``). The
NiceGUI frontend subscribes once per tab and pushes live updates to the UI
(user profile/header, jobs board, own-session revocation…).

SQLite fallback: in dev (aiosqlite) there is no NOTIFY; ``notify_event``
then queues the event directly to in-process subscribers — SSE still works
within the single dev process.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import AsyncIterator

from fastapi import Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import CurrentUser

logger = logging.getLogger(__name__)

CHANNEL = "infra_events"

# Connected SSE subscribers: one asyncio.Queue each.
_subscribers: set[asyncio.Queue] = set()
_listener_task: asyncio.Task | None = None


# -- emitting ----------------------------------------------------------------

async def notify_event(session: AsyncSession, event_type: str, **payload) -> None:
    """Emit a change event; delivered when the surrounding tx commits."""
    data = json.dumps({"type": event_type, **payload})
    if get_settings().database_url.startswith("sqlite"):
        _fanout(data)
        return
    await session.execute(text(f"SELECT pg_notify({CHANNEL!r}, :p)"), {"p": data})


def _fanout(raw: str) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(raw)
        except asyncio.QueueFull:  # slow consumer: drop rather than block
            pass


# -- LISTEN bridge -----------------------------------------------------------

async def _listen_loop() -> None:
    """LISTEN on the events channel; push notifications to subscribers.

    Uses a dedicated asyncpg connection (SQLAlchemy has no portable async
    LISTEN). Notifications may be emitted by any backend replica or worker.
    """
    import asyncpg

    url = get_settings().database_url
    dsn = url.split("://", 1)[1]          # strip the "+asyncpg" dialect part
    dsn = "postgresql://" + dsn
    while True:
        try:
            conn = await asyncpg.connect(dsn)
            await conn.add_listener(CHANNEL, lambda *args: _fanout(args[3]))
            logger.info("Listening on Postgres channel %r", CHANNEL)
            while True:
                await asyncio.sleep(3600.0)  # keep the connection alive
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — reconnect forever
            logger.warning("Event listener disconnected (%s); retrying in 2s", exc)
            await asyncio.sleep(2.0)


def start_listener() -> None:
    """Start the LISTEN task once (called from the app lifespan)."""
    global _listener_task
    if _listener_task is None or _listener_task.done():
        _listener_task = asyncio.create_task(_listen_loop())


async def stop_listener() -> None:
    global _listener_task
    if _listener_task is not None:
        _listener_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _listener_task
        _listener_task = None


# -- SSE endpoint ------------------------------------------------------------

async def _event_stream() -> AsyncIterator[str]:
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    _subscribers.add(queue)
    try:
        # Initial comment so the client stream is opened immediately
        yield ": connected\n\n"
        while True:
            try:
                raw = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                # Keepalive comment every 15s: proves the connection is
                # alive end-to-end AND lets clients with a read-timeout
                # detect a dead stream within seconds instead of hanging
                # on a socket that will never deliver again (silent death
                # after a proxy hiccup or a backend restart).
                yield ": keepalive\n\n"
                continue
            try:
                evt = json.loads(raw)
            except Exception:  # noqa: BLE001
                continue
            yield f"data: {json.dumps(evt)}\n\n"
    finally:
        _subscribers.discard(queue)


async def events(user: CurrentUser) -> StreamingResponse:
    """SSE stream of change events (auth: Bearer, same as other endpoints)."""
    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
