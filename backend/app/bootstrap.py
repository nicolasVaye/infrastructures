"""Database bootstrap: schema creation + seeding.

Called both by the API (lifespan) and by every worker/scheduler process on
startup, so whichever starts first creates the schema — no startup ordering
dependency between containers. ``create_all`` and the seed are idempotent.
"""

from __future__ import annotations

import logging

from sqlalchemy import select, text

from app.core.db import (Base, RoleRecord, ScheduleRecord, UserRecord, get_engine,
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

# Known-default / weak JWT secrets: deploying with one of these means anyone
# reading the public compose file can forge tokens. Refuse to boot instead.
_WEAK_SECRETS = {
    "change_me_in_production", "change-me-in-production", "changeme",
    "please-change-me", "secret", "test", "test-secret", "insecure",
}


def validate_runtime_secrets() -> None:
    """Refuse to start with a default/weak JWT_SECRET.

    Called by every process (API, worker, scheduler) via ensure_schema, so a
    misconfigured deployment fails loudly at boot instead of signing tokens
    with a secret that ships in the public docker-compose.yaml. Throw-away
    local environments can opt out with INSECURE_DEV=1.
    """
    import os
    settings = get_settings()
    if os.environ.get("INSECURE_DEV") == "1":
        return
    secret = settings.jwt_secret.strip()
    if secret.lower() in _WEAK_SECRETS or len(secret) < 32:
        raise RuntimeError(
            "Refusing to start: JWT_SECRET is a known default or too weak "
            f"(< 32 chars, got {len(secret)}). Set a strong JWT_SECRET, or "
            "export INSECURE_DEV=1 only for throw-away local development."
        )


async def ensure_schema() -> None:
    """Create all tables if missing, then seed roles and the bootstrap admin.

    Guarded by a transaction-scoped advisory lock so concurrent processes
    (backend, worker, scheduler all call this on startup) cannot race on
    ``CREATE TABLE`` (duplicate pg_type) or double-seed the admin.
    """
    settings = get_settings()
    validate_runtime_secrets()
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
        await conn.execute(text(
            "ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS session_id"
            " VARCHAR(36)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_activity_events_session_id"
            " ON activity_events (session_id)"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS refresh_token_hash"
            " VARCHAR(64)"
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

        # Daily session purge (see maintenance.cleanup_sessions in the
        # worker). Seeded once, idempotently; admins can disable or retune
        # it through the schedules table.
        cleanup = (await session.scalars(
            select(ScheduleRecord).where(
                ScheduleRecord.job_type == "maintenance.cleanup_sessions")
        )).first()
        if cleanup is None:
            session.add(ScheduleRecord(
                job_type="maintenance.cleanup_sessions",
                params={"keep_days": 7},
                cron="0 3 * * *",  # daily at 03:00
                enabled=True,
            ))
            logger.info("Seeded daily session cleanup schedule (03:00, keep 7 days).")

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
