"""OIDC (OpenID Connect) helper layer for external identity providers.

Implements just enough of the OIDC authorization-code flow to federate
logins from providers like Keycloak:

    1. discover the provider endpoints (``/.well-known/openid-configuration``)
    2. build the authorization URL (with a signed ``state`` anti-CSRF token)
    3. exchange the authorization code for tokens (token endpoint)
    4. verify the ID token against the provider JWKS

Only ``httpx`` and ``pyjwt`` are used — no extra dependency. Discovery
documents and JWKS are cached per issuer for ``_CACHE_TTL_SECONDS``.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
import jwt
from fastapi import HTTPException, status
from jwt import PyJWK

from app.core.config import get_settings

_CACHE_TTL_SECONDS = 3600
_discovery_cache: dict[str, tuple[float, dict]] = {}
_jwks_cache: dict[str, tuple[float, list[dict]]] = {}


def _fresh(entry: tuple[float, Any] | None) -> Any | None:
    if entry is None or (time.monotonic() - entry[0]) > _CACHE_TTL_SECONDS:
        return None
    return entry[1]


async def discover(issuer_url: str) -> dict:
    """Fetch (and cache) the provider's OpenID configuration."""
    cached = _fresh(_discovery_cache.get(issuer_url))
    if cached is not None:
        return cached
    well_known = issuer_url.rstrip("/") + "/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(well_known)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Identity provider unreachable: {exc}",
        ) from exc
    if response.status_code != 200:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Discovery document not found at {well_known} (HTTP {response.status_code})",
        )
    document = response.json()
    _discovery_cache[issuer_url] = (time.monotonic(), document)
    return document


async def jwks(issuer_url: str) -> list[dict]:
    """Fetch (and cache) the provider's JWKS key set."""
    cached = _fresh(_jwks_cache.get(issuer_url))
    if cached is not None:
        return cached
    document = await discover(issuer_url)
    jwks_uri = document.get("jwks_uri")
    if not jwks_uri:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Provider discovery has no jwks_uri")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(jwks_uri)
    if response.status_code != 200:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"JWKS fetch failed (HTTP {response.status_code})")
    keys = response.json().get("keys", [])
    _jwks_cache[issuer_url] = (time.monotonic(), keys)
    return keys


def build_authorize_url(
    document: dict, client_id: str, redirect_uri: str, state: str,
) -> str:
    endpoint = document.get("authorization_endpoint")
    if not endpoint:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Provider has no authorization_endpoint")
    params = {
        "response_type": "code",
        "scope": "openid profile email",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    # Keycloak accepts plain HTTP dev setups; production should use PKCE +
    # confidential clients. The client secret stays server-side (token exchange).
    return f"{endpoint}?{httpx.QueryParams(params)}"


async def exchange_code(
    document: dict, *, code: str, client_id: str, client_secret: str, redirect_uri: str,
) -> dict:
    """Exchange the authorization code for tokens at the token endpoint."""
    endpoint = document.get("token_endpoint")
    if not endpoint:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Provider has no token_endpoint")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Accept": "application/json"},
        )
    if response.status_code != 200:
        detail = ""
        try:
            detail = response.json().get("error_description", response.json().get("error", ""))
        except Exception:  # noqa: BLE001
            detail = response.text[:200]
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, f"OIDC code exchange failed: {detail or response.status_code}"
        )
    return response.json()


async def verify_id_token(idp, id_token: str) -> dict:
    """Verify the provider-signed ID token and return its claims.

    Validates signature (JWKS), issuer and audience, and expiry/issued-at.
    """
    keys = await jwks(idp.issuer_url)
    claims: dict | None = None
    last_error: Exception | None = None
    for key_dict in keys:
        try:
            jwk = PyJWK.from_dict(key_dict)
            claims = jwt.decode(
                id_token,
                key=jwk.key,
                algorithms=["RS256", "RS384", "RS512", "ES256"],
                audience=idp.client_id,
                issuer=idp.issuer_url.rstrip("/"),
                options={"require": ["exp", "iat", "sub"]},
            )
            break
        except jwt.PyJWTError as exc:  # try the next key (kid rotation)
            last_error = exc
    if claims is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, f"Invalid OIDC ID token: {last_error or 'no JWKS key matched'}"
        )
    return claims


# -- signed ``state`` (anti-CSRF) ---------------------------------------------

def sign_state(idp_id: int) -> str:
    settings = get_settings()
    payload = {
        "typ": "oidc_state",
        "idp": idp_id,
        "nonce": uuid.uuid4().hex,
        "exp": int(time.time()) + settings.oidc_state_ttl_seconds,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_state(state: str, idp_id: int) -> None:
    settings = get_settings()
    try:
        payload = jwt.decode(state, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired OIDC state") from exc
    if payload.get("typ") != "oidc_state" or payload.get("idp") != idp_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "OIDC state does not match this provider")


def redirect_uri() -> str:
    return get_settings().oidc_redirect_base_url.rstrip("/") + "/auth/oidc/callback"
