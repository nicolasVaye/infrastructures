"""Cross-cutting services: audit trail recording and session helpers."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import AuditLogRecord, SessionRecord, UserRecord, utcnow
from app.core.security import client_ip


async def record(
    session: AsyncSession,
    action: str,
    *,
    user_id: int | None = None,
    username: str = "unknown",
    target: str | None = None,
    details: str | None = None,
    ip: str | None = None,
) -> None:
    """Append one audit entry. Never raises — auditing must not break actions."""
    try:
        session.add(AuditLogRecord(
            action=action.value if hasattr(action, "value") else str(action),
            user_id=user_id, username=username, target=target, details=details, ip=ip,
        ))
        await session.flush()
    except Exception:  # pragma: no cover
        pass


async def audit_list(
    session: AsyncSession, *, limit: int = 100, offset: int = 0,
    username: str | None = None, action: str | None = None,
) -> list[AuditLogRecord]:
    query = select(AuditLogRecord).order_by(AuditLogRecord.id.desc())
    if username:
        query = query.where(AuditLogRecord.username == username)
    if action:
        query = query.where(AuditLogRecord.action == action)
    return list((await session.scalars(query.limit(limit).offset(offset))).all())


async def audit_clear(session: AsyncSession) -> None:
    await session.execute(delete(AuditLogRecord))


# -- sessions ----------------------------------------------------------------

async def create_session_record(
    session: AsyncSession, user: UserRecord, *, client: str,
    ip: str | None, user_agent: str | None,
) -> SessionRecord:
    settings = get_settings()
    record = SessionRecord(
        user_id=user.id,
        client=client,
        ip=ip,
        user_agent=user_agent[:255] if user_agent else None,
        expires_at=utcnow() + timedelta(seconds=settings.refresh_token_ttl_seconds),
    )
    session.add(record)
    await session.flush()
    return record


async def revoke_session(session: AsyncSession, session_id: str) -> bool:
    record = await session.get(SessionRecord, session_id)
    if record is None or record.revoked_at is not None:
        return False
    record.revoked_at = utcnow()
    return True


async def connected_sessions(session: AsyncSession) -> list[SessionRecord]:
    """Sessions considered 'connected': not revoked, not expired, recent heartbeat."""
    settings = get_settings()
    threshold = utcnow() - timedelta(seconds=settings.heartbeat_ttl_seconds)
    query = (
        select(SessionRecord)
        .where(
            SessionRecord.revoked_at.is_(None),
            SessionRecord.expires_at > utcnow(),
            SessionRecord.last_activity >= threshold,
        )
        .order_by(SessionRecord.last_activity.desc())
    )
    return list((await session.scalars(query)).all())


async def prune_expired_sessions(session: AsyncSession) -> int:
    """Mark expired sessions as revoked (housekeeping)."""
    result = await session.execute(
        select(SessionRecord).where(
            SessionRecord.revoked_at.is_(None), SessionRecord.expires_at <= utcnow()
        )
    )
    count = 0
    for record in result.scalars():
        record.revoked_at = utcnow()
        count += 1
    return count
