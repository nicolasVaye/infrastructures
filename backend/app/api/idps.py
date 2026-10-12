"""Identity provider management (admin): configure external OIDC sources.

These endpoints back the frontend 'Providers' page: an admin can add a
Keycloak realm (or any OIDC IdP), toggle it, change the default role for
auto-provisioned users, and verify the endpoints are reachable.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core import oidc
from app.core.db import IdentityProviderRecord, UserRecord
from app.core.security import AdminUser, DbSession
from app.services import record
from shared.enums import AuditAction
from shared.models import (IdentityProviderCreate, IdentityProviderOut,
                           IdentityProviderUpdate)

router = APIRouter(prefix="/idps", tags=["identity providers"])


async def _get_idp(session, idp_id: int) -> IdentityProviderRecord:
    idp = await session.get(IdentityProviderRecord, idp_id)
    if idp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Identity provider not found")
    return idp


@router.get("", response_model=list[IdentityProviderOut])
async def list_idps(admin: AdminUser, session: DbSession) -> list[IdentityProviderOut]:
    idps = (await session.scalars(
        select(IdentityProviderRecord).order_by(IdentityProviderRecord.id)
    )).all()
    return [IdentityProviderOut.model_validate(i) for i in idps]


@router.post("", response_model=IdentityProviderOut, status_code=201)
async def create_idp(body: IdentityProviderCreate, admin: AdminUser,
                     session: DbSession) -> IdentityProviderOut:
    existing = (await session.scalars(
        select(IdentityProviderRecord).where(IdentityProviderRecord.name == body.name)
    )).first()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Provider '{body.name}' already exists")
    idp = IdentityProviderRecord(
        name=body.name.strip(),
        issuer_url=body.issuer_url.strip().rstrip("/"),
        client_id=body.client_id.strip(),
        client_secret=body.client_secret,
        enabled=body.enabled,
        auto_create_users=body.auto_create_users,
        default_role=body.default_role.value,
    )
    session.add(idp)
    await session.flush()
    await record(session, AuditAction.IDP_CREATED, user_id=admin.id,
                 username=admin.username, target=idp.name)
    return IdentityProviderOut.model_validate(idp)


@router.patch("/{idp_id}", response_model=IdentityProviderOut)
async def update_idp(idp_id: int, body: IdentityProviderUpdate, admin: AdminUser,
                     session: DbSession) -> IdentityProviderOut:
    idp = await _get_idp(session, idp_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        idp.name = data.pop("name").strip()
    if "issuer_url" in data and data["issuer_url"]:
        idp.issuer_url = data.pop("issuer_url").strip().rstrip("/")
    if "client_id" in data and data["client_id"]:
        idp.client_id = data.pop("client_id").strip()
    if "client_secret" in data and data["client_secret"]:
        idp.client_secret = data.pop("client_secret")
    if "auto_create_users" in data:
        idp.auto_create_users = data.pop("auto_create_users")
    if "enabled" in data:
        idp.enabled = data.pop("enabled")
    if "default_role" in data and data["default_role"] is not None:
        idp.default_role = data.pop("default_role")  # model_dump gives the value string
    await session.flush()
    await record(session, AuditAction.IDP_UPDATED, user_id=admin.id,
                 username=admin.username, target=idp.name)
    return IdentityProviderOut.model_validate(idp)


@router.delete("/{idp_id}", status_code=204)
async def delete_idp(idp_id: int, admin: AdminUser, session: DbSession) -> None:
    idp = await _get_idp(session, idp_id)
    federated = (await session.scalars(
        select(UserRecord).where(UserRecord.idp_id == idp.id)
    )).all()
    if federated:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{len(federated)} user(s) still federated through this provider — "
            "deactivate or reassign them first.",
        )
    await record(session, AuditAction.IDP_DELETED, user_id=admin.id,
                 username=admin.username, target=idp.name)
    await session.delete(idp)


@router.get("/{idp_id}/verify")
async def verify_idp(idp_id: int, admin: AdminUser, session: DbSession) -> dict:
    """Reach out to the provider's discovery document and report the outcome."""
    idp = await _get_idp(session, idp_id)
    document = await oidc.discover(idp.issuer_url)
    await oidc.jwks(idp.issuer_url)
    return {
        "ok": True,
        "issuer": document.get("issuer"),
        "authorization_endpoint": document.get("authorization_endpoint"),
        "token_endpoint": document.get("token_endpoint"),
    }
