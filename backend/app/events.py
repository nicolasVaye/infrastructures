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
from collections import deque
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import CurrentUser

logger = logging.getLogger(__name__)

CHANNEL = "infra_events"

# Connected SSE subscribers: one asyncio.Queue each (items: (seq, raw_json)).
_subscribers: set[asyncio.Queue] = set()
_listener_task: asyncio.Task | None = None

# Observability counters (surfaced via GET /system/sse-stats): the admin can
# see whether keepalives/events are actually being produced server-side
# even when a client claims it receives nothing.
_keepalives: int = 0
_fanouts: int = 0
_client_id: int = 0


def stats() -> dict:
    """Live snapshot of the realtime machinery (admin diagnostics)."""
    return {
        "subscribers": len(_subscribers),
        "seq": _seq,
        "buffered": len(_ring),
        "keepalives": _keepalives,
        "fanouts": _fanouts,
    }

# -- event log (DB) -----------------------------------------------------------

async def log_event_issue(level: str, source: str, message: str) -> None:
    """Persist a realtime-machinery incident to the ``event_log`` table.

    Failures here must never break event delivery: log to the file logger too
    when the DB write itself fails.
    """
    from app.core.db import EventLogRecord, get_session_factory
    try:
        async with get_session_factory()() as session:
            session.add(EventLogRecord(
                level=level, source=source,
                message=f"{message} @ {datetime.now(timezone.utc).isoformat()}"
                        [:2000]))
            await session.commit()
    except Exception as exc:  # noqa: BLE001  diagnostics must never raise
        logger.warning("Could not persist event-log entry (%s): %s", message, exc)


def log_event_issue_bg(level: str, source: str, message: str) -> None:
    """Fire-and-forget variant usable from sync callbacks (LISTEN handler)."""
    try:
        asyncio.get_running_loop().create_task(log_event_issue(level, source, message))
    except RuntimeError:  # no loop (unit tests) → file log only
        logger.warning("[%s/%s] %s", level, source, message)


# -- emitting ----------------------------------------------------------------

# Sequence numbers + ring buffer: best practice for at-least-once SSE.
# Every event gets a monotonic ``seq``; the last 200 stay buffered so a
# client that reconnects (read timeout, backend restart, proxy hiccup…)
# replays everything it missed instead of silently losing events.
# GLOBAL sequence: on Postgres the number is drawn from the shared
# ``infra_event_seq`` sequence INSIDE the emitting transaction and embedded
# in the notification, so every replica of a scaled-out backend assigns the
# same coherent order — a per-process counter made Last-Event-ID replay
# incoherent as soon as backend > 1 replica. ``_seq`` only remains as the
# fallback for the SQLite dev path (single process).
_seq: int = 0
_ring: deque[tuple[int, str]] = deque(maxlen=200)
_REPLAY_WINDOW = _ring.maxlen


async def notify_event(session: AsyncSession, event_type: str, **payload) -> None:
    """Emit a change event; delivered when the surrounding tx commits."""
    if get_settings().database_url.startswith("sqlite"):
        _fanout(json.dumps({"type": event_type, **payload}))
        return
    # Draw the GLOBAL sequence number in the same transaction: committed
    # events get contiguous ids across all replicas; rolled-back ones leave
    # a hole, which clients self-heal via the _resync mechanism.
    seq = (await session.execute(
        text("SELECT nextval('infra_event_seq')"))).scalar_one()
    data = json.dumps({"type": event_type, "_seq": seq, **payload})
    await session.execute(text(f"SELECT pg_notify({CHANNEL!r}, :p)"), {"p": data})


def _fanout(raw: str, *, seq: int | None = None) -> None:
    """Assign a sequence number, buffer the event, push to subscribers."""
    global _seq, _fanouts
    if seq is None:
        # Notification without an embedded global seq (emitted by a replica
        # running an older build): fall back to the local counter.
        try:
            seq = int(json.loads(raw).get("_seq") or 0)
        except Exception:  # noqa: BLE001 — malformed payload: local fallback
            seq = 0
        if seq <= 0:
            _seq += 1
            seq = _seq
    _fanouts += 1
    _ring.append((seq, raw))
    if _subscribers:
        logger.info("SSE event seq=%s fanned out to %s subscriber(s)",
                    seq, len(_subscribers))
    for q in list(_subscribers):
        try:
            q.put_nowait((seq, raw))
        except asyncio.QueueFull:
            # Slow consumer: drop rather than block the fanout loop, but
            # leave a trace — a dropped event is a lost UI refresh and the
            # admin should be able to see why live updates lagged.
            log_event_issue_bg("warning", "sse",
                               f"event {seq} dropped: subscriber queue full "
                               f"({len(_subscribers)} subscribers)")


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
            # Reconnect also closes the gap left by events emitted while
            # no listener was attached (they were still buffered by the
            # ring, but subscribers had nothing feeding them): views
            # resync via the _resync event below.
            log_event_issue_bg("info", "listen", "LISTEN bridge connected")
            while True:
                await asyncio.sleep(3600.0)  # keep the connection alive
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — reconnect forever
            logger.warning("Event listener disconnected (%s); retrying in 2s", exc)
            log_event_issue_bg("warning", "listen",
                               f"LISTEN bridge disconnected: {exc}; reconnecting in 2s")
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

_RESYNC = json.dumps({"type": "_resync"})


async def _event_stream(last_id: int | None) -> AsyncIterator[str]:
    global _keepalives, _client_id
    _client_id += 1
    cid = _client_id
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    _subscribers.add(queue)
    logger.info("SSE subscriber #%s connected (last_event_id=%s, now %s subscriber(s))",
                cid, last_id, len(_subscribers))
    try:
        # SSE best practices: advertise the reconnect interval, then replay
        # everything the client missed while disconnected (Last-Event-ID).
        yield "retry: 5000\n: connected\n\n"
        if last_id is not None:
            missed = [(s, r) for (s, r) in _ring if s > last_id]
            if _ring and last_id + 1 < _ring[0][0]:
                # The client fell further behind than the replay window: the
                # evicted events are unrecoverable, so tell it to resync its
                # views from scratch (bump all refresh counters) and log the
                # incident for the diagnostics page.
                log_event_issue_bg("warning", "sse",
                                   f"replay gap for client {last_id}: oldest "
                                   f"buffered event is {_ring[0][0]} "
                                   f"(window {_REPLAY_WINDOW})")
                yield f"id: 0\ndata: {_RESYNC}\n\n"
            for seq, raw in missed:
                yield f"id: {seq}\ndata: {raw}\n\n"
        while True:
            try:
                seq, raw = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                # Keepalive comment every 15s: proves the connection is
                # alive end-to-end AND lets clients with a read-timeout
                # detect a dead stream within seconds instead of hanging
                # on a socket that will never deliver again (silent death
                # after a proxy hiccup or a backend restart).
                _keepalives += 1
                if _keepalives <= 3 or _keepalives % 20 == 0:
                    logger.info("SSE keepalive #%s sent to %s subscriber(s)",
                                _keepalives, len(_subscribers))
                yield ": keepalive\n\n"
                continue
            yield f"id: {seq}\ndata: {raw}\n\n"
    finally:
        _subscribers.discard(queue)
        logger.info("SSE subscriber #%s disconnected (%s left)",
                    cid, len(_subscribers))


async def events(user: CurrentUser, request: Request) -> StreamingResponse:
    """SSE stream of change events (auth: Bearer, same as other endpoints).

    Standard SSE resumption: the client echoes the last received event id in
    the ``Last-Event-ID`` header (httpx here, browsers do it natively) and
    the stream starts by replaying what was emitted during the disconnect.
    """
    last_id = None
    raw = request.headers.get("last-event-id")
    if raw:
        try:
            last_id = int(raw)
        except ValueError:
            last_id = None
    return StreamingResponse(
        _event_stream(last_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
