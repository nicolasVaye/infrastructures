"""User activity tracking (navigation events) + realtime diagnostics log.

The frontend POSTs one small event per sub-page navigation (see
``services.api_client.track_activity``); ``GET /activity/users`` aggregates
the last 4 hours into the per-user mini bar chart of the Users tab (24 bars
of 10 minutes, plus a "last 15 minutes" count for the tooltip).

``GET /system/events-log`` exposes the ``event_log`` table (SSE drops,
LISTEN bridge disconnects…) so an admin can diagnose live-update lags from
the App Settings page without reading container logs.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import (ActivityRecord, EventLogRecord, SessionRecord,
                         UserRecord, utcnow)
from app.core.security import (AdminUser, CurrentUser, DbSession,
                               SessionId)

router = APIRouter(tags=["activity"])

# How long raw navigation events are kept. The Users tab only reads the last
# 4 hours; the extra margin covers clock skew and future chart tweaks.
_RETENTION = timedelta(hours=48)


@router.post("/activity")
async def record_activity(body: dict, user: CurrentUser, sid: SessionId,
                          session: DbSession) -> dict:
    """Record one navigation by the caller (fire-and-forget client-side).

    The session id comes from the JWT ('sid') — no payload from the client —
    so the event is attributed to the exact browser that navigated, and
    /activity/sessions can split a user's activity per browser/client.
    """
    path = str((body or {}).get("path") or "/")[:200]
    session.add(ActivityRecord(user_id=user.id, session_id=sid, path=path))
    # Opportunistic trim: one DELETE per navigation is cheap at this volume
    # and keeps the table small without a dedicated worker job.
    await session.execute(delete(ActivityRecord).where(
        ActivityRecord.created_at < utcnow() - _RETENTION))
    return {"status": "ok"}


def _aggregate(rows: list[ActivityRecord], now) -> dict:
    """Shared 24×10-minute bucketing for the per-user and per-session views."""
    cutoff15 = now - timedelta(minutes=15)
    entry = {'bars': [0] * 24, 'last15': 0, 'last': None}
    for r in rows:
        idx = 23 - int((now - r.created_at).total_seconds() // 600)
        if 0 <= idx < 24:
            entry['bars'][idx] += 1
        if r.created_at >= cutoff15:
            entry['last15'] += 1
        if entry['last'] is None or r.created_at > entry['last']:
            entry['last'] = r.created_at
    return entry


@router.get("/activity/users")
async def activity_users(admin: AdminUser, session: DbSession) -> list[dict]:
    """Per-user activity summary over the last 4 hours (admin view).

    Cumulative across ALL of a user's sessions: someone connected in Chrome
    and Firefox has one merged sparkline — that is the Users tab's contract.
    ``bars``: 24 buckets of 10 minutes, oldest first. ``last15`` and
    ``last_activity`` feed the tooltip.
    """
    now = utcnow()
    start = now - timedelta(hours=4)
    rows = (await session.scalars(
        select(ActivityRecord)
        .where(ActivityRecord.created_at >= start)
        .order_by(ActivityRecord.created_at)
    )).all()

    per_user: dict[int, list[ActivityRecord]] = {}
    for r in rows:
        per_user.setdefault(r.user_id, []).append(r)

    out: list[dict] = []
    for uid, user_rows in per_user.items():
        user = await session.get(UserRecord, uid)
        if user is None:
            continue
        e = _aggregate(user_rows, now)
        out.append({
            'username': user.username,
            'bars': e['bars'],
            'last15': e['last15'],
            'last_activity': e['last'].isoformat() if e['last'] else None,
        })
    return out


@router.get("/activity/sessions")
async def activity_sessions(admin: AdminUser, session: DbSession) -> list[dict]:
    """Per-SESSION activity summary over the last 4 hours (admin view).

    Same 24×10-minute buckets as /activity/users, but keyed by session id:
    the Sessions tab shows one sparkline per connected browser/client, so a
    user on Chrome and Firefox gets two distinct graphs instead of the merged
    Users-tab view. Only sessions still active are returned.
    """
    now = utcnow()
    start = now - timedelta(hours=4)
    rows = (await session.scalars(
        select(ActivityRecord)
        .where(ActivityRecord.created_at >= start,
               ActivityRecord.session_id.is_not(None))
        .order_by(ActivityRecord.created_at)
    )).all()

    per_sid: dict[str, list[ActivityRecord]] = {}
    for r in rows:
        per_sid.setdefault(r.session_id, []).append(r)

    out: list[dict] = []
    for sid, sid_rows in per_sid.items():
        record = await session.get(SessionRecord, sid)
        if record is None or record.revoked_at is not None:
            continue
        # Same freshness rules as the Sessions tab itself (connected_sessions):
        # a browser closed without logout leaves the record un-revoked until
        # TTL expiry — those zombie sessions must not feed sparklines.
        if record.expires_at <= now:
            continue
        threshold = now - timedelta(seconds=get_settings().heartbeat_ttl_seconds)
        if record.last_activity < threshold:
            continue
        e = _aggregate(sid_rows, now)
        out.append({
            'session_id': sid,
            'username': record.username,
            'bars': e['bars'],
            'last15': e['last15'],
            'last_activity': e['last'].isoformat() if e['last'] else None,
        })
    return out


@router.get("/system/sse-stats")
async def sse_stats(admin: AdminUser) -> dict:
    """Live counters of the realtime machinery (backend app.events).

    Lets the admin compare what the SERVER produced (events fanned out,
    keepalives, subscribers) against what a client RECEIVED — the fastest
    way to tell whether a dead stream is a backend or a transport issue.
    """
    from app import events as _events
    return _events.stats()


@router.get("/system/events-log")
async def events_log(admin: AdminUser, session: DbSession) -> list[dict]:
    """Last 50 realtime-machinery incidents (SSE drops, LISTEN reconnects)."""
    rows = (await session.scalars(
        select(EventLogRecord).order_by(EventLogRecord.id.desc()).limit(50)
    )).all()
    return [
        {
            'created_at': r.created_at.isoformat(),
            'level': r.level,
            'source': r.source,
            'message': r.message,
        }
        for r in reversed(rows)
    ]
