"""Security layer: password hashing (PBKDF2, same wire format as the frontend
template), JWT access/refresh tokens and request-scoped auth dependencies."""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionRecord, UserRecord, get_session, utcnow

# -- password hashing (pbkdf2_sha256$iterations$salt$hash) ------------------

_PBKDF2_ITERATIONS = 260_000
_SALT_BYTES = 16

# Dummy hash used to equalize verification time for unknown usernames.
_DUMMY_PASSWORD_HASH: str | None = None


def hash_password(password: str) -> str:
    salt = os.urandom(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, _PBKDF2_ITERATIONS)
    return f'pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}'


def token_hash(token: str) -> str:
    """Stable one-way hash of a token, for replay-detection anchors."""
    return hashlib.sha256(token.encode()).hexdigest()


# Random initial passwords (user creation / admin reset): unambiguous
# alphabet, shown once to the admin, change forced on first login.
_PASSWORD_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'


def generate_initial_password(length: int = 12) -> str:
    """Random per-account password — NEVER a shared constant: a known shared
    default let anyone take over a reset account before its first login."""
    import secrets  # noqa: PLC0415  stdlib, kept local like os.urandom usage
    return ''.join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, hash_hex = encoded.split('$')
        if algorithm != 'pbkdf2_sha256':
            return False
        digest = hashlib.pbkdf2_hmac(
            'sha256', password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        expected = bytes.fromhex(hash_hex)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


def burn_password_time(password: str) -> None:
    """Burn the same CPU time as a real verification (anti user enumeration)."""
    verify_password(password, _dummy_hash())


def _dummy_hash() -> str:
    global _DUMMY_PASSWORD_HASH
    if _DUMMY_PASSWORD_HASH is None:
        _DUMMY_PASSWORD_HASH = hash_password(os.urandom(16).hex())
    return _DUMMY_PASSWORD_HASH


# -- JWT ---------------------------------------------------------------------

def _create_token(user_id: int, session_id: str, kind: str, ttl_seconds: int) -> tuple[str, str, datetime]:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    payload = {
        "sub": str(user_id),
        "sid": session_id,
        "typ": kind,  # "access" or "refresh"
        "jti": uuid.uuid4().hex,
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    return token, payload["jti"], expires_at


def create_token_pair(user_id: int, session_id: str) -> tuple[str, str, int]:
    settings = get_settings()
    access, _, _ = _create_token(user_id, session_id, "access", settings.access_token_ttl_seconds)
    refresh, _, _ = _create_token(user_id, session_id, "refresh", settings.refresh_token_ttl_seconds)
    return access, refresh, settings.access_token_ttl_seconds


def decode_token(token: str, *, expected_kind: str = "access") -> dict:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    if payload.get("typ") != expected_kind:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")
    return payload


# -- FastAPI dependencies ------------------------------------------------------

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserRecord:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    payload = decode_token(credentials.credentials)
    # The access token alone is not enough: check that the session it belongs
    # to is still valid. Without this, a revoked session (logout or admin
    # kick from another tab) would keep working until the token expires.
    record = await session.get(SessionRecord, payload["sid"])
    if record is None or record.revoked_at is not None or record.expires_at <= utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session revoked or expired")
    user = await session.get(UserRecord, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Inactive or unknown user")
    return user


async def require_admin(user: Annotated[UserRecord, Depends(get_current_user)]) -> UserRecord:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user


CurrentUser = Annotated[UserRecord, Depends(get_current_user)]
AdminUser = Annotated[UserRecord, Depends(require_admin)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


async def get_session_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """JWT session id ('sid') — pair with CurrentUser on endpoints that need
    to attribute an action to a specific browser/client. Only decodes the
    token (no DB roundtrip); the auth check is CurrentUser's job."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return str(decode_token(credentials.credentials)["sid"])


SessionId = Annotated[str, Depends(get_session_id)]


def _is_trusted_proxy(host: str | None) -> bool:
    """True when the peer IP belongs to a configured trusted proxy range.

    X-Forwarded-For is CLIENT-CONTROLLED: an untrusted caller can spoof the
    header and rotate fake IPs to defeat the login rate limiter (which keys
    on this value). The header is therefore only honoured when the TCP peer
    itself comes from a trusted network (the frontend container / reverse
    proxy), and the actual peer IP is used otherwise.
    """
    if not host:
        return False
    import ipaddress
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in ipaddress.ip_network(cidr)
               for cidr in get_settings().trusted_proxies)


def client_ip(request) -> str:
    host = request.client.host if request.client else None
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded and _is_trusted_proxy(host):
        # Left-most entry = the original client as added by OUR proxy chain.
        return forwarded.split(',')[0].strip()
    return host or "unknown"
