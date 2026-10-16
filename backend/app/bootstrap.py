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


async def run_migrations() -> None:
    """Run ``alembic upgrade head`` in a worker thread.

    Uses Alembic's programmatic API: the migration directory ships with the
    code (backend/migrations), the baseline revision creates the current
    schema, and every future schema change is a new revision — reviewable,
    revertible and applied exactly once per database, unlike the old
    "ALTER TABLE IF NOT EXISTS" bootstrap. The advisory lock held by the
    caller serializes concurrent container startups.

    env.py drives an asyncio loop of its own (``asyncio.run``), which is
    impossible inside the caller's already-running event loop — so the
    upgrade runs in a separate thread and env.py connects with its own
    engine. Startup serialization is preserved because the caller holds the
    transaction-scoped advisory lock for the whole duration of the upgrade.
    """
    import asyncio
    from alembic import command
    from alembic.config import Config
    from pathlib import Path

    migrations_dir = Path(__file__).resolve().parent.parent / "migrations"
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir))
    # env.py reads the URL from the app settings (async driver included).
    await asyncio.to_thread(command.upgrade, cfg, "head")


# Advisory lock key: serialises schema creation/seeding when several
# processes (API, worker, scheduler) start at the same time.
_LOCK_KEY = 918273645

# Known-default / weak JWT secrets: deploying with one of these means anyone
# reading the public compose file can forge tokens. Refuse to boot instead.
_WEAK_SECRETS = {
    "change_me_in_production", "change-me-in-production", "changeme",
    "please-change-me", "secret", "test", "test-secret", "insecure",
    "admin",
}


def validate_runtime_secrets() -> None:
    """Refuse to start with default/weak secrets (fail-fast).

    Covers JWT_SECRET and the seed admin password: booting a production
    deployment with credentials that ship in the public docker-compose.yaml
    is the single most dangerous misconfiguration, so every process (API,
    worker, scheduler) checks this via ensure_schema and dies loudly instead.
    Throw-away local environments can opt out with INSECURE_DEV=1.
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
    if settings.seed_admin_password.lower() in _WEAK_SECRETS:
        raise RuntimeError(
            "Refusing to start: SEED_ADMIN_PASSWORD is a known default "
            f"({settings.seed_admin_password!r}). Anyone reading the public "
            "compose file could take over the bootstrap admin. Set a strong "
            "SEED_ADMIN_PASSWORD, or export INSECURE_DEV=1 for local dev."
        )


async def ensure_schema() -> None:
    """Create all tables if missing, then seed roles and the bootstrap admin.

    Guarded by a transaction-scoped advisory lock so concurrent processes
    (backend, worker, scheduler all call this on startup) cannot race on
    ``CREATE TABLE`` (duplicate pg_type) or double-seed the admin.
    """
    settings = get_settings()
    validate_runtime_secrets()
    is_sqlite = settings.database_url.startswith("sqlite")
    engine = get_engine()
    async with engine.begin() as conn:
        if not is_sqlite:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY}
            )
        # Versioned schema: Alembic owns the database shape from now on
        # (see migrations/). create_all + ad-hoc "ALTER TABLE IF NOT EXISTS"
        # statements cannot express RENAMES, type changes or data backfills,
        # which is exactly what a multi-customer production database will
        # eventually need. If Alembic is unavailable (stripped runtime), we
        # fall back to create_all for throw-away dev databases.
        try:
            await run_migrations()
        except ImportError:
            logger.warning("Alembic not installed — falling back to "
                           "create_all (dev only; production images must "
                           "ship alembic).")
            await conn.run_sync(Base.metadata.create_all)
        # Global SSE event sequence: every backend replica draws the next
        # event number from the SAME Postgres sequence, so Last-Event-ID
        # replay keeps a coherent order across a scaled-out backend fleet.
        if not is_sqlite:
            await conn.execute(text(
                "CREATE SEQUENCE IF NOT EXISTS infra_event_seq START 1"
            ))

    async with get_session_factory()() as session:
        if not is_sqlite:
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
