"""OIDC callback page: landing point of the authorization-code flow.

The IdP (Keycloak) redirects the browser here with ?code=...&state=... The
page is public (the user is not logged in yet): it forwards the pair to the
backend, which exchanges the code, verifies the ID token and returns the same
JWT pair as a local login. From there the standard login flow resumes.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import Request
from nicegui import app, ui

import os

logger = logging.getLogger(__name__)

BACKEND_URL = os.environ.get('BACKEND_URL', 'http://localhost:8000')


@ui.page('/auth/oidc/callback')
async def oidc_callback(request: Request, code: str = '', state: str = '',
                        idp: str = '0', error: str = '') -> None:
    ui.colors(primary='#18181b')

    with ui.column().classes('absolute-center items-center gap-2'):
        ui.spinner(size='2rem')

        if error:
            ui.label('The identity provider refused the login.').classes('text-negative')
            ui.label(error[:300]).classes('text-xs text-muted')
            ui.button('Back to login', on_click=lambda: ui.navigate.to('/login')).props('no-caps')
            return

        if not code or not state:
            ui.label('Missing authorization code — please retry from the login page.').classes('text-negative')
            ui.button('Back to login', on_click=lambda: ui.navigate.to('/login')).props('no-caps')
            return

        ui.label('Finishing sign-in with your identity provider…').classes('text-muted')

        try:
            async with httpx.AsyncClient(base_url=BACKEND_URL, timeout=15.0) as client:
                response = await client.post(
                    f'/auth/oidc/{idp}/callback',
                    json={'code': code, 'state': state},
                    headers={'X-Client-Label': 'oidc',
                             'X-User-Agent': request.headers.get('User-Agent', '')},
                )
                if response.status_code != 200:
                    detail = response.json().get('detail', response.text) if response.content else response.text
                    raise RuntimeError(str(detail)[:300])
                tokens = response.json()

                me_response = await client.get(
                    '/auth/me', headers={'Authorization': f"Bearer {tokens['access_token']}"}
                )
                me_response.raise_for_status()
                user = me_response.json()
        except Exception as exc:  # noqa: BLE001 — show any failure inline
            logger.warning('OIDC callback failed: %s', exc)
            ui.label('Sign-in failed.').classes('text-negative')
            ui.label(str(exc)[:300]).classes('text-xs text-muted')
            ui.button('Back to login', on_click=lambda: ui.navigate.to('/login')).props('no-caps')
            return

        import time
        now_ts = time.time()
        app.storage.user.update({
            'authenticated': True,
            'access_token': tokens['access_token'],
            'refresh_token': tokens['refresh_token'],
            'user_id': user['id'],
            'username': user['username'],
            'role': user['role'],
            'must_change_password': user['must_change_password'],
            'language': user['language'],
            'email': user.get('email'),
            'display_name': user.get('display_name'),
            'avatar': user.get('avatar'),
            'login_at': now_ts,
            'last_activity': now_ts,
        })

        from services import api_client
        await api_client.heartbeat()
        ui.navigate.to('/')
