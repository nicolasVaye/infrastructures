"""Enumerations shared by the backend, the frontend and external clients."""

from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    """Role-based access control levels (values are stable API identifiers)."""

    ADMIN = "admin"
    OPERATOR = "operator"
    USER = "user"


class AuthProvider(str, enum.Enum):
    """Where a user's credentials come from."""

    LOCAL = "local"  # username + password stored locally
    OIDC = "oidc"    # external identity provider (Keycloak, etc.)


class AuditAction(str, enum.Enum):
    """Stable identifiers for actions recorded in the audit trail."""

    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    OIDC_LOGIN = "oidc_login"
    IDP_CREATED = "idp_created"
    IDP_UPDATED = "idp_updated"
    IDP_DELETED = "idp_deleted"
    LOGOUT = "logout"
    PASSWORD_CHANGED = "password_changed"
    PASSWORD_RESET = "password_reset"
    USER_CREATED = "user_created"
    USER_DELETED = "user_deleted"
    ROLE_CHANGED = "role_changed"
    USER_ACTIVATED = "user_activated"
    USER_DEACTIVATED = "user_deactivated"
    PROFILE_UPDATED = "profile_updated"
    LANGUAGE_CHANGED = "language_changed"
    THEME_CHANGED = "theme_changed"
    SESSION_REVOKED = "session_revoked"
    JOB_SUBMITTED = "job_submitted"
    JOB_CANCELLED = "job_cancelled"


class JobStatus(str, enum.Enum):
    """Lifecycle of an asynchronous job executed by the workers."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SessionStatus(str, enum.Enum):
    """Lifecycle of a user session tracked by the backend."""

    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
