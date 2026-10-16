"""Application entry point: page routing, shared layout decorator and run targets."""

import json
import logging
import os
import secrets
from functools import wraps
from pathlib import Path

from fastapi import Request, Response
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

# CookieRotationGuard must sit OUTERMOST (outside NiceGUI's session
# middleware, which appends Set-Cookie to every response it sees) — it is
# registered on startup, AFTER ui.run() has added the session middlewares.
# Starlette refuses add_middleware once the stack is built (first lifespan
# call), so invalidate it first: the NEXT request rebuilds the chain with
# the guard outermost, able to strip Set-Cookie from session-less public
# routes. See the class docstring for why this matters (WebKitGTK favicon
# probes rotated the session cookie → F5 logout in Epiphany).
def _install_cookie_guard() -> None:
    app.middleware_stack = None
    app.add_middleware(security.CookieRotationGuard)


app.on_startup(_install_cookie_guard)

# Health check endpoint: bypasses auth middleware, always returns 200
@app.get('/health')
async def health() -> Response:
    return Response(content='ok', media_type='text/plain', status_code=200)


@app.post('/sidebar-width')
async def set_sidebar_width(request: Request) -> Response:
    """Persist the drawer width chosen with the sidebar splitter.

    The splitter drag/click runs client-side (see _SIDEBAR_SPLITTER_JS) for
    smooth live resizing; this endpoint only stores the final width so the
    next page render (any tab, storage is per user) restores it.
    """
    try:
        payload = await request.json()
        width = int(payload.get('width', 240))
    except Exception:  # noqa: BLE001  malformed payloads fall back to default
        width = 240
    width = max(100, min(400, width))
    app.storage.user['sidebar-width'] = width
    return Response(content='{"ok": true}', media_type='application/json')


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


# Application logo, straight from the backend's app_settings table (uploaded
# by the admin on the App Settings page). Public and unauthenticated: the
# browser needs it for the favicon and the login page BEFORE any sign-in.
# Falls back to the bundled asset when no custom logo is configured; the
# process-level TTL cache (core.backend_assets) keeps the 404 "no logo"
# misses out of the backend logs — one probe per minute instead of one per
# page load — and is invalidated by the settings page right after an upload.
_LOGO_FALLBACK = Path(__file__).parent / 'assets' / 'images' / 'logo.svg'


def _backend_logo(path: str) -> tuple[bytes, str] | None:
    """Fetch a logo payload from the backend (unauthenticated, public route)."""
    from core.backend_assets import backend_asset
    return backend_asset(path)


@app.get('/logo')
async def logo() -> Response:
    fetched = _backend_logo('/app/logo')
    if fetched is None:
        return FileResponse(_LOGO_FALLBACK, media_type='image/svg+xml',
                            headers={'Cache-Control': 'no-cache'})
    raw, mime = fetched
    return Response(content=raw, media_type=mime,
                    headers={'Cache-Control': 'no-cache'})


@app.get('/favicon.ico')
async def favicon() -> Response:
    """Serve the tab icon: the admin-uploaded logo (ICO generated server-side),
    falling back to the bundled SVG logo."""
    fetched = _backend_logo('/app/logo.ico')
    if fetched is not None:
        raw, _mime = fetched
        return Response(content=raw, media_type='image/x-icon',
                        headers={'Cache-Control': 'no-cache'})
    return FileResponse(_LOGO_FALLBACK, media_type='image/svg+xml',
                        headers={'Cache-Control': 'no-cache'})


# PWA / apple icons, regenerated server-side from the uploaded logo (see
# backend GET /app/logo/icons/{name}). The old static PNGs under
# assets/icons were deleted: they went stale as soon as the admin uploaded a
# new logo. When no PNG exists (SVG logo, or none configured) the bundled
# logo.svg is served instead — browsers accept SVG icons everywhere except
# the apple-touch-icon, which iOS then simply ignores.
# FileResponse extends Response, so the annotation stays Response (a
# Response | FileResponse union is not a valid Pydantic response model).
def _serve_icon(name: str) -> Response:
    fetched = _backend_logo(f'/app/logo/icons/{name}')
    if fetched is not None:
        raw, _mime = fetched
        return Response(content=raw, media_type='image/png',
                        headers={'Cache-Control': 'no-cache'})
    return FileResponse(_LOGO_FALLBACK, media_type='image/svg+xml',
                        headers={'Cache-Control': 'no-cache'})


@app.get('/icon-192.png')
async def icon_192() -> Response:
    return _serve_icon('icon-192.png')


@app.get('/icon-512.png')
async def icon_512() -> Response:
    return _serve_icon('icon-512.png')


@app.get('/icon-maskable-512.png')
async def icon_maskable_512() -> Response:
    return _serve_icon('icon-maskable-512.png')


@app.get('/apple-touch-icon.png')
async def apple_touch_icon() -> Response:
    return _serve_icon('apple-touch-icon.png')

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
    # Icons come from the logo upload (backend-generated PNGs). When the
    # logo is an SVG — or none is configured — no PNG exists and the SVG
    # itself is the icon (served by the /icon-*.png routes).
    fetched = _backend_logo('/app/logo/icons/icon-192.png')
    if fetched is not None:
        icons = [
            {'src': '/icon-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': '/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': '/icon-maskable-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ]
    else:
        icons = [{'src': '/logo', 'sizes': 'any', 'type': 'image/svg+xml', 'purpose': 'any'}]
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
        'icons': icons,
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
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" href="/logo" type="image/svg+xml">
<meta name="theme-color" content="#18181b">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="{appName}">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<script>
if ('serviceWorker' in navigator) {{
  window.addEventListener('load', function () {{
    navigator.serviceWorker.register('/sw.js').then(function (reg) {{
      // Check for an updated worker on EVERY load: without this, browsers
      // only re-fetch sw.js every ~24h and users keep a stale CSS/JS cache
      // after a deploy ("the fix changed nothing" although it shipped).
      reg.update().catch(function () {{}});
    }}).catch(function (e) {{ console.error('SW registration failed', e); }});
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


# Sidebar splitter: the vertical handle on the drawer's right border can be
# DRAGGED to resize the nav bar live (100–400 px) or CLICKED to toggle between
# icon-only (100 px) and standard (240 px) width. Everything happens in the
# browser for smoothness; only the final width is POSTed to /sidebar-width so
# the server-side render (and every other tab of the same user) restores it.
# Label visibility is CSS-driven: 'sidebar-wide' on <body> shows the text
# labels, otherwise the labels collapse to icons and the hover hints show.
_SIDEBAR_SPLITTER_JS = '''<script>
(function () {
  var MINW = 100, MAXW = 400, TOGGLE = 240, WIDE = 180;

  // Last width APPLIED to the drawer (its CSS target). getBoundingClientRect
  // must never feed a new gesture: mid-animation it returns a transient
  // value, which made the handle jump and drift away from the drawer edge.
  var currentW = 0;
  // rAF follower id while the drawer's CSS transition runs (click-toggle).
  var follower = 0;

  function get(name) { return document.querySelector(name); }

  function apply(w, persist) {
    currentW = w;
    var handle = get('.sidebar-collapse-handle');
    var drawer = get('.q-drawer--left');
    if (handle) {
      handle.style.left = (w - 5) + 'px';
      var icon = handle.querySelector('.sidebar-collapse-handle-icon');
      if (icon) { icon.textContent = (w >= WIDE) ? 'chevron_left' : 'chevron_right'; }
    }
    if (drawer) { drawer.style.width = w + 'px'; }
    // Quasar sizes the page container from the DRAWER MODEL width; our JS
    // resize diverges from it, so the padding must follow manually —
    // without this the sub-pages never gained/lost space on resize.
    var container = get('.q-page-container');
    if (container) { container.style.paddingLeft = w + 'px'; }
    var wide = w >= WIDE;
    document.querySelectorAll('.sidebar-label').forEach(function (l) {
      l.classList.toggle('expanded', wide);
      l.classList.toggle('collapsed', !wide);
    });
    document.body.classList.toggle('sidebar-wide', wide);
    if (persist) {
      fetch('/sidebar-width', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ width: w })
      }).catch(function () {});
    }
  }

  // While the drawer animates (click-toggle), move the handle with its LIVE
  // width each frame: without this the handle jumped to its target instantly
  // while the drawer edge was still mid-flight — the handle visibly detached
  // from the nav-bar edge for the whole transition (user-visible bug).
  function followDrawer() {
    if (follower) { cancelAnimationFrame(follower); }
    function step() {
      var drawer = get('.q-drawer--left');
      var handle = get('.sidebar-collapse-handle');
      var container = get('.q-page-container');
      if (!drawer || !handle) { follower = 0; return; }
      var w = Math.round(drawer.getBoundingClientRect().width);
      handle.style.left = (w - 5) + 'px';
      if (container) { container.style.paddingLeft = w + 'px'; }
      if (Math.abs(w - currentW) > 0.5) {
        follower = requestAnimationFrame(step);
      } else {
        handle.style.left = (currentW - 5) + 'px';  // exact landing
        if (container) { container.style.paddingLeft = currentW + 'px'; }
        follower = 0;
      }
    }
    follower = requestAnimationFrame(step);
  }

  // Initial sync: server-side rendering sets the drawer width but not the
  // handle position, so reflect it once the drawer hits the DOM.
  var tries = 0;
  var initTimer = setInterval(function () {
    var drawer = get('.q-drawer--left');
    var handle = get('.sidebar-collapse-handle');
    if (drawer && handle) {
      currentW = Math.round(drawer.getBoundingClientRect().width) || TOGGLE;
      handle.style.left = (currentW - 5) + 'px';
      document.body.classList.toggle('sidebar-wide', currentW >= WIDE);
      clearInterval(initTimer);
    } else if (++tries > 150) { clearInterval(initTimer); }
  }, 200);

  var dragging = false, moved = false, startX = 0, startW = TOGGLE;

  function beginDrag(x) {
    if (follower) { cancelAnimationFrame(follower); follower = 0; }
    dragging = true; moved = false;
    startX = x;
    startW = currentW || TOGGLE;  // never read a mid-animation rect here
    var drawer = get('.q-drawer--left');
    if (drawer) { drawer.style.transition = 'none'; }
    var handle = get('.sidebar-collapse-handle');
    if (handle) { handle.style.transition = 'none'; }
  }

  function moveDrag(x) {
    if (!dragging) { return; }
    var dx = x - startX;
    if (Math.abs(dx) > 3) { moved = true; }
    apply(Math.min(MAXW, Math.max(MINW, startW + dx)), false);
  }

  function endDrag(x) {
    if (!dragging) { return; }
    dragging = false;
    var drawer = get('.q-drawer--left');
    if (drawer) { drawer.style.transition = ''; }
    var handle = get('.sidebar-collapse-handle');
    if (handle) { handle.style.transition = ''; }
    var w;
    if (moved) {
      w = Math.round(Math.min(MAXW, Math.max(MINW, startW + x - startX)));
      apply(w, false);
    } else {
      // Simple click: toggle icon-only <-> standard width. The drawer then
      // ANIMATES: let the rAF follower keep the handle glued to its edge.
      w = (startW < WIDE) ? TOGGLE : MINW;
      apply(w, false);
      followDrawer();
    }
    fetch('/sidebar-width', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ width: w })
    }).catch(function () {});
  }

  document.addEventListener('mousedown', function (ev) {
    if (ev.target.closest && ev.target.closest('.sidebar-collapse-handle')) {
      ev.preventDefault();
      beginDrag(ev.clientX);
    }
  });
  document.addEventListener('mousemove', function (ev) { moveDrag(ev.clientX); });
  document.addEventListener('mouseup', function (ev) { endDrag(ev.clientX); });

  document.addEventListener('touchstart', function (ev) {
    if (ev.target.closest && ev.target.closest('.sidebar-collapse-handle')) {
      beginDrag(ev.touches[0].clientX);
    }
  }, { passive: true });
  document.addEventListener('touchmove', function (ev) {
    if (dragging) { moveDrag(ev.touches[0].clientX); }
  }, { passive: true });
  document.addEventListener('touchend', function (ev) {
    if (dragging) { endDrag((ev.changedTouches[0] || {}).clientX || startX); }
  });
})();
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
        ui.add_head_html('<link rel="preload" href="/logo" as="image">')

        if 'sidebar-width' not in app.storage.user:
            app.storage.user['sidebar-width'] = 240
        ui.add_head_html(_SIDEBAR_SPLITTER_JS, shared=True)

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