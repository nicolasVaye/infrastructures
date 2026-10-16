"""User and role management endpoints (admin), plus self-profile endpoints."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, func, select

from app.core.db import RoleRecord, SessionRecord, UserRecord, utcnow
from app.core.security import (AdminUser, CurrentUser, DbSession,
                               generate_initial_password, hash_password)
from app.events import notify_event
from app.services import record, revoke_session
from shared.enums import AuditAction
from shared.models import (PasswordChange, ProfileUpdate, RoleOut, UserCreate,
                           UserCreatedOut, UserOut, UserUpdate)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

router = APIRouter(tags=["users"])

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 64
_PROTECTED_USERNAME = "admin"


def _validate_password(password: str) -> None:
    import string
    problems = []
    if not (MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH):
        problems.append(f"{MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters")
    if not any(c.isupper() for c in password):
        problems.append("one uppercase letter")
    if not any(c.islower() for c in password):
        problems.append("one lowercase letter")
    if not any(c.isdigit() for c in password):
        problems.append("one number")
    if not any(c in string.punctuation for c in password):
        problems.append("one special character")
    if problems:
        raise HTTPException(400, "Password requirements not met: " + ", ".join(problems) + ".")


def _out(user: UserRecord) -> UserOut:
    return UserOut(
        id=user.id, username=user.username, role=user.role,
        auth_provider=user.auth_provider,
        idp_name=user.idp_ref.name if user.idp_ref else None,
        is_active=user.is_active, must_change_password=user.must_change_password,
        email=user.email, display_name=user.display_name, avatar=user.avatar,
        language=user.language,
        theme=user.theme or "light", created_at=user.created_at,
    )


async def _get_role(session, name: str) -> RoleRecord:
    role = (await session.scalars(select(RoleRecord).where(RoleRecord.name == name))).first()
    if role is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown role '{name}'")
    return role


async def _admin_count(session) -> int:
    admin_role = await _get_role(session, "admin")
    return await session.scalar(
        select(func.count()).select_from(UserRecord).where(
            UserRecord.role_id == admin_role.id, UserRecord.is_active.is_(True)
        )
    ) or 0


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(user: CurrentUser, session: DbSession) -> list[RoleOut]:
    """Catalog of roles with description and user counts (Users > Roles tab)."""
    from sqlalchemy import func
    counts = dict((await session.execute(
        select(UserRecord.role_id, func.count())
        .where(UserRecord.is_active.is_(True)).group_by(UserRecord.role_id)
    )).all())
    roles = (await session.scalars(select(RoleRecord).order_by(RoleRecord.id))).all()
    return [RoleOut(id=r.id, name=r.name, description=r.description,
                    user_count=counts.get(r.id, 0)) for r in roles]


@router.get("/users", response_model=list[UserOut])
async def list_users(admin: AdminUser, session: DbSession) -> list[UserOut]:
    users = (await session.scalars(
        select(UserRecord).order_by(func.lower(UserRecord.username))
    )).all()
    return [_out(u) for u in users]


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: int, admin: AdminUser, session: DbSession) -> UserOut:
    user = await session.get(UserRecord, user_id)
    if user is None:
        raise HTTPException(404, "User not found.")
    return _out(user)


@router.post("/users", response_model=UserCreatedOut, status_code=201)
async def create_user(body: UserCreate, admin: AdminUser, session: DbSession) -> UserCreatedOut:
    username = body.username.strip()
    if not username:
        raise HTTPException(400, "Username is required.")
    existing = (await session.scalars(
        select(UserRecord).where(UserRecord.username == username)
    )).first()
    if existing:
        raise HTTPException(409, f'User "{username}" already exists.')

    role = await _get_role(session, body.role.value)
    # No caller-provided password → generate a RANDOM one. A shared default
    # ("changeme") let anyone take over fresh accounts before first login.
    generated = None
    if body.password:
        _validate_password(body.password)  # same policy as /me/password
        password = body.password
    else:
        generated = generate_initial_password()
        password = generated
    user = UserRecord(
        username=username,
        password_hash=hash_password(password),
        role_id=role.id,
        is_active=True,
        must_change_password=body.must_change_password,
        email=body.email,
        display_name=body.display_name,
    )
    session.add(user)
    await session.flush()
    await record(session, AuditAction.USER_CREATED, user_id=admin.id,
                 username=admin.username, target=username)
    # Commit BEFORE returning (see reset_password): the caller may try the
    # generated initial_password immediately.
    await session.commit()
    out = UserCreatedOut.model_validate(_out(user))
    out.initial_password = generated
    return out


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: int, body: UserUpdate, admin: AdminUser, session: DbSession) -> UserOut:
    user = await session.get(UserRecord, user_id)
    if user is None:
        raise HTTPException(404, "User not found.")

    if body.role is not None:
        target_role = body.role.value
        if user.username == _PROTECTED_USERNAME and target_role != "admin":
            raise HTTPException(400, "The default admin must remain an admin.")
        if user.role == "admin" and target_role != "admin" and await _admin_count(session) <= 1:
            raise HTTPException(400, "Cannot demote the last remaining admin.")
        user.role_id = (await _get_role(session, target_role)).id
        await record(session, AuditAction.ROLE_CHANGED, user_id=admin.id,
                     username=admin.username, target=user.username, details=target_role)

    if body.is_active is not None:
        if user.username == _PROTECTED_USERNAME and not body.is_active:
            raise HTTPException(400, "The default admin cannot be deactivated.")
        if user.role == "admin" and not body.is_active and await _admin_count(session) <= 1:
            raise HTTPException(400, "Cannot deactivate the last active admin.")
        user.is_active = body.is_active
        if not body.is_active:
            # kick all sessions of the deactivated user
            for s in (await session.scalars(
                select(SessionRecord).where(
                    SessionRecord.user_id == user.id, SessionRecord.revoked_at.is_(None)
                )
            )).all():
                s.revoked_at = s.revoked_at or utcnow()
        await record(
            session,
            AuditAction.USER_ACTIVATED if body.is_active else AuditAction.USER_DEACTIVATED,
            user_id=admin.id, username=admin.username, target=user.username,
        )

    if body.email is not None:
        user.email = body.email
    if body.display_name is not None:
        user.display_name = body.display_name
    await session.flush()
    await notify_event(session, "user_updated", user_id=user.id,
                      has_avatar=bool(user.avatar),
                      avatar_version=user.avatar_version or 0,
                      display_name=user.display_name)
    return _out(user)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: int, admin: AdminUser, session: DbSession) -> None:
    user = await session.get(UserRecord, user_id)
    if user is None:
        raise HTTPException(404, "User not found.")
    if user.username == _PROTECTED_USERNAME:
        raise HTTPException(400, "The default admin cannot be deleted.")
    # Revoke the user's sessions BEFORE deleting the row: SQLAlchemy cascades
    # the delete (sessions.user_id has no ON DELETE SET NULL, it would fail
    # the NOT NULL constraint), and a revocation update on a deleted-parent
    # row is emitted as user_id=NULL. Deleting the sessions outright is the
    # correct move — they die with the account (the audit log keeps the
    # history).
    await session.execute(
        delete(SessionRecord).where(SessionRecord.user_id == user.id)
    )
    await session.delete(user)
    await record(session, AuditAction.USER_DELETED, user_id=admin.id,
                 username=admin.username, target=user.username)


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: int, admin: AdminUser, session: DbSession) -> dict:
    """Reset a user's password to a RANDOM value (change forced on next login).

    The generated password is returned exactly once, for the admin to relay —
    never a shared constant: a known default password meant anyone could
    log into a reset account before its legitimate owner did.
    """
    user = await session.get(UserRecord, user_id)
    if user is None:
        raise HTTPException(404, "User not found.")
    if user.auth_provider != "local":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"User '{user.username}' is federated — their password is managed "
            "by their identity provider.",
        )
    new_password = generate_initial_password()
    user.password_hash = hash_password(new_password)
    user.must_change_password = True
    await record(session, AuditAction.PASSWORD_RESET, user_id=admin.id,
                 username=admin.username, target=user.username)
    # Commit BEFORE returning: the dependency teardown commits only after
    # the response is on the wire, and the client (or the admin) will try
    # the new password immediately — without this the first login races
    # the commit and fails (same class of bug as /auth/login).
    await session.commit()
    return {"password": new_password}


# -- self-service (any authenticated user) -------------------------------------

@router.patch("/me/profile", response_model=UserOut)
async def update_profile(body: ProfileUpdate, user: CurrentUser, session: DbSession) -> UserOut:
    """Self-service profile update.

    Uses ``model_fields_set`` so that an explicitly provided ``null``/empty
    value CLEARS the field, while an absent field is left untouched. The
    previous "ignore None" logic made it impossible to remove an avatar,
    email or display name.
    """
    provided = body.model_fields_set
    if "email" in provided:
        email = (body.email or "").strip()
        if email and not _EMAIL_RE.match(email):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid email address.")
        user.email = email or None
    if "display_name" in provided:
        user.display_name = (body.display_name or "").strip() or None
    if "avatar" in provided:
        user.avatar = body.avatar or None
        # Bump the version so heartbeats tell every browser/tab of this user
        # that the image changed and must be reloaded from GET /avatar.
        user.avatar_version = (user.avatar_version or 0) + 1
    if "language" in provided and body.language:
        user.language = body.language
        await record(session, AuditAction.LANGUAGE_CHANGED, user_id=user.id,
                     username=user.username, details=body.language)
    if "theme" in provided and body.theme in ("light", "dark"):
        user.theme = body.theme
        await record(session, AuditAction.THEME_CHANGED, user_id=user.id,
                     username=user.username, details=body.theme)
    await session.flush()
    await notify_event(session, "user_updated", user_id=user.id,
                      has_avatar=bool(user.avatar),
                      avatar_version=user.avatar_version or 0,
                      display_name=user.display_name)
    return _out(user)


@router.put("/me/password", status_code=204)
async def change_password(body: PasswordChange, user: CurrentUser, session: DbSession) -> None:
    if user.auth_provider != "local":
        # Federated account: the password lives in the IdP (Keycloak...),
        # a local one would never be used and would only confuse the user.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This account is managed by an external identity provider — "
            "change the password there.",
        )
    _validate_password(body.new_password)
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    await record(session, AuditAction.PASSWORD_CHANGED, user_id=user.id, username=user.username)
    # Commit BEFORE returning (see reset_password): a fast client that
    # logs in with the new password immediately must not race the commit.
    await session.commit()
