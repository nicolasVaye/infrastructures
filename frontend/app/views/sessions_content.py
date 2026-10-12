"""Connected sessions page (admin): who is connected, grouped by user, and kick.

Data comes from GET /sessions on the backend — web browsers, OIDC logins and
external automation clients all appear here, with their last heartbeat. A
per-user summary row lets the admin see at a glance how many sessions each
user holds and filter the table on a specific user.
"""

from __future__ import annotations

from collections import Counter

from nicegui import app, ui

from components.dialogs import confirm_dialog, info_dialog
from components.notifications import notify
from core.database import get_session
from models.enums import UserRole
from views._common import page_header, safe_auto_refresh

_client_icons = {
    'web': 'web',
    'automation': 'smart_toy',
    'pytest': 'science',
    'oidc': 'key',
}


def _is_admin() -> bool:
    return app.storage.user.get('role') == UserRole.ADMIN.value


def content() -> None:
    page_header('Connected sessions', 'Sessions grouped by user — web, OIDC and automation clients')

    if not _is_admin():
        with ui.column().classes('card w-full items-center gap-2 p-8'):
            ui.icon('lock', size='2rem').classes('text-muted')
            ui.label('Admin only').classes('section-title')
            ui.label('You need the admin role to view connected sessions.').classes('text-muted')
        return

    selected_user = {'username': None}

    @ui.refreshable
    def sessions_table() -> None:
        # Refreshables run in a background task: an exception here is logged
        # by NiceGUI, it never reaches the timer's wrapper. Guard the fetch
        # itself — after a logout/revocation the next poll must not raise.
        from shared.client.async_client import ApiError
        try:
            with get_session() as api:
                all_sessions = api.get('/sessions')
        except ApiError as exc:
            if getattr(exc, 'status_code', None) == 401:
                return  # session revoked (e.g. self-kick): heartbeat redirects
            raise
        # Total (unfiltered) counts for the per-user summary chips
        count_total = Counter(s['username'] for s in all_sessions)

        if selected_user['username'] is not None:
            sessions = [s for s in all_sessions if s['username'] == selected_user['username']]
        else:
            sessions = all_sessions

        # Per-user summary: how many connected sessions each user holds.
        with ui.row().classes('w-full items-center gap-2 mb-2 flex-wrap'):
            for username, count in sorted(count_total.items()):
                active = selected_user['username'] == username
                with ui.element('button').classes(
                    'badge badge-default cursor-pointer'
                ).style('gap: 6px;' + (' box-shadow: 0 0 0 2px #3b82f6;' if active else '')).on(
                    'click', lambda _, u=username: (selected_user.update(username=None)
                                                   if selected_user['username'] == u
                                                   else selected_user.update(username=u),
                                                   sessions_table.refresh())
                ):
                    ui.icon('person', size='0.9rem')
                    ui.label(f'{username} ({count})')

        if not sessions:
            with ui.column().classes('card w-full items-center gap-2 p-8'):
                ui.icon('cloud_off', size='2rem').classes('text-muted')
                ui.label('No connected client right now.').classes('text-muted')
            return

        with ui.column().classes('card w-full gap-0 p-0'):
            with ui.row().classes('w-full items-center px-4 py-3 label-text').style(
                'border-bottom: 1px solid var(--border, #e4e4e7);'
            ):
                ui.label('User').classes('flex-1')
                ui.label('Client').style('width: 130px;')
                ui.label('IP').style('width: 130px;')
                ui.label('Last activity').style('width: 190px;')
                ui.label('').style('width: 90px;')

            for s in sessions:
                with ui.row().classes('w-full items-center px-4 py-3 no-wrap').style(
                    'border-bottom: 1px solid var(--border, #f4f4f5);'
                ):
                    ui.icon('person', size='1rem').classes('text-muted')
                    with ui.column().classes('flex-1 gap-0'):
                        with ui.row().classes('items-center gap-2'):
                            ui.label(s['username']).classes('truncate')
                            if s['username'] == app.storage.user.get('username'):
                                with ui.element('span').classes('badge badge-default').style('gap: 4px;'):
                                    ui.icon('verified_user', size='0.9rem')
                                    ui.label('you')
                        if count_total[s['username']] > 1:
                            ui.label(f'+{count_total[s["username"]] - 1} other session(s)').classes('text-xs text-muted')

                    icon = _client_icons.get(s.get('client'), 'devices')
                    with ui.element('div').style('width: 130px;'):
                        with ui.element('span').classes('badge badge-default').style('gap: 4px;'):
                            ui.icon(icon, size='0.9rem')
                            ui.label(s.get('client') or 'unknown')

                    ui.label(s.get('ip') or '—').classes('text-xs text-muted').style(
                        'width: 130px; font-family: monospace;'
                    )
                    ui.label(s.get('last_activity', '')).classes('text-xs text-muted').style(
                        'width: 190px; font-family: monospace;'
                    )

                    session_id = s['id']
                    async def _kick(sid: str = session_id) -> None:
                        confirmed = await confirm_dialog(
                            f'Revoke session {sid[:8]}…?',
                            title='Kick session', danger=True,
                        )
                        if not confirmed:
                            return
                        try:
                            with get_session() as api:
                                api.delete(f'/sessions/{sid}')
                        except Exception as exc:
                            await info_dialog(str(exc), title='Not possible', danger=True)
                            return
                        notify('Session revoked', type='warning')
                        # The kicked session may be the caller's own: the
                        # refresh then runs unauthenticated and must not raise.
                        safe_auto_refresh(sessions_table.refresh)()

                    with ui.button(icon='logout', on_click=_kick).props('flat dense color=negative'):
                        pass

    sessions_table()

    ui.timer(15.0, safe_auto_refresh(sessions_table.refresh))
