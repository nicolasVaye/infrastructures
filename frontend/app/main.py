"""Application entry point: page routing, shared layout decorator and run targets."""

import json
import logging
import os
import secrets
from functools import wraps
from pathlib import Path

from fastapi import Response
from fastapi.responses import FileResponse

# engine.io caps how many socket packets one HTTP payload may carry (16 by
# default). After a server restart, the browser's socket.io client replays its
# whole queued event buffer over long-polling and the payload is rejected with
# 'ValueError: Too many packets in payload' — every UI event (and the click
# that triggered it) is then silently lost. Raise the cap BEFORE importing
# nicegui (recommended fix, see zauberzeug/nicegui#209).
from engineio.payload import Payload
Payload.max_decode_packets = 500

from nicegui import app, ui

import header
from core import security
from core.database import init_db
from core.logging_config import setup_logging
from services import i18n

# Served as a static file and linked with an mtime cache-buster, so editing the
# stylesheet only needs a browser refresh, not a server restart.
_CSS_PATH = Path(__file__).parent / 'assets' / 'css' / 'global-css.css'


def _add_global_css(shared: bool = False) -> None:
    version = int(_CSS_PATH.stat().st_mtime)
    ui.add_head_html(f'<link rel="stylesheet" href="/assets/css/global-css.css?v={version}">', shared=shared)

# Configure application-wide rolling logging before anything else emits records
setup_logging()

# Initialize the database and seed the default admin (admin/admin) on first run
init_db()

# Apply middlewares
app.add_middleware(security.AuthMiddleware)
app.add_middleware(security.SecurityHeadersMiddleware)

# Health check endpoint: bypasses auth middleware, always returns 200
@app.get('/health')
async def health() -> Response:
    return Response(content='ok', media_type='text/plain', status_code=200)


@app.get('/avatar')
async def avatar() -> Response:
    """Serve the connected user's avatar image, straight from the database.

    The session cookie (app.storage.user) never carries the avatar itself —
    only a version counter — so the browser always loads it from here. The
    route is protected by the auth middleware like any page; the browser
    sends the session cookie along with the <img> request.
    """
    import base64 as _b64
    from fastapi.responses import Response as _Resp
    from core.database import make_client, sync_tokens_to_storage

    client = make_client()
    try:
        me = client.get('/auth/me') or {}
        data_url = me.get('avatar') or ''
    finally:
        sync_tokens_to_storage(client)
        client.close()
    if not data_url.startswith('data:'):
        return _Resp(status_code=404)
    try:
        header, b64 = data_url.split(',', 1)
        mime = header[5:].split(';')[0] or 'image/png'
        raw = _b64.b64decode(b64)
    except Exception:  # noqa: BLE001 — malformed stored avatar
        return _Resp(status_code=404)
    return _Resp(
        content=raw, media_type=mime,
        headers={'Cache-Control': 'private, max-age=86400'},
    )

from views import (
    dashboard_content,
    design_system_content,
    shipping_content,
    production_content,
    orders_content,
    pallets_content,
    packings_content,
    icons_content,
    settings_content,
    user_settings_content,
    users_content,
    audit_content,
    sessions_content,
    jobs_content,
    job_submit_content,
    idps_content,
    print_demo_content,
)
import views.login_content  # noqa: F401  registers the /login route
import views.oidc_callback_content  # noqa: F401  registers the /auth/oidc/callback route
import views.change_password_content  # noqa: F401  registers the /change-password route
from components import print_component

# Config
with open('config.json') as f:
    config = json.load(f)

appName    = config["appName"]
appVersion = config["appVersion"]
appPort    = config["appPort"]

app.add_static_files('/assets', 'assets')


# Progressive Web App: manifest, service worker and install/head tags.
# /manifest.json and /sw.js are allow-listed in core.security so they bypass auth.
_SW_PATH = Path(__file__).parent / 'assets' / 'pwa' / 'sw.js'


@app.get('/manifest.json')
async def pwa_manifest() -> Response:
    manifest = {
        'name': appName,
        'short_name': appName,
        'description': f'{appName} progressive web app.',
        'start_url': '/',
        'scope': '/',
        'display': 'standalone',
        'orientation': 'any',
        'background_color': '#ffffff',
        'theme_color': '#18181b',
        'icons': [
            {'src': '/assets/icons/icon-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': '/assets/icons/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': '/assets/icons/icon-maskable-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
    }
    return Response(content=json.dumps(manifest), media_type='application/manifest+json')


@app.get('/sw.js')
async def pwa_service_worker() -> FileResponse:
    # Served from root so its scope covers the whole origin.
    return FileResponse(
        _SW_PATH,
        media_type='application/javascript',
        headers={'Service-Worker-Allowed': '/', 'Cache-Control': 'no-cache'},
    )


_PWA_HEAD = f'''<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#18181b">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="{appName}">
<link rel="apple-touch-icon" href="/assets/icons/apple-touch-icon.png">
<script>
if ('serviceWorker' in navigator) {{
  window.addEventListener('load', function () {{
    navigator.serviceWorker.register('/sw.js').catch(function (e) {{ console.error('SW registration failed', e); }});
  }});
}}
</script>'''

ui.add_head_html(_PWA_HEAD, shared=True)


# Watches for a logout happening in another tab of the same browser. The
# logging-out tab writes localStorage['infra-logout-at']; the 'storage' event
# fires instantly in every OTHER tab (shared NiceGUI storage.user means the
# heartbeat alone cannot detect this — the first tab to react clears the
# shared storage and the others are left with nothing to check).
_LOGOUT_WATCHER_JS = '''<script>
window.addEventListener('storage', function (e) {
  if (e.key === 'infra-logout-at' && e.newValue) { window.location.href = '/login'; }
});
</script>'''


# Base layout decorator: applies theme, global CSS and sidebar shell
def with_base_layout(route_handler):
    @wraps(route_handler)
    def wrapper(*args, **kwargs):
        from services import theme as theme_service
        theme_service.apply(theme_service.current())
        _add_global_css(shared=True)
        ui.add_head_html('<link rel="stylesheet" href="/assets/css/icons.css">', shared=True)
        ui.add_head_html(_LOGOUT_WATCHER_JS, shared=True)

        # Preload avoids a layout-shift flash when the sidebar logo first renders
        ui.add_head_html('<link rel="preload" href="/assets/images/logo.png" as="image">')

        if 'sidebar-collapsed' not in app.storage.user:
            app.storage.user['sidebar-collapsed'] = False

        # Heartbeat so the backend knows this client is connected. It also
        # watches for session revocation (logout/kick in another tab) and
        # redirects to /login when it happens — hence the short interval.
        if app.storage.user.get('authenticated', False):
            from services import api_client
            ui.timer(15.0, api_client.heartbeat)
            # Live push (SSE per tab): instant propagation of avatar/name
            # changes, session revocations and job updates.
            from services import events_client
            events_client.install_event_listener()

        with header.frame(title=appName, version=appVersion):
            return route_handler(*args, **kwargs)
    return wrapper

# Page and sub-page routing
@ui.page('/')
@with_base_layout
def root():
    ui.sub_pages({
    '/': index,
    '/design-system': design_system,
    '/shipping': shipping,
    '/production': production,
    '/production/{searchFilter}' : production_search,
    '/orders' : orders,
    '/pallets' : pallets,
    '/packing' : packing,
    '/icons'      : icons,
    '/print-demo' : print_demo,
    '/settings'   : settings,
    '/account'    : account,
    '/jobs'       : jobs_list,
    '/jobs/new'   : jobs_new,
    })


# Sub-page handlers

def _localized(build, *args, **kwargs):
    """Render a view inside a refreshable so it rebuilds live on language change."""
    view = ui.refreshable(lambda: build(*args, **kwargs))
    view()
    i18n.register_view_refresh(view.refresh)


def index():
    _localized(dashboard_content.content)

def design_system():
    _localized(design_system_content.content)

def shipping():
    _localized(shipping_content.content)

def production():
    _localized(production_content.content, searchFilter='')

def orders():
    _localized(orders_content.content)

def pallets():
    _localized(pallets_content.content)

def packing():
    _localized(packings_content.content)

def icons():
    _localized(icons_content.content)

def print_demo():
    _localized(print_demo_content.content)

def settings():
    from models.enums import UserRole
    if app.storage.user.get('role') != UserRole.ADMIN.value:
        ui.navigate.to('/')
        return
    _localized(settings_content.content)


def account():
    user_settings_content.content()

def _admin_guard():
    from models.enums import UserRole
    if app.storage.user.get('role') != UserRole.ADMIN.value:
        ui.navigate.to('/')
        return True
    return False


def jobs_list():
    if _admin_guard():
        return
    _localized(jobs_content.content)


def jobs_new():
    if _admin_guard():
        return
    _localized(job_submit_content.content)

def production_search(searchFilter):
    _localized(production_content.content, searchFilter=searchFilter)


# Standalone print route: no sidebar, no header, no layout wrapper
@ui.page('/print/{data}')
def print_standalone(data: str):
    _add_global_css()
    print_component.content(data)


def _get_storage_secret() -> str:
    """Return the session-signing secret.

    Prefers the STORAGE_SECRET environment variable, otherwise falls back to a
    strong random secret persisted (with restrictive permissions) under data/ so
    cookies survive restarts. Never a weak hardcoded value.
    """
    env_secret = os.environ.get('STORAGE_SECRET')
    if env_secret:
        return env_secret

    secret_file = Path(__file__).parent / 'data' / '.storage_secret'
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    if secret_file.exists():
        return secret_file.read_text().strip()

    secret = secrets.token_hex(32)
    secret_file.write_text(secret)
    try:
        os.chmod(secret_file, 0o600)
    except OSError:
        pass
    logging.getLogger(__name__).warning(
        'STORAGE_SECRET not set — generated a persistent random secret at %s. '
        'Set STORAGE_SECRET in the environment for production deployments.',
        secret_file,
    )
    return secret


# Entry point: uncomment exactly one target

# 1) Development: auto-reload on file changes
ui.run(root, storage_secret=_get_storage_secret(), title=appName, port=appPort,
       favicon='favicon.ico', reconnect_timeout=20)
'''
#2) Production — no auto-reload
ui.run(root, host='0.0.0.0', storage_secret=_get_storage_secret(), title=appName, port=appPort,
        favicon='favicon.ico', reconnect_timeout=20, reload=False)
'''

'''
#3) Production over HTTPS — no auto-reload + self-signed TLS certs (see certs/)
ui.run(root, host='0.0.0.0', storage_secret=_get_storage_secret(), title=appName, port=appPort,
        favicon='favicon.ico', reconnect_timeout=20, reload=False,
        ssl_certfile='certs/cert.pem', ssl_keyfile='certs/key.pem')
'''

'''
#4) Docker — STORAGE_SECRET is resolved via _get_storage_secret(); HOST comes from docker-compose.yaml
ui.run(root, storage_secret=_get_storage_secret(), host=os.environ['HOST'], title=appName,
        port=appPort, favicon='favicon.ico', reconnect_timeout=20, reload=False)
'''
# python -m PyInstaller --name 'ProductionSuite' --onedir main.py --add-data '...\nicegui;nicegui' --noconfirm --clean