"""Async helpers for the NiceGUI frontend: login, logout, heartbeat.

NiceGUI pages are async, so these use httpx.AsyncClient directly. The rest of
the template's views use the synchronous facade (``core.database.get_session``),
which is fine for quick CRUD calls.
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx
from nicegui import app, ui

logger = logging.getLogger(__name__)

BACKEND_URL = os.environ.get('BACKEND_URL', 'http://localhost:8000')


class AuthenticationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def login(username: str, password: str, *, client_ip: str | None = None,
                user_agent: str | None = None) -> dict:
    """Authenticate against the backend and store JWTs in the session storage.

    Returns the ``/auth/me`` payload (user info). Raises AuthenticationError
    with a user-facing message on failure.
    """
    async with httpx.AsyncClient(base_url=BACKEND_URL, timeout=10.0) as client:
        response = await client.post(
            '/auth/login',
            json={'username': username, 'password': password},
            headers={'X-Client-Label': 'web',
                     **({'X-User-Agent': user_agent} if user_agent else {})},
        )
        if response.status_code in (401, 403):
            detail = response.json().get('detail', 'Invalid credentials')
            raise AuthenticationError(str(detail))
        if response.status_code != 200:
            raise AuthenticationError('Authentication service unavailable.')
        tokens = response.json()

        # The session record is committed by the backend before it answers,
        # but be robust anyway: if /auth/me transiently 401s (e.g. the request
        # races the commit), retry once before giving up.
        me = None
        for attempt in range(2):
            me_response = await client.get(
                '/auth/me', headers={'Authorization': f"Bearer {tokens['access_token']}"}
            )
            if me_response.status_code == 200:
                me = me_response.json()
                break
            await asyncio.sleep(0.25 if attempt == 0 else 1.0)
        if me is None:
            raise AuthenticationError('Authentication service unavailable.')

    # Persist tokens for the sync facade and later API calls. The avatar
    # image itself is NEVER stored here (cookie size) — only the flag and
    # version; the browser loads the image from GET /avatar.
    app.storage.user.update({
        'access_token': tokens['access_token'],
        'refresh_token': tokens['refresh_token'],
        'session_id': tokens.get('session_id'),
        'user_id': me['id'],
        'username': me['username'],
        'role': me['role'],
        'must_change_password': me['must_change_password'],
        'language': me['language'],
        'theme': me.get('theme', 'light'),
        'auth_provider': me.get('auth_provider', 'local'),
        'display_name': me.get('display_name'),
        'has_avatar': bool(me.get('avatar')),
        'avatar_version': 1,
    })
    return me


async def logout() -> None:
    """Revoke the backend session, then clear the local session storage."""
    access = app.storage.user.get('access_token')
    if access:
        try:
            async with httpx.AsyncClient(base_url=BACKEND_URL, timeout=10.0) as client:
                await client.post('/auth/logout', headers={'Authorization': f'Bearer {access}'})
        except Exception as exc:  # noqa: BLE001 — logout must always succeed locally
            logger.warning('Backend logout failed: %s', exc)
    app.storage.user.clear()


async def _handle_session_revoked() -> None:
    """Local logout + redirect, used when the backend session was revoked
    from elsewhere (logout/kick in another tab).

    NiceGUI's storage.user is shared across all tabs of a browser, so only
    ONE tab's heartbeat gets to run this (the others then find the storage
    already cleared and have nothing left to check). To redirect EVERY tab
    we broadcast through localStorage: the 'storage' event fires instantly
    in all other tabs (see the watcher registered in main.py), and the login
    page shows the notice banner client-side — no query parameter needed.
    """
    logger.info('Session revoked on the backend — forcing local logout')
    app.storage.user.clear()
    ui.run_javascript(
        "var n = Date.now();"
        "sessionStorage.setItem('infra-logout-self', String(n));"
        "localStorage.setItem('infra-logout-at', String(n));"
        "window.location.href = '/login';"
    )


async def _apply_profile_digest(data: dict) -> None:
    """Sync the local profile snapshot from the heartbeat digest.

    The heartbeat reports the DB truth (has_avatar, avatar_version,
    display_name). If it differs from the local snapshot, update the storage
    and re-render the header — this is how an avatar/name change made in
    ANOTHER BROWSER (different cookie, invisible to the storage events)
    propagates here within one heartbeat interval.
    """
    storage = app.storage.user
    sid = data.get('session_id')
    if sid and sid != storage.get('session_id'):
        # Fresh from the backend: the session record this connection is
        # bound to (used to recognise 'session_revoked' events for US).
        storage['session_id'] = sid
    changed = (
        bool(data.get('has_avatar')) != bool(storage.get('has_avatar'))
        or int(data.get('avatar_version') or 0) != int(storage.get('avatar_version') or 0)
        or (data.get('display_name') or None) != storage.get('display_name')
    )
    if not changed:
        return
    storage['has_avatar'] = bool(data.get('has_avatar'))
    storage['avatar_version'] = int(data.get('avatar_version') or 0)
    storage['display_name'] = data.get('display_name') or None
    refresh_header = app.storage.client.get('header_account_refresh')
    if refresh_header is not None:
        refresh_header()


async def heartbeat() -> None:
    """Tell the backend this client is still connected (who's-online).

    Called by a timer in the base layout. It doubles as a session watcher:
    when the backend rejects the access token (401), we try to refresh it —
    a simple expiry refreshes silently, but if the session was *revoked*
    (logout or admin kick from another tab), refresh fails too and every
    remaining open tab is redirected to the login page.
    """
    access = app.storage.user.get('access_token')
    refresh_token = app.storage.user.get('refresh_token')
    if not access and not refresh_token:
        # Tokens were wiped locally (e.g. by the auto-refreshing client after
        # a failed call) while the tab still believes it is authenticated:
        # the session is broken, force the local logout too.
        if app.storage.user.get('authenticated', False):
            await _handle_session_revoked()
        return
    try:
        async with httpx.AsyncClient(base_url=BACKEND_URL, timeout=10.0) as client:
            response = await client.put(
                '/auth/heartbeat',
                json={'client': 'web'},
                headers={'Authorization': f'Bearer {access}'} if access else {},
            )
            if response.status_code == 200:
                # Profile digest: live cross-browser avatar/name updates.
                try:
                    await _apply_profile_digest(response.json() or {})
                except Exception:  # noqa: BLE001 — digest must never break the beat
                    pass
            if response.status_code == 401:
                # Access token expired or session revoked: try to refresh.
                if not refresh_token:
                    await _handle_session_revoked()
                    return
                refresh_response = await client.post(
                    '/auth/refresh', json={'refresh_token': refresh_token}
                )
                if refresh_response.status_code != 200:
                    # Session revoked on the backend (logout in another tab…)
                    await _handle_session_revoked()
                    return
                tokens = refresh_response.json()
                app.storage.user['access_token'] = tokens['access_token']
                app.storage.user['refresh_token'] = tokens['refresh_token']
                # Keep the "connected" flag up to date with the fresh token
                beat = await client.put(
                    '/auth/heartbeat',
                    json={'client': 'web'},
                    headers={'Authorization': f"Bearer {tokens['access_token']}"},
                )
                if beat.status_code == 200:
                    try:
                        await _apply_profile_digest(beat.json() or {})
                    except Exception:  # noqa: BLE001
                        pass
    except Exception as exc:  # noqa: BLE001 — network errors must not log the user out
        logger.debug('Heartbeat failed: %s', exc)
