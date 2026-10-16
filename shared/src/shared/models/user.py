"""User, role and authentication DTOs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from shared.enums import UserRole


class RoleOut(BaseModel):
    id: int
    name: UserRole
    description: str | None = None
    user_count: int = 0


class UserOut(BaseModel):
    """Public representation of a user (never exposes password hashes)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: UserRole
    auth_provider: str = "local"
    # Name of the identity provider for federated accounts (None for local).
    idp_name: str | None = None
    is_active: bool
    must_change_password: bool
    email: str | None = None
    display_name: str | None = None
    # The avatar image itself is NEVER serialized here: a base64 data URL can
    # weigh megabytes and used to ride in EVERY /users, /auth/me and /sessions
    # response. Consumers fetch it on demand from GET /users/{id}/avatar and
    # use avatar_version for cache busting.
    has_avatar: bool = False
    avatar_version: int = 0
    language: str = "en"
    theme: str = "light"
    created_at: datetime


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str | None = None
    role: UserRole = UserRole.USER
    email: str | None = Field(default=None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    display_name: str | None = None
    must_change_password: bool = True


class UserCreatedOut(UserOut):
    """Creation response: carries the one-time generated initial password.

    When the caller does not provide a password, the backend generates a
    RANDOM one (never a shared constant) and returns it exactly once here —
    the admin relays it to the user, who must change it at first login.
    """
    initial_password: str | None = None


class UserUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
    email: str | None = Field(default=None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    display_name: str | None = None


class ProfileUpdate(BaseModel):
    # No Pydantic pattern on email: an explicitly sent empty string means
    # "clear the field" (see the endpoint's model_fields_set logic) and the
    # format itself is validated in the endpoint.
    email: str | None = None
    display_name: str | None = None
    avatar: str | None = None
    language: str | None = None
    theme: str | None = None


class PasswordChange(BaseModel):
    new_password: str = Field(min_length=10, max_length=64)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenPair(BaseModel):
    """JWT pair returned by POST /auth/login."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # access token TTL in seconds
    # Session record the tokens are bound to — the frontend keeps it to
    # recognise 'session_revoked' events targeting THIS connection.
    session_id: str | None = None


class Heartbeat(BaseModel):
    """Periodic signal sent by clients so the backend knows who is connected."""

    client: str = "web"  # free label: web, automation, cli, ...
