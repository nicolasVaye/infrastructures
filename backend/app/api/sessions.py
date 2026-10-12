"""Session tracking endpoints: who is connected, revoke sessions."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.core.db import utcnow
from app.core.security import AdminUser, CurrentUser, DbSession
from app.events import notify_event
from app.services import connected_sessions, record, revoke_session
from shared.enums import AuditAction
from shared.models import SessionOut

router = APIRouter(tags=["sessions"])


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(admin: AdminUser, session: DbSession) -> list[SessionOut]:
    """Admin view: all currently connected clients (web or automation)."""
    records = await connected_sessions(session)
    return [SessionOut.model_validate(r) for r in records]


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
    await record(session, AuditAction.SESSION_REVOKED, user_id=admin.id,
                 username=admin.username, target=session_id)
