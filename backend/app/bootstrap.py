"""Database bootstrap: schema creation + seeding.

Called both by the API (lifespan) and by every worker/scheduler process on
startup, so whichever starts first creates the schema — no startup ordering
dependency between containers. ``create_all`` and the seed are idempotent.
"""

from __future__ import annotations

import logging

from sqlalchemy import select, text

from app.core.db import (Base, RoleRecord, UserRecord, get_engine,
                         get_session_factory)
from app.core.security import hash_password
from app.core.config import get_settings
from shared.enums import UserRole

logger = logging.getLogger(__name__)

_SEED_ROLES = [
    (UserRole.ADMIN.value, "Full administration"),
    (UserRole.OPERATOR.value, "Can submit and manage jobs"),
    (UserRole.USER.value, "Read-only dashboard access"),
]


# Advisory lock key: serialises schema creation/seeding when several
# processes (API, worker, scheduler) start at the same time.
_LOCK_KEY = 918273645


async def ensure_schema() -> None:
    """Create all tables if missing, then seed roles and the bootstrap admin.

    Guarded by a transaction-scoped advisory lock so concurrent processes
    (backend, worker, scheduler all call this on startup) cannot race on
    ``CREATE TABLE`` (duplicate pg_type) or double-seed the admin.
    """
    settings = get_settings()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY}
        )
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight migrations for columns added after the first release;
        # create_all only builds missing TABLES, never missing COLUMNS.
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_version"
            " INTEGER NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS theme"
            " VARCHAR(8) NOT NULL DEFAULT 'light'"
        ))

    async with get_session_factory()() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY}
        )
        role_ids: dict[str, int] = {}
        for name, description in _SEED_ROLES:
            role = (await session.scalars(
                select(RoleRecord).where(RoleRecord.name == name)
            )).first()
            if role is None:
                session.add(RoleRecord(name=name, description=description))
                await session.flush()
                role = (await session.scalars(
                    select(RoleRecord).where(RoleRecord.name == name)
                )).first()
            role_ids[name] = role.id

        admin = (await session.scalars(
            select(UserRecord)
            .where(UserRecord.username == settings.seed_admin_username)
        )).first()
        if admin is None:
            session.add(UserRecord(
                username=settings.seed_admin_username,
                password_hash=hash_password(settings.seed_admin_password),
                role_id=role_ids[UserRole.ADMIN.value],
                is_active=True,
                must_change_password=True,
            ))
            logger.warning("Seeded default admin (%s/%s); change the password.",
                           settings.seed_admin_username, settings.seed_admin_password)
        await session.commit()
