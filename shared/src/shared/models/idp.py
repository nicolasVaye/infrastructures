"""Identity provider (OIDC/Keycloak) DTOs and admin management payloads."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from shared.enums import UserRole


class IdentityProviderBase(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    issuer_url: str = Field(pattern=r"^https?://", examples=["https://keycloak.example/realms/myrealm"])
    client_id: str = Field(min_length=1, max_length=128)
    auto_create_users: bool = True
    default_role: UserRole = UserRole.USER
    enabled: bool = True


class IdentityProviderCreate(IdentityProviderBase):
    client_secret: str = Field(min_length=1, max_length=255)


class IdentityProviderUpdate(BaseModel):
    """Partial update: only the provided fields are modified."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    issuer_url: str | None = Field(default=None, pattern=r"^https?://")
    client_id: str | None = Field(default=None, min_length=1, max_length=128)
    client_secret: str | None = Field(default=None, min_length=1, max_length=255)
    auto_create_users: bool | None = None
    default_role: UserRole | None = None
    enabled: bool | None = None


class IdentityProviderOut(BaseModel):
    """Admin view of a provider — never exposes the client secret."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    issuer_url: str
    client_id: str
    enabled: bool
    auto_create_users: bool
    default_role: UserRole
    created_at: datetime


class PublicProviderOut(BaseModel):
    """Login-page view: only what is needed to render a button."""

    id: int
    name: str


class OIDCAuthorizeOut(BaseModel):
    """Response of GET /auth/oidc/{idp_id}/authorize: open this URL."""

    authorize_url: str
    state: str


class OIDCCallbackIn(BaseModel):
    """Body of POST /auth/oidc/{idp_id}/callback."""

    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=2048)
