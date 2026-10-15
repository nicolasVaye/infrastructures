"""Audit log page: a chronological view of who did what across the app.

Admin-only.  All persistence goes through :class:`services.audit_service.AuditService`;
this view only orchestrates the UI and delegates every query to the service.
"""

from __future__ import annotations

from nicegui import app, ui

from components.dialogs import confirm_dialog, info_dialog
from components.notifications import notify
from core.database import get_session
from models.audit import AuditAction
from models.enums import UserRole
from services.audit_service import AuditService
from services.i18n import t
from services.tz import format_local, get_app_timezone

# action value -> (Material icon, badge class) for the activity list.
_ACTION_META: dict[str, tuple[str, str]] = {
    AuditAction.LOGIN.value:            ('login', 'badge badge-success'),
    AuditAction.LOGIN_FAILED.value:     ('gpp_bad', 'badge badge-danger'),
    AuditAction.LOGOUT.value:           ('logout', 'badge badge-default'),
    AuditAction.PASSWORD_CHANGED.value: ('password', 'badge badge-info'),
    AuditAction.PASSWORD_RESET.value:   ('lock_reset', 'badge badge-warning'),
    AuditAction.USER_CREATED.value:     ('person_add', 'badge badge-success'),
    AuditAction.USER_DELETED.value:     ('person_remove', 'badge badge-danger'),
    AuditAction.ROLE_CHANGED.value:     ('swap_horiz', 'badge badge-info'),
    AuditAction.USER_ACTIVATED.value:   ('check_circle', 'badge badge-success'),
    AuditAction.USER_DEACTIVATED.value: ('block', 'badge badge-warning'),
    AuditAction.PROFILE_UPDATED.value:  ('manage_accounts', 'badge badge-info'),
    AuditAction.LANGUAGE_CHANGED.value: ('language', 'badge badge-default'),
    AuditAction.THEME_CHANGED.value:     ('dark_mode', 'badge badge-default'),
    AuditAction.SESSION_REVOKED.value:  ('no_accounts', 'badge badge-warning'),
    AuditAction.JOB_SUBMITTED.value:    ('play_circle', 'badge badge-info'),
    AuditAction.JOB_CANCELLED.value:    ('cancel', 'badge badge-warning'),
    AuditAction.OIDC_LOGIN.value:       ('key', 'badge badge-success'),
    AuditAction.IDP_CREATED.value:      ('add_link', 'badge badge-success'),
    AuditAction.IDP_UPDATED.value:      ('edit_note', 'badge badge-info'),
    AuditAction.IDP_DELETED.value:      ('link_off', 'badge badge-danger'),
}

_DEFAULT_META = ('history', 'badge badge-default')

# Thematic grouping of audit actions for the linked filter selects:
# i18n group key -> ordered action values. Every AuditAction must appear in
# exactly one group so the flat enum list and the grouped view stay in sync.
_AUDIT_THEMES: list[tuple[str, tuple[str, ...]]] = [
    ('audit.group.sessions', (
        AuditAction.LOGIN.value,
        AuditAction.LOGIN_FAILED.value,
        AuditAction.OIDC_LOGIN.value,
        AuditAction.LOGOUT.value,
        AuditAction.SESSION_REVOKED.value,
    )),
    ('audit.group.accounts', (
        AuditAction.USER_CREATED.value,
        AuditAction.USER_DELETED.value,
        AuditAction.USER_ACTIVATED.value,
        AuditAction.USER_DEACTIVATED.value,
        AuditAction.PASSWORD_CHANGED.value,
        AuditAction.PASSWORD_RESET.value,
    )),
    ('audit.group.roles', (
        AuditAction.ROLE_CHANGED.value,
    )),
    ('audit.group.preferences', (
        AuditAction.PROFILE_UPDATED.value,
        AuditAction.LANGUAGE_CHANGED.value,
        AuditAction.THEME_CHANGED.value,
    )),
    ('audit.group.idps', (
        AuditAction.IDP_CREATED.value,
        AuditAction.IDP_UPDATED.value,
        AuditAction.IDP_DELETED.value,
    )),
    ('audit.group.jobs', (
        AuditAction.JOB_SUBMITTED.value,
        AuditAction.JOB_CANCELLED.value,
    )),
]

_THEME_ACTIONS: dict[str, tuple[str, ...]] = dict(_AUDIT_THEMES)

# How many rows the list shows at once.
_LIMIT = 200


def _is_admin() -> bool:
    return app.storage.user.get('role') == UserRole.ADMIN.value


def _action_label(action: str) -> str:
    return t(f'audit.action.{action}')


def content() -> None:
    """Audit tab of the /settings admin hub (no page header; guard in hub)."""
    # Filter state: selected category ('all' or a group key) plus the set of
    # selected action values (multi-select). An empty set inside a category
    # means "every action of that category".
    state = {'category': 'all', 'actions': set()}

    def _effective_actions() -> list[str] | None:
        """Translate the two combos into the service's `actions` argument.

        - category 'all': the explicitly selected actions, or None (= all).
        - a category: its selected actions, or the whole category when none
          is picked (choosing a category filters to that category).
        """
        if state['category'] == 'all':
            return sorted(state['actions']) or None
        group = _THEME_ACTIONS.get(state['category'], ())
        selected = [a for a in group if a in state['actions']]
        return selected or list(group)

    @ui.refreshable
    def audit_table() -> None:
        with get_session() as session:
            service = AuditService(session)
            total = service.count()
            entries = [
                {
                    'created_at': e.created_at,
                    'action': e.action,
                    'username': e.username,
                    'target': e.target,
                    'details': e.details,
                    'ip': e.ip,
                }
                for e in service.get_recent(limit=_LIMIT,
                                           actions=_effective_actions())
            ]
        # Display timezone: timestamps are stored UTC, the admin-configured
        # zone (GET /app/timezone, short-cached) drives how they render.
        display_tz = get_app_timezone()

        ui.label(t('audit.showing').format(shown=len(entries), total=total)) \
            .classes('text-xs text-muted mb-2')

        if not entries:
            with ui.column().classes('card w-full items-center gap-2 p-8'):
                ui.icon('history', size='2rem').classes('text-muted')
                ui.label(t('audit.empty')).classes('text-muted')
            return

        with ui.column().classes('card w-full gap-0 p-0'):
            # Header row
            with ui.row().classes('w-full items-center px-4 py-3 label-text').style(
                'border-bottom: 1px solid var(--border, #e4e4e7);'
            ):
                ui.label(t('audit.col.time')).style('width: 170px;')
                ui.label(t('audit.col.user')).style('width: 160px;')
                ui.label(t('audit.col.action')).style('width: 190px;')
                ui.label(t('audit.col.details')).classes('flex-1')
                ui.label(t('audit.col.ip')).style('width: 130px;')

            for e in entries:
                icon, badge_cls = _ACTION_META.get(e['action'], _DEFAULT_META)
                detail_parts = [p for p in (e['target'], e['details']) if p]
                detail_text = ' · '.join(detail_parts)

                with ui.row().classes('w-full items-center px-4 py-3 no-wrap').style(
                    'border-bottom: 1px solid var(--border, #f4f4f5);'
                ):
                    ui.label(format_local(e['created_at'], display_tz)).style(
                        'width: 170px; font-family: monospace;'
                    ).classes('text-xs text-muted')

                    ui.label(e['username']).style('width: 160px;').classes('truncate')

                    with ui.element('div').style('width: 190px;'):
                        with ui.element('span').classes(badge_cls).style('gap: 4px;'):
                            ui.icon(icon, size='0.9rem')
                            ui.label(_action_label(e['action']))

                    ui.label(detail_text or '—').classes('flex-1 truncate text-sm')

                    ui.label(e['ip'] or '—').style(
                        'width: 130px; font-family: monospace;'
                    ).classes('text-xs text-muted')

    async def _clear() -> None:
        confirmed = await confirm_dialog(
            t('audit.clear_confirm'),
            title=t('audit.clear_title'),
            confirm_text=t('audit.clear'),
            danger=True,
        )
        if not confirmed:
            return
        try:
            with get_session() as session:
                removed = AuditService(session).clear()
        except Exception as exc:  # noqa: BLE001  surfaced to the admin
            await info_dialog(str(exc), title=t('audit.clear_title'), danger=True)
            return
        notify(t('audit.cleared').format(n=removed), type='warning')
        audit_table.refresh()

    # Toolbar: linked filter selects, refresh, clear.
    # First combo = category ('all' or one of the six themes); second combo =
    # the actions INSIDE that category (multi-select). Picking a category
    # without any action shows the whole category; picking actions narrows
    # it down. The table refreshes live on every change.
    with ui.row().classes('w-full items-center justify-between gap-2 mb-3 no-wrap'):
        with ui.row().classes('items-center gap-2 flex-1'):
            def _category_options() -> dict[str, str]:
                return {'all': t('audit.filter.all')} \
                    | {key: t(key) for key, _ in _AUDIT_THEMES}

            def _action_options() -> dict[str, str]:
                if state['category'] == 'all':
                    actions = [a for group in _THEME_ACTIONS.values() for a in group]
                else:
                    actions = _THEME_ACTIONS.get(state['category'], ())
                return {a: _action_label(a) for a in actions}

            category_select = ui.select(
                options=_category_options(),
                value=state['category'],
                label=t('audit.filter.category'),
            ).props('outlined dense no-caps').classes('audit-filter-select')

            action_select = ui.select(
                options=_action_options(),
                value=[],
                multiple=True,
                label=t('audit.filter.actions'),
            ).props('outlined dense no-caps use-chips').classes('audit-filter-select')

            def _on_category_change(_) -> None:
                """Switching category: reset the action selection and re-scope
                the second combo to the new category's actions."""
                state['category'] = category_select.value or 'all'
                state['actions'].clear()
                action_select.set_options(_action_options())
                action_select.set_value([])
                audit_table.refresh()

            def _on_actions_change(_) -> None:
                state['actions'] = set(action_select.value or [])
                audit_table.refresh()

            category_select.on_value_change(_on_category_change)
            action_select.on_value_change(_on_actions_change)

            def _reset_filter() -> None:
                """Back to 'all actions' whatever the current state (set_value
                alone would be a no-op when the category is already 'all')."""
                category_select.set_value('all')
                state['actions'].clear()
                action_select.set_options(_action_options())
                action_select.set_value([])
                audit_table.refresh()

            ui.button(t('audit.filter.reset'), icon='filter_alt_off',
                      on_click=_reset_filter) \
                .props('flat no-caps').classes('button button-ghost')

        with ui.row().classes('items-center gap-2'):
            ui.button(t('common.refresh'), icon='refresh', on_click=lambda: audit_table.refresh()) \
                .props('flat no-caps').classes('button button-secondary')
            ui.button(t('audit.clear'), icon='delete_sweep', on_click=_clear) \
                .props('flat no-caps color=negative').classes('button button-ghost')

    audit_table()

    # Live updates: logins/logouts/kicks emit 'sessions_changed' — new audit
    # rows should appear without a manual refresh, like the Users/Sessions
    # tabs. Same SSE counter pattern; 60s fallback poll as safety net.
    from views._common import safe_auto_refresh

    seen = {'counter': app.storage.user.get('sessions_refresh_counter', 0)}

    def _on_event() -> None:
        counter = app.storage.user.get('sessions_refresh_counter', 0)
        if counter != seen['counter']:
            seen['counter'] = counter
            safe_auto_refresh(audit_table.refresh)()

    ui.timer(1.0, _on_event)
    ui.timer(60.0, safe_auto_refresh(audit_table.refresh))
