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

from app.core.db import (ActivityRecord, EventLogRecord, UserRecord,
                         utcnow)
from app.core.security import AdminUser, CurrentUser, DbSession

router = APIRouter(tags=["activity"])

# How long raw navigation events are kept. The Users tab only reads the last
# 4 hours; the extra margin covers clock skew and future chart tweaks.
_RETENTION = timedelta(hours=48)


@router.post("/activity")
async def record_activity(body: dict, user: CurrentUser, session: DbSession) -> dict:
    """Record one navigation by the caller (fire-and-forget client-side)."""
    path = str((body or {}).get("path") or "/")[:200]
    session.add(ActivityRecord(user_id=user.id, path=path))
    # Opportunistic trim: one DELETE per navigation is cheap at this volume
    # and keeps the table small without a dedicated worker job.
    await session.execute(delete(ActivityRecord).where(
        ActivityRecord.created_at < utcnow() - _RETENTION))
    return {"status": "ok"}


@router.get("/activity/users")
async def activity_users(admin: AdminUser, session: DbSession) -> list[dict]:
    """Per-user activity summary over the last 4 hours (admin view).

    ``bars``: 24 buckets of 10 minutes, oldest first — the Users tab renders
    them as a sparkline. ``last15`` and ``last_activity`` feed the tooltip.
    """
    now = utcnow()
    start = now - timedelta(hours=4)
    rows = (await session.scalars(
        select(ActivityRecord)
        .where(ActivityRecord.created_at >= start)
        .order_by(ActivityRecord.created_at)
    )).all()

    cutoff15 = now - timedelta(minutes=15)
    per_user: dict[int, dict] = {}
    for r in rows:
        entry = per_user.setdefault(r.user_id, {'bars': [0] * 24,
                                                'last15': 0,
                                                'last': r.created_at})
        idx = 23 - int((now - r.created_at).total_seconds() // 600)
        if 0 <= idx < 24:
            entry['bars'][idx] += 1
        if r.created_at >= cutoff15:
            entry['last15'] += 1
        if r.created_at > entry['last']:
            entry['last'] = r.created_at

    out: list[dict] = []
    for uid, e in per_user.items():
        user = await session.get(UserRecord, uid)
        if user is None:
            continue
        out.append({
            'username': user.username,
            'bars': e['bars'],
            'last15': e['last15'],
            'last_activity': e['last'].isoformat() if e['last'] else None,
        })
    return out


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
