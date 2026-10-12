"""Login page — authenticates against the backend REST API.

Credentials are verified by the backend (single source of truth for users,
roles and sessions); the frontend stores the returned JWTs in its session
storage and shows the account dropdown / pages based on the /auth/me payload.
"""

import logging
import time
from pathlib import Path

from fastapi import Request  # noqa: F401  (injected by NiceGUI into page handlers)
from nicegui import app, ui

from core.security import is_locked, record_attempt
from services import api_client
from services.api_client import AuthenticationError
from components.notifications import notify

logger = logging.getLogger(__name__)

# CSS cached once at import so it is not read from disk per request
_CSS = (Path(__file__).parent.parent / 'assets' / 'css' / 'global-css.css').read_text()


def get_current_year() -> int:
    return time.localtime().tm_year


@ui.page('/login')
async def login_page(request: Request, redirect_to: str = '/', reason: str = '') -> None:
    """Login page — posts credentials to POST /auth/login on the backend."""

    # Prevent open redirect
    if not redirect_to.startswith('/') or redirect_to.startswith('//'):
        redirect_to = '/'

    if reason not in ('timeout', 'expired', 'revoked'):
        reason = ''

    if app.storage.user.get('authenticated', False):
        ui.navigate.to(redirect_to)
        return

    # Capture IP at page-load time (HTTP context), not in the click handler
    forwarded_for = request.headers.get('X-Forwarded-For', '')
    client_ip: str = forwarded_for.split(',')[0].strip() if forwarded_for else (
        request.client.host if request.client else 'unknown'
    )

    async def try_login() -> None:
        if not username.value or not password.value:
            notify('Please enter username and password.', type='warning')
            return

        # Rate-limit by IP and by targeted username so neither a single source
        # nor a single account can be brute-forced from the login page itself.
        user_key = f"user:{username.value.strip().lower()}"
        for key in (client_ip, user_key):
            locked, lock_msg = is_locked(key)
            if locked:
                notify(lock_msg, type='negative')
                return

        try:
            user = await api_client.login(username.value.strip(), password.value)
        except AuthenticationError as exc:
            record_attempt(client_ip, success=False)
            record_attempt(user_key, success=False)
            logger.warning(f"Failed login for '{username.value}' from {client_ip}")
            # The backend already recorded the failure in its audit trail.
            notify(exc.message, type='negative')
            return

        record_attempt(client_ip, success=True)
        record_attempt(user_key, success=True)
        logger.info(f"Login successful for '{user['username']}' from {client_ip}")
        now_ts = time.time()
        app.storage.user.update({
            'authenticated': True,
            'email': user.get('email'),
            'display_name': user.get('display_name'),
            'avatar': user.get('avatar'),
            'login_at': now_ts,
            'last_activity': now_ts,
        })
        # Kick off the first heartbeat so the user shows up as connected
        await api_client.heartbeat()
        ui.navigate.to('/change-password' if user['must_change_password'] else redirect_to)

    # Styling
    ui.colors(primary='#18181b', secondary='#f4f4f5', positive='#4caf50',
              negative='#ef4444', warning='#f59e0b', info='#3b82f6', accent='#e4e4e7')

    ui.add_head_html(f'<style>{_CSS}</style>')
    ui.add_head_html('<link rel="stylesheet" href="/assets/css/icons.css">')
    ui.add_head_html('<meta name="viewport" content="width=device-width, initial-scale=1.0">')

    # Notice for logouts detected client-side (logout/revocation in another
    # tab). The redirect deliberately goes to a CLEAN '/login' URL — a query
    # parameter there broke signing back in — so the banner is rendered
    # client-side from the localStorage breadcrumb instead. The tab that
    # initiated the logout recognises its own nonce (sessionStorage) and
    # sees no banner.
    ui.add_head_html('''<script>
(function () {
  var t = localStorage.getItem('infra-logout-at');
  var self = sessionStorage.getItem('infra-logout-self');
  if (t && (Date.now() - Number(t)) < 60000 && t !== self) {
    localStorage.removeItem('infra-logout-at');
    function show() {
      var d = document.createElement('div');
      d.textContent = 'You were logged out from another tab or session. Please log in again.';
      d.style.cssText = 'position:fixed;top:18px;left:50%;transform:translateX(-50%);'
        + 'z-index:9999;background:#f59e0b;color:#fff;padding:10px 20px;border-radius:8px;'
        + 'font-family:sans-serif;font-size:14px;box-shadow:0 2px 10px rgba(0,0,0,.25);'
        + 'max-width:90%;text-align:center;';
      document.body.appendChild(d);
      setTimeout(function () { d.remove(); }, 7000);
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', show); }
    else { show(); }
  }
})();
</script>''')

    if reason:
        _msg = (
            'Your session expired due to inactivity. Please log in again.'
            if reason == 'timeout'
            else 'You were logged out from another tab or session. Please log in again.'
            if reason == 'revoked'
            else 'Your session has expired. Please log in again.'
        )
        ui.timer(0.5, lambda m=_msg: notify(m, type='warning', duration=7000), once=True)

    with ui.column().classes('absolute-center items-center gap-2').style(
        'min-height: 70vh; width: 100%; padding: 1rem;'
    ):
        # Logo
        ui.html(
            '<div style="width:15rem;height:7rem;'
            'background-image:url(\'/assets/images/logo.png\');'
            'background-size:contain;background-repeat:no-repeat;'
            'background-position:center;margin-bottom:1rem;"></div>',
            sanitize=False,
        )

        with ui.card().classes('login-card').style('width: 100%; max-width: 450px;'):
            with ui.column().classes('w-full gap-4'):
                ui.label('Infrastructure Login').classes('text-xl font-bold text-center mb-2')

                with ui.column().classes('w-full gap-3'):
                    with ui.element('div').classes('w-full'):
                        ui.label('Username').classes('field-label')
                        username = ui.input(placeholder='').classes('w-full').props('outlined dense')
                        username.on('keydown.enter', try_login)

                    with ui.element('div').classes('w-full'):
                        ui.label('Password').classes('field-label')
                        password = ui.input(
                            password=True, password_toggle_button=True
                        ).classes('w-full').props('outlined dense')
                        password.on('keydown.enter', try_login)

                    ui.button('Sign in', on_click=try_login, color='white') \
                        .props('no-caps') \
                        .classes('button button-primary w-full mt-4')

                # External OIDC providers (e.g. Keycloak), managed by admins.
                try:
                    import httpx as _httpx
                    _providers = (await _httpx.AsyncClient(timeout=5.0).get(
                        f"{api_client.BACKEND_URL}/auth/providers")).json()
                except Exception:  # noqa: BLE001 — login must work if the API hiccups
                    _providers = []
                if _providers:
                    ui.separator().classes('my-2')
                    ui.label('or sign in with').classes('text-xs text-muted w-full text-center')
                    for _p in _providers:
                        async def _oidc_login(idp_id: int = _p['id']) -> None:
                            import httpx as _h
                            try:
                                async with _h.AsyncClient(base_url=api_client.BACKEND_URL, timeout=10.0) as c:
                                    r = await c.get(f'/auth/oidc/{idp_id}/authorize')
                                r.raise_for_status()
                                data = r.json()
                            except Exception as exc:  # noqa: BLE001
                                notify(str(exc), type='negative')
                                return
                            # The state is signed by the backend; the callback
                            # page sends it back for verification.
                            app.storage.user['oidc_state'] = data['state']
                            ui.navigate.to(data['authorize_url'], new_tab=False)

                        ui.button(f"Sign in with {_p['name']}", icon='key',
                                  on_click=_oidc_login, color='white') \
                            .props('no-caps outline') \
                            .classes('button w-full mt-2')

        ui.label(f'© {get_current_year()} Infrastructure').classes('text-xs text-muted mt-6')
