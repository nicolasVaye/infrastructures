"""Authentication endpoints: login, refresh, logout, me, heartbeat.

This is the single source of truth for authentication — the NiceGUI frontend
authenticates here exactly like any external automation client would.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func, or_, select

from app.core.config import get_settings
from app.core.db import (AuditLogRecord, IdentityProviderRecord, RoleRecord,
                         SessionRecord, UserRecord, as_utc, utcnow)
from app.core.security import (_bearer, CurrentUser, DbSession,
                               burn_password_time, client_ip,
                               create_token_pair, decode_token,
                               token_hash, verify_password)
from app.events import notify_event
from app.services import (create_session_record, record, revoke_session)
from shared.enums import AuditAction, AuthProvider, UserRole
from shared.models import (Heartbeat, LoginRequest, OIDCAuthorizeOut,
                           OIDCCallbackIn, PublicProviderOut, TokenPair,
                           UserOut)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# Brute-force protection, ENFORCED HERE (the frontend's in-memory limiter is
# trivially bypassed by calling the API directly). Backed by the audit table
# so the limit is shared across every backend replica and survives
# restarts; LOGIN_FAILED entries are committed before the 401 is raised.
_LOGIN_WINDOW_SECONDS = 900   # 15 min sliding window
_LOGIN_MAX_FAILURES = 10       # per IP OR per username, then locked out


async def _recent_login_failures(session, *, ip: str, username: str) -> int:
    """Failed logins from this IP or for this username within the window."""
    cutoff = utcnow() - timedelta(seconds=_LOGIN_WINDOW_SECONDS)
    return (await session.execute(
        select(func.count()).select_from(AuditLogRecord).where(
            AuditLogRecord.action == AuditAction.LOGIN_FAILED.value,
            AuditLogRecord.created_at >= cutoff,
            or_(AuditLogRecord.ip == ip,
                AuditLogRecord.username == username),
        )
    )).scalar_one()


def _user_agent(request: Request) -> str | None:
    """Real browser UA when the frontend forwards it (X-User-Agent), else the
    caller's own User-Agent. Without the forwarded header every session would
    record the frontend's httpx UA ('python-httpx/…') instead of the browser."""
    return request.headers.get("X-User-Agent") or request.headers.get("User-Agent")

_INACTIVE_MESSAGE = "Account disabled"


def _user_out(user: UserRecord) -> UserOut:
    return UserOut(
        id=user.id, username=user.username, role=user.role,
        auth_provider=user.auth_provider,
        idp_name=user.idp_ref.name if user.idp_ref else None,
        is_active=user.is_active, must_change_password=user.must_change_password,
        email=user.email, display_name=user.display_name,
        has_avatar=bool(user.avatar),
        avatar_version=user.avatar_version or 0,
        language=user.language,
        theme=user.theme or "light", created_at=user.created_at,
    )


@router.post("/login", response_model=TokenPair)
async def login(body: LoginRequest, request: Request, session: DbSession) -> TokenPair:
    """Authenticate any client (frontend or automation) and return a JWT pair."""
    username = body.username.strip()

    # Brute-force guard BEFORE any password work: a locked-out caller gets
    # the same CPU burn as a wrong password, so timing never leaks whether
    # the username exists or the account is locked.
    ip = client_ip(request)
    if await _recent_login_failures(session, ip=ip, username=username) \
            >= _LOGIN_MAX_FAILURES:
        burn_password_time(body.password)
        logger.warning("Login refused (rate limited): username=%r ip=%s",
                       username, ip)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Too many failed attempts. Try again later.")

    user = (await session.scalars(
        select(UserRecord).where(UserRecord.username == username)
    )).first()

    if user is None or user.auth_provider != AuthProvider.LOCAL.value:
        # Unknown user or federated (OIDC) account: burn the same CPU time so
        # the response delay never reveals whether the username exists.
        burn_password_time(body.password)
        await record(session, AuditAction.LOGIN_FAILED, username=username, ip=ip)
        # Commit the failure BEFORE raising: the session dependency rolls
        # back on the HTTPException — an unrecorded failure is invisible to
        # both the audit trail and the brute-force guard above (observed:
        # zero login_failed rows despite real failed attempts).
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    if not verify_password(body.password, user.password_hash):
        await record(session, AuditAction.LOGIN_FAILED, user_id=user.id,
                     username=user.username, ip=ip)
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    if not user.is_active:
        await record(session, AuditAction.LOGIN_FAILED, user_id=user.id,
                     username=user.username, details=_INACTIVE_MESSAGE, ip=ip)
        await session.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, _INACTIVE_MESSAGE)

    client_label = request.headers.get("X-Client-Label", "web")[:32]
    session_record = await create_session_record(
        session, user,
        client=client_label,
        ip=ip,
        user_agent=_user_agent(request),
    )
    access, refresh, ttl = create_token_pair(user.id, session_record.id)
    # Refresh-token rotation anchor: only the LATEST refresh token issued
    # for this session stays valid (see /auth/refresh).
    session_record.refresh_token_hash = token_hash(refresh)
    await record(session, AuditAction.LOGIN, user_id=user.id,
                 username=user.username, ip=ip)
    # Live sessions list: a login changes who is connected — push it so the
    # Sessions tab refreshes instantly (SSE) instead of on its slow poll.
    await notify_event(session, "sessions_changed")

    # Commit BEFORE returning: the dependency teardown commits only after
    # the response is on the wire, and the client calls /auth/me (or the
    # heartbeat) immediately with the fresh token. Without this commit the
    # session record is not visible yet and get_current_user rejects the
    # brand-new session with 401.
    await session.commit()

    return TokenPair(access_token=access, refresh_token=refresh, expires_in=ttl)


# -- OIDC (external identity providers, e.g. Keycloak) -----------------------

@router.get("/providers", response_model=list[PublicProviderOut])
async def providers(session: DbSession) -> list[PublicProviderOut]:
    """Public: enabled OIDC providers, rendered as buttons on the login page."""
    from sqlalchemy import select as _select
    idps = (await session.scalars(
        _select(IdentityProviderRecord).where(IdentityProviderRecord.enabled.is_(True))
    )).all()
    return [PublicProviderOut(id=i.id, name=i.name) for i in idps]


@router.get("/oidc/{idp_id}/authorize", response_model=OIDCAuthorizeOut)
async def oidc_authorize(idp_id: int, session: DbSession) -> OIDCAuthorizeOut:
    """Start the OIDC authorization-code flow for the given provider.

    Public (the browser is not authenticated yet). Returns the provider's
    authorization URL plus a signed anti-CSRF state; the caller opens the URL,
    the IdP redirects back to the frontend ``/auth/oidc/callback`` page.
    """
    from app.core import oidc
    idp = await session.get(IdentityProviderRecord, idp_id)
    if idp is None or not idp.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Identity provider not found or disabled")
    document = await oidc.discover(idp.issuer_url)
    state = oidc.sign_state(idp.id)
    url = oidc.build_authorize_url(document, idp.client_id, oidc.redirect_uri(idp.id), state)
    return OIDCAuthorizeOut(authorize_url=url, state=state)


@router.post("/oidc/{idp_id}/callback", response_model=TokenPair)
async def oidc_callback(idp_id: int, body: OIDCCallbackIn, request: Request,
                        session: DbSession) -> TokenPair:
    """Finish the OIDC flow: exchange the code, verify the ID token, log in.

    Public endpoint called by the frontend callback page. Returns the same
    TokenPair as a local login — everything downstream (sessions, heartbeat,
    kick, roles, audit) is identical for federated and local users.
    """
    from app.core import oidc
    idp = await session.get(IdentityProviderRecord, idp_id)
    if idp is None or not idp.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Identity provider not found or disabled")
    oidc.verify_state(body.state, idp.id)

    document = await oidc.discover(idp.issuer_url)
    tokens = await oidc.exchange_code(
        document, code=body.code, client_id=idp.client_id,
        client_secret=idp.client_secret, redirect_uri=oidc.redirect_uri(idp.id),
    )
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Provider returned no id_token")
    claims = await oidc.verify_id_token(idp, id_token)

    subject = str(claims["sub"])
    user = (await session.scalars(
        select(UserRecord).where(
            UserRecord.idp_id == idp.id, UserRecord.external_subject == subject
        )
    )).first()

    if user is None:
        # Optional claim-based identity: preferred_username, else email prefix.
        preferred = claims.get("preferred_username") or claims.get("email", "").split("@")[0]
        username = (preferred or f"oidc-{subject[:16]}")[:64]
        # Avoid collisions with an existing local username.
        if (await session.scalars(
            select(UserRecord).where(UserRecord.username == username)
        )).first() is not None:
            username = f"{username}.{subject[:8]}"[:64]

        if idp.auto_create_users:
            role = (await session.scalars(
                select(RoleRecord).where(RoleRecord.name == idp.default_role)
            )).first()
            if role is None:
                role = (await session.scalars(
                    select(RoleRecord).where(RoleRecord.name == UserRole.USER.value)
                )).first()
            user = UserRecord(
                username=username,
                password_hash=None,  # federated account: no local password
                role_id=role.id,
                is_active=True,
                must_change_password=False,
                email=claims.get("email"),
                display_name=claims.get("name"),
                auth_provider=AuthProvider.OIDC.value,
                external_subject=subject,
                idp_id=idp.id,
            )
            session.add(user)
            await session.flush()
        else:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Account provisioning is disabled for this provider — ask an administrator.",
            )

    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _INACTIVE_MESSAGE)

    # A federated account has no local password: the flag can only be a legacy
    # leftover (rows created before the OIDC path set it to False). Clear it
    # on every federated login so the forced change-password page — which
    # would be a dead end for these accounts — never triggers.
    if user.must_change_password:
        user.must_change_password = False

    client_label = request.headers.get("X-Client-Label", "oidc")[:32]
    session_record = await create_session_record(
        session, user,
        client=client_label,
        ip=client_ip(request),
        user_agent=_user_agent(request),
    )
    access, refresh, ttl = create_token_pair(user.id, session_record.id)
    # Refresh-token rotation anchor (same as /auth/login).
    session_record.refresh_token_hash = token_hash(refresh)
    await record(session, AuditAction.OIDC_LOGIN, user_id=user.id,
                 username=user.username, target=idp.name, ip=client_ip(request))
    await notify_event(session, "sessions_changed")
    # Same commit-before-return as /auth/login: the callback page fires a
    # heartbeat with the fresh token immediately after this response.
    await session.commit()
    return TokenPair(access_token=access, refresh_token=refresh, expires_in=ttl,
                     session_id=session_record.id)


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: dict, session: DbSession) -> TokenPair:
    """Exchange a valid refresh token for a fresh JWT pair (ROTATING).

    Only the LATEST refresh token issued for the session is accepted: each
    refresh stores the hash of the new token on the session record. A
    presented token that does not match is a REPLAY of an already-used
    (possibly stolen) token — the whole session is revoked immediately:
    an attacker who copied the old token cannot use it, and the legitimate
    user re-authenticates instead of silently racing the thief.
    """
    token = (body or {}).get("refresh_token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh_token required")
    payload = decode_token(token, expected_kind="refresh")
    sid = payload["sid"]

    record_ = await session.get(SessionRecord, sid)
    if (record_ is None or record_.revoked_at is not None
            or as_utc(record_.expires_at) <= utcnow()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session revoked or expired")

    presented_hash = token_hash(token)
    if record_.refresh_token_hash and presented_hash != record_.refresh_token_hash:
        # Replay of an already-rotated refresh token: treat the session as
        # compromised and kill it everywhere (SSE session_revoked kicks the
        # open tabs of that user).
        record_.revoked_at = utcnow()
        await record(session, AuditAction.REFRESH_REUSED, user_id=record_.user_id,
                     details=f"session {sid[:8]}")
        await notify_event(session, "session_revoked", session_id=sid)
        await notify_event(session, "sessions_changed")
        await session.commit()
        logger.warning("Refresh token replay detected — session %s revoked", sid[:8])
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Session revoked (token replay)")

    record_.last_activity = utcnow()

    access, refresh_new, ttl = create_token_pair(int(payload["sub"]), sid)
    record_.refresh_token_hash = token_hash(refresh_new)
    return TokenPair(access_token=access, refresh_token=refresh_new, expires_in=ttl,
                     session_id=sid)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return _user_out(user)


@router.put("/heartbeat")
async def heartbeat(
    body: Heartbeat,
    user: CurrentUser,
    session: DbSession,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Periodic signal: keeps the caller's session marked as 'connected'.

    The backend considers a session connected while its last heartbeat is more
    recent than settings.heartbeat_ttl_seconds.

    The response also carries a small profile digest (avatar version,
    display name). Each frontend compares it with its local snapshot and
    live-reloads the avatar/name when they differ — this is how a change
    made in one BROWSER propagates to the same user's other browsers
    (cookies are per-browser and cannot carry that).
    """
    payload = decode_token(credentials.credentials)
    record_ = await session.get(SessionRecord, payload["sid"])
    if record_ is not None and record_.revoked_at is None:
        record_.last_activity = utcnow()
        record_.client = body.client[:32]
    return {
        "status": "ok",
        "session_id": payload["sid"],
        "has_avatar": bool(user.avatar),
        "avatar_version": user.avatar_version or 0,
        "display_name": user.display_name,
    }


@router.post("/logout")
async def logout(
    request: Request,
    user: CurrentUser,
    session: DbSession,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Revoke the session bound to the presented access token."""
    payload = decode_token(credentials.credentials)
    revoked = await revoke_session(session, payload["sid"])
    await notify_event(session, "session_revoked", session_id=payload["sid"])
    await notify_event(session, "sessions_changed")
    await record(session, AuditAction.LOGOUT, user_id=user.id,
                 username=user.username, ip=client_ip(request))
    return {"status": "logged out", "session_revoked": revoked}
