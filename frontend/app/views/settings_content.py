"""Admin-only application settings page for logging configuration.

The log level is applied live across the whole application and persisted so it
survives restarts.  Log records are written to a rolling file in the ``logs/``
folder (see :mod:`core.logging_config`).
"""

from nicegui import app, ui

from components.notifications import notify
from core.logging_config import LOG_FILE, LOG_LEVELS, get_log_level, set_log_level
from models.enums import UserRole
from services import i18n
from services.i18n import t
from views._common import page_header


def _is_admin() -> bool:
    return app.storage.user.get('role') == UserRole.ADMIN.value


def content() -> None:
    """Admin hub: one horizontal tab per administration area.

    Everything an administrator configures lives here: general app settings
    (logging), users & roles, connected sessions, the audit log and the
    identity providers. Each tab renders the existing view module unchanged.
    """
    page_header(t('appsettings.title'), t('appsettings.subtitle'))

    if not _is_admin():
        with ui.column().classes('card w-full items-center gap-2 p-8'):
            ui.icon('lock', size='2rem').classes('text-muted')
            ui.label(t('appsettings.admin_only')).classes('text-muted')
        return

    # -- Admin hub tabs ---------------------------------------------------
    # Lazy imports keep the module import graph flat; each tab body is the
    # existing view, rendered inside its panel (only the active one builds).
    from views import audit_content, idps_content, sessions_content, users_content

    with ui.tabs().classes('tabs-bar') as tabs:
        tab_general  = ui.tab(name='general',  label=t('appsettings.tab.general'),  icon='tune')
        tab_users    = ui.tab(name='users',    label=t('appsettings.tab.users'),    icon='group')
        tab_roles    = ui.tab(name='roles',    label=t('appsettings.tab.roles'),    icon='admin_panel_settings')
        tab_sessions = ui.tab(name='sessions', label=t('appsettings.tab.sessions'), icon='devices')
        tab_audit    = ui.tab(name='audit',    label=t('appsettings.tab.audit'),    icon='history')
        tab_idps     = ui.tab(name='idps',     label=t('appsettings.tab.idps'),     icon='vpn_key')

    with ui.tab_panels(tabs, value=tab_general).classes('w-full'):
        with ui.tab_panel(tab_general):
            _general_panel()
        with ui.tab_panel(tab_users):
            users_content.users_tab()
        with ui.tab_panel(tab_roles):
            users_content.roles_tab()
        with ui.tab_panel(tab_sessions):
            sessions_content.content()
        with ui.tab_panel(tab_audit):
            audit_content.content()
        with ui.tab_panel(tab_idps):
            idps_content.content()


def _general_panel() -> None:
    """Logging configuration (the original /settings body)."""
    def _on_level_change(e) -> None:
        if set_log_level(e.value):
            notify(t('appsettings.level_saved').format(level=e.value), type='positive')

    with ui.column().classes('card w-full gap-1 p-6').style('max-width: 640px;'):
        with ui.row().classes('items-center gap-2'):
            ui.icon('article', size='sm').classes('text-muted')
            ui.label(t('appsettings.logging')).classes('card-title')
        ui.label(t('appsettings.logging_desc')).classes('card-description mb-4')

        with ui.element('div').classes('w-full'):
            ui.label(t('appsettings.log_level')).classes('field-label')
            ui.select(
                LOG_LEVELS,
                value=get_log_level(),
                on_change=_on_level_change,
            ).props('outlined dense').classes('w-full').style('max-width: 260px;')

        with ui.row().classes('items-center gap-2 mt-4'):
            ui.label(f"{t('appsettings.log_file')}:").classes('text-sm text-muted')
            ui.label(str(LOG_FILE)).classes('text-sm').style('font-family: monospace;')

    _timezone_panel()
    _sse_log_panel()
    _logo_panel()



def _sse_log_panel() -> None:
    """Realtime diagnostics: the backend's event_log table (SSE drops,
    LISTEN bridge reconnects, replay gaps…). Read-only view; the backend
    writes one row per incident (see app/events.py)."""
    from services.tz import format_local, get_app_timezone

    @ui.refreshable
    def log_list() -> None:
        try:
            with get_session() as session:
                rows = session.get('/system/events-log') or []
        except Exception:  # noqa: BLE001 — backend unreachable
            rows = None
        display_tz = get_app_timezone()
        if rows is None:
            ui.label(t('appsettings.sse_unavailable')).classes('text-sm text-muted')
            return
        if not rows:
            with ui.row().classes('items-center gap-2'):
                ui.icon('check_circle', size='1rem').classes('text-muted')
                ui.label(t('appsettings.sse_ok')).classes('text-sm text-muted')
            return
        with ui.column().classes('w-full gap-0'):
            for r in rows:
                with ui.row().classes('w-full items-start gap-2 py-1 no-wrap').style(
                    'border-bottom: 1px solid var(--border, #f4f4f5);'
                ):
                    badge = 'badge-success' if r['level'] == 'info' else (
                        'badge-warning' if r['level'] == 'warning' else 'badge-danger')
                    with ui.element('span').classes(f'badge {badge}').style(
                            'gap: 4px; min-width: 78px; justify-content: center;'):
                        ui.label(r['level'])
                    ui.label(format_local(r['created_at'], display_tz)) \
                        .classes('text-xs text-muted').style('font-family: monospace;')
                    ui.label(r['message']).classes('text-xs flex-1')

    with ui.column().classes('card w-full gap-1 p-6 mt-4').style('max-width: 640px;'):
        with ui.row().classes('items-center gap-2'):
            ui.icon('monitor_heart', size='sm').classes('text-muted')
            ui.label(t('appsettings.sse_log')).classes('card-title')
            ui.space()
            ui.button(icon='refresh', on_click=log_list.refresh) \
                .props('flat dense').tooltip(t('common.refresh'))
        ui.label(t('appsettings.sse_log_desc')).classes('card-description mb-3')
        log_list()


_MAX_LOGO_BYTES = 2 * 1024 * 1024  # mirrors the backend limit
_LOGO_MIMES = ('image/svg+xml', 'image/png', 'image/jpeg')


def _timezone_panel() -> None:
    """Display timezone for the audit log and the connected sessions list.

    All timestamps stay stored as UTC; this only changes how the frontend
    renders them (GET/PUT /app/timezone → app_settings table).
    """
    from core.database import get_session
    from services import tz as tz_service

    state = {'value': tz_service.get_app_timezone()}

    def _options() -> list[str]:
        # The stored zone is always offered, even when not in the curated
        # list (a previous admin may have picked an exotic one).
        opts = list(tz_service.COMMON_TIMEZONES)
        if state['value'] not in opts:
            opts.insert(1, state['value'])
        return opts

    def _on_change(e) -> None:
        value = e.value or 'UTC'
        try:
            with get_session() as session:
                session.put('/app/timezone', json={'timezone': value})
        except Exception:  # noqa: BLE001  backend unreachable / auth expired
            notify(t('appsettings.timezone_bad'), type='negative')
            return
        state['value'] = value
        tz_service.invalidate_cache()
        notify(t('appsettings.timezone_saved').format(tz=value), type='positive')

    with ui.column().classes('card w-full gap-1 p-6 mt-4').style('max-width: 640px;'):
        with ui.row().classes('items-center gap-2'):
            ui.icon('schedule', size='sm').classes('text-muted')
            ui.label(t('appsettings.timezone')).classes('card-title')
        ui.label(t('appsettings.timezone_desc')).classes('card-description mb-4')

        with ui.element('div').classes('w-full'):
            ui.label(t('appsettings.timezone')).classes('field-label')
            ui.select(
                _options(),
                value=state['value'],
                on_change=_on_change,
            ).props('outlined dense').classes('w-full').style('max-width: 260px;')


def _logo_panel() -> None:
    """Application logo: upload SVG/PNG/JPG, persisted in the backend DB.

    The logo is served by GET /logo (header, login page) and the browser tab
    icon is regenerated from it (ICO built server-side for raster formats).
    """
    import base64

    from components.dropzone import dropzone
    from core.database import get_session

    state = {'version': int(app.storage.user.get('logo_version', 0))}

    @ui.refreshable
    def logo_preview() -> None:
        v = state['version']
        ui.image(f'/logo?v={v}').style(
            'width: 15rem; height: 6rem; object-fit: contain;'
        )

    async def _on_upload(e) -> None:
        f = getattr(e, 'file', None)
        if f is not None:
            size = f.size() if callable(f.size) else f.size
            if size > _MAX_LOGO_BYTES:
                notify(t('appsettings.logo_too_large'), type='negative')
                return
            raw = await f.read()
            mime = f.content_type or ''
        else:
            raw = e.content.read()
            if len(raw) > _MAX_LOGO_BYTES:
                notify(t('appsettings.logo_too_large'), type='negative')
                return
            mime = getattr(e, 'type', None) or ''
        if mime == 'image/jpg':
            mime = 'image/jpeg'
        if mime not in _LOGO_MIMES:
            notify(t('appsettings.logo_bad_format'), type='negative')
            return
        payload = {'mime': mime, 'data': base64.b64encode(raw).decode()}
        try:
            with get_session() as session:
                out = session.put('/app/logo', json=payload)
            state['version'] = (out or {}).get('version', state['version'] + 1)
        except Exception:  # noqa: BLE001 — backend unreachable / auth expired
            notify(t('appsettings.logo_save_failed'), type='negative')
            return
        # Live-reload the logo in every open tab (same pattern as the avatar).
        app.storage.user['logo_version'] = state['version']
        notify(t('appsettings.logo_saved'), type='positive')
        logo_preview.refresh()

    def _on_reset() -> None:
        try:
            with get_session() as session:
                session.delete('/app/logo')
        except Exception:  # noqa: BLE001
            notify(t('appsettings.logo_save_failed'), type='negative')
            return
        state['version'] += 1
        app.storage.user['logo_version'] = state['version']
        notify(t('appsettings.logo_reset'), type='positive')
        logo_preview.refresh()

    with ui.column().classes('card w-full gap-1 p-6 mt-4').style('max-width: 640px;'):
        with ui.row().classes('items-center gap-2'):
            ui.icon('image', size='sm').classes('text-muted')
            ui.label(t('appsettings.logo')).classes('card-title')
        ui.label(t('appsettings.logo_desc')).classes('card-description mb-4')

        with ui.row().classes('items-start gap-5 w-full no-wrap'):
            with ui.column().classes('items-center gap-2 flex-shrink-0'):
                logo_preview()
                i18n.bind(
                    ui.button(t('appsettings.logo_reset_btn'), icon='restore',
                               on_click=_on_reset)
                    .props('flat no-caps').classes('button button-ghost button-sm'),
                    'appsettings.logo_reset_btn',
                )
            with ui.column().classes('flex-1 min-w-0 gap-0'):
                dropzone(on_upload=_on_upload, max_file_size=_MAX_LOGO_BYTES,
                         accept='.svg,.png,.jpg,.jpeg')
