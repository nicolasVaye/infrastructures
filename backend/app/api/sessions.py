"""Session tracking endpoints: who is connected, revoke sessions."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionRecord, utcnow
from app.core.security import AdminUser, CurrentUser, DbSession
from app.events import notify_event
from app.services import connected_sessions, record, revoke_session
from shared.enums import AuditAction
from shared.models import SessionOut

router = APIRouter(tags=["sessions"])


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(admin: AdminUser, session: DbSession,
                        include_inactive: bool = False) -> list[SessionOut]:
    """Admin view: all currently connected clients (web or automation).

    With ``include_inactive`` the response ALSO carries the zombie sessions:
    not revoked and not expired, but silent for longer than the heartbeat
    TTL (browser closed without logout). They stay in the DB until the
    maintenance cleanup job sweeps them — the Sessions tab can show them
    (flagged ``active=False``) so the admin sees the difference between
    "connected" and "leftover" instead of trusting a list that mixes both.
    """
    records = await connected_sessions(session)
    out = [SessionOut.model_validate(r) for r in records]
    for s in out:
        s.active = True
    if include_inactive:
        settings = get_settings()
        threshold = utcnow() - timedelta(seconds=settings.heartbeat_ttl_seconds)
        stale = (await session.scalars(
            select(SessionRecord).where(
                SessionRecord.revoked_at.is_(None),
                SessionRecord.expires_at > utcnow(),
                SessionRecord.last_activity < threshold,
            )
        )).all()
        for r in stale:
            s = SessionOut.model_validate(r)
            s.active = False
            out.append(s)
    return out


@router.get("/sessions/mine", response_model=list[SessionOut])
async def my_sessions(user: CurrentUser, session: DbSession) -> list[SessionOut]:
    """Non-admin view: the caller's own active sessions."""
    records = [s for s in await connected_sessions(session) if s.user_id == user.id]
    return [SessionOut.model_validate(s) for s in records]


@router.delete("/sessions/{session_id}", status_code=204)
async def kick_session(session_id: str, admin: AdminUser, session: DbSession) -> None:
    """Revoke any session (kick a user)."""
    if not await revoke_session(session, session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found or already revoked")
    await notify_event(session, "session_revoked", session_id=session_id)
    # Live sessions list: a kick changes who is connected.
    await notify_event(session, "sessions_changed")
    await record(session, AuditAction.SESSION_REVOKED, user_id=admin.id,
                 username=admin.username, target=session_id)
