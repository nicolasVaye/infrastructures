"""Audit trail endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.security import AdminUser, DbSession
from app.services import audit_clear, audit_list
from shared.models import AuditOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditOut])
async def list_audit(
    admin: AdminUser,
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    username: str | None = None,
    action: str | None = None,
    actions: str | None = None,
) -> list[AuditOut]:
    records = await audit_list(
        session, limit=limit, offset=offset, username=username, action=action,
        actions=[a.strip() for a in actions.split(",") if a.strip()] if actions else None,
    )
    return [AuditOut.model_validate(a) for a in records]


@router.get("/count")
async def count_audit(
    admin: AdminUser,
    session: DbSession,
    username: str | None = None,
    action: str | None = None,
    actions: str | None = None,
) -> dict:
    from sqlalchemy import func, select
    from app.core.db import AuditLogRecord
    stmt = select(func.count()).select_from(AuditLogRecord)
    if username:
        stmt = stmt.where(AuditLogRecord.username == username)
    if actions:
        stmt = stmt.where(AuditLogRecord.action.in_(
            [a.strip() for a in actions.split(",") if a.strip()]))
    elif action:
        stmt = stmt.where(AuditLogRecord.action == action)
    return {"count": await session.scalar(stmt) or 0}


@router.delete("", status_code=204)
async def clear_audit(admin: AdminUser, session: DbSession) -> None:
    await audit_clear(session)
