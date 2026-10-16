"""Async SQLAlchemy engine, ORM models and session dependency."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.ext.asyncio import (AsyncEngine, AsyncSession,
                                    async_sessionmaker, create_async_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class RoleRecord(Base):
    """Catalog of roles (seeded: admin, operator, user)."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(255))

    users: Mapped[list["UserRecord"]] = relationship(back_populates="role_ref")


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # None for OIDC users (no local password)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    must_change_password: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    email: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(128))
    avatar: Mapped[str | None] = mapped_column(Text)
    # Bumped on every avatar change; reported by the heartbeat so other
    # browsers/tabs of the same user can live-reload the image from /avatar.
    avatar_version: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    language: Mapped[str] = mapped_column(String(8), nullable=False, server_default=text("'en'"))
    # UI theme preference: 'light' or 'dark' (applied at login by the frontend).
    theme: Mapped[str] = mapped_column(String(8), nullable=False, server_default=text("'light'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    # Federated identity: where the credentials live, and the external subject
    # (the 'sub' claim of the OIDC ID token) when auth_provider == 'oidc'.
    auth_provider: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'local'"), index=True)
    external_subject: Mapped[str | None] = mapped_column(String(255))
    idp_id: Mapped[int | None] = mapped_column(ForeignKey("identity_providers.id"))

    role_ref: Mapped["RoleRecord"] = relationship(lazy="joined")
    sessions: Mapped[list["SessionRecord"]] = relationship(back_populates="user")
    # The provider the account is federated through (None for local users).
    idp_ref: Mapped["IdentityProviderRecord | None"] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_users_oidc_identity", "idp_id", "external_subject", unique=True),
    )

    @property
    def role(self) -> str:
        return self.role_ref.name


class IdentityProviderRecord(Base):
    """An external OIDC identity provider (e.g. a Keycloak realm).

    Managed by admins from the frontend 'Providers' page; the login page lists
    every enabled provider as an alternative to local credentials.
    """

    __tablename__ = "identity_providers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    issuer_url: Mapped[str] = mapped_column(String(255), nullable=False)
    client_id: Mapped[str] = mapped_column(String(128), nullable=False)
    client_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    auto_create_users: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    default_role: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'user'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class SessionRecord(Base):
    """One authenticated client (web browser, automation, CLI...).

    Created on login, refreshed by heartbeats, revoked on logout — this is the
    table that answers "who is connected?".
    """

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: secrets.token_hex(16))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    client: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'web'"))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_activity: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Refresh-token rotation anchor: hash of the LATEST refresh token issued
    # for this session. A presented token that no longer matches is a replay
    # (see /auth/refresh) — the session is then revoked as compromised.
    refresh_token_hash: Mapped[str | None] = mapped_column(String(64))

    user: Mapped["UserRecord"] = relationship(back_populates="sessions", lazy="joined")

    @property
    def username(self) -> str:
        return self.user.username

    @property
    def auth_provider(self) -> str:
        return "idp" if self.user.idp_id else "local"

    @property
    def idp_name(self) -> str | None:
        return self.user.idp_ref.name if self.user.idp_ref else None

    @property
    def has_avatar(self) -> bool:
        return bool(self.user.avatar)

    @property
    def avatar_version(self) -> int:
        return self.user.avatar_version or 0


class AuditLogRecord(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int | None] = mapped_column()
    target: Mapped[str | None] = mapped_column(String(255))
    details: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(64))


class JobRecord(Base):
    """A unit of work submitted through the API, executed by workers.

    The table doubles as the job queue: workers claim rows with
    ``SELECT ... FOR UPDATE SKIP LOCKED`` so N workers can scale horizontally.
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True, default="queued")
    priority: Mapped[int] = mapped_column(nullable=False, default=5)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_jobs_claim", "status", "priority"),
    )


class SettingRecord(Base):
    """Global application settings (key/value), e.g. the custom logo."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)


class ScheduleRecord(Base):
    """CRON-based recurring job submission, consumed by the scheduler worker."""

    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    cron: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActivityRecord(Base):
    """One user navigation in the frontend (sub-page visited).

    Written by POST /activity on every path change; aggregated by
    GET /activity/users into the per-user 4-hour mini bar chart. Rows older
    than 48h are trimmed opportunistically — the raw granularity is only
    needed for the activity sparkline, the audit log keeps the durable
    business trail.
    """

    __tablename__ = "activity_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(nullable=False, index=True)
    # Which browser/client emitted the navigation (JWT 'sid'): lets
    # GET /activity/sessions split a user's activity per session (Chrome
    # vs Firefox vs automation client). Kept as a plain column, not a FK —
    # sessions are purged after 7 days while activity is trimmed after 48h.
    session_id: Mapped[str | None] = mapped_column(String(36), index=True)
    path: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)


class EventLogRecord(Base):
    """Operational log of the realtime (SSE/LISTEN) machinery.

    Anything that perturbs event delivery — dropped events (slow consumer),
    LISTEN bridge disconnects, replay gaps — is persisted here so an admin
    can diagnose "live updates sometimes lag" from the App Settings page
    instead of guessing. Kept separate from the audit log, which tracks
    business actions, not plumbing.
    """

    __tablename__ = "event_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False)  # info | warning | error
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # sse | listen
    message: Mapped[str] = mapped_column(Text, nullable=False)


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, echo=False, pool_pre_ping=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """Request-scoped DB session that COMMITS on success.

    Without the explicit commit, every write flushed during a request (audit
    entries, session records, user updates…) was silently rolled back when the
    session closed — the API looked fine but nothing ever reached the database.
    """
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
