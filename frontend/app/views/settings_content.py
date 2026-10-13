"""Admin-only application settings page for logging configuration.

The log level is applied live across the whole application and persisted so it
survives restarts.  Log records are written to a rolling file in the ``logs/``
folder (see :mod:`core.logging_config`).
"""

from nicegui import app, ui

from components.notifications import notify
from core.logging_config import LOG_FILE, LOG_LEVELS, get_log_level, set_log_level
from models.enums import UserRole
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
