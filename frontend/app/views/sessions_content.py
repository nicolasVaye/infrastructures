"""Connected sessions page (admin): who is connected, grouped by user, and kick.

Data comes from GET /sessions on the backend — web browsers, OIDC logins and
external automation clients all appear here, with their last heartbeat. A
per-user summary row lets the admin see at a glance how many sessions each
user holds and filter the table on a specific user.
"""

from __future__ import annotations

import re
from collections import Counter

from nicegui import app, ui

from components.dialogs import confirm_dialog, info_dialog
from components.notifications import notify
from core.database import get_session
from services.i18n import bind_format, t
from views._common import safe_auto_refresh

_client_icons = {
    'web': 'web',
    'automation': 'smart_toy',
    'pytest': 'science',
    'oidc': 'key',
}


def _ua_summary(ua: str | None) -> str | None:
    """Compact 'Browser · OS' label parsed from a raw User-Agent string."""
    if not ua:
        return None
    match = re.search(r'(Edg|OPR|Firefox|Chrome|Safari)/[\d.]+', ua)
    browser = None
    if match:
        name = match.group(1)
        browser = {'Edg': 'Edge', 'OPR': 'Opera', 'Safari': 'Safari',
                   'Chrome': 'Chrome', 'Firefox': 'Firefox'}.get(name)
    if 'Windows NT' in ua:
        os_name = 'Windows'
    elif 'Mac OS X' in ua:
        os_name = 'macOS'
    elif 'Android' in ua:
        os_name = 'Android'
    elif 'iPhone' in ua or 'iPad' in ua:
        os_name = 'iOS'
    elif 'Linux' in ua:
        os_name = 'Linux'
    else:
        os_name = None
    parts = [p for p in (browser, os_name) if p]
    if parts:
        return ' · '.join(parts)
    return ua[:40] + '…' if len(ua) > 40 else ua


def content() -> None:
    """Sessions tab of the /settings admin hub (no page header here:
    the hub renders one; the admin guard also lives in the hub)."""
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
                ui.label(t('sessions.empty')).classes('text-muted')
            return

        with ui.column().classes('card w-full gap-0 p-0'):
            with ui.row().classes('w-full items-center px-4 py-3 label-text').style(
                'border-bottom: 1px solid var(--border, #e4e4e7);'
            ):
                ui.label(t('sessions.col.user')).classes('flex-1')
                ui.label(t('sessions.col.client')).style('width: 130px;')
                ui.label(t('sessions.col.ip')).style('width: 130px;')
                ui.label(t('sessions.col.last_activity')).style('width: 190px;')
                ui.label('').style('width: 90px;')

            for s in sessions:
                with ui.row().classes('w-full items-center px-4 py-3 no-wrap').style(
                    'border-bottom: 1px solid var(--border, #f4f4f5);'
                ):
                    if s.get('avatar'):
                        # Profile photo (data URL) of the session's user.
                        ui.image(s['avatar']).style(
                            'width: 28px; height: 28px; border-radius: 50%; '
                            'object-fit: cover; flex-shrink: 0;'
                        )
                    else:
                        ui.icon('person', size='1rem').classes('text-muted')
                    with ui.column().classes('flex-1 gap-0'):
                        with ui.row().classes('items-center gap-2'):
                            ui.label(s['username']).classes('truncate')
                            if s['username'] == app.storage.user.get('username'):
                                with ui.element('span').classes('badge badge-default').style('gap: 4px;'):
                                    ui.icon('verified_user', size='0.9rem')
                                    ui.label(t('sessions.you'))
                            # Local vs federated (IdP) source — same badge style
                            # as the Users tab.
                            if s.get('auth_provider') == 'idp' and s.get('idp_name'):
                                with ui.element('span').classes('badge badge-info').style('gap: 4px;'):
                                    ui.icon('vpn_key', size='0.9rem')
                                    ui.label(s['idp_name'])
                            else:
                                with ui.element('span').classes('badge badge-default').style('gap: 4px;'):
                                    ui.icon('person', size='0.9rem')
                                    ui.label(t('users.source.local'))
                        if count_total[s['username']] > 1:
                            # Informational: how many OTHER active sessions the
                            # same user holds (other browsers, a second login,
                            # automation clients...).
                            bind_format(
                                ui.label().classes('text-xs text-muted'),
                                'sessions.other_sessions',
                                n=count_total[s['username']] - 1,
                            )

                    icon = _client_icons.get(s.get('client'), 'devices')
                    with ui.element('div').style('width: 130px;'):
                        with ui.element('span').classes('badge badge-default').style('gap: 4px;'):
                            ui.icon(icon, size='0.9rem')
                            ui.label(s.get('client') or 'unknown')
                        # User-agent summary (e.g. "Chrome - Windows") under
                        # the client badge; the tooltip carries the full UA.
                        ua = s.get('user_agent')
                        ua_label = _ua_summary(ua)
                        if ua_label:
                            with ui.element('div').classes('text-xs text-muted truncate').style(
                                'max-width: 120px; margin-top: 2px;'
                            ) as ua_el:
                                ui.label(ua_label)
                                if ua and ua != ua_label:
                                    ua_el.tooltip(ua)

                    ui.label(s.get('ip') or '—').classes('text-xs text-muted').style(
                        'width: 130px; font-family: monospace;'
                    )
                    ui.label(s.get('last_activity', '')).classes('text-xs text-muted').style(
                        'width: 190px; font-family: monospace;'
                    )

                    session_id = s['id']
                    async def _kick(sid: str = session_id) -> None:
                        confirmed = await confirm_dialog(
                            t('sessions.kick_confirm').format(sid=sid[:8]),
                            title=t('sessions.kick_title'), danger=True,
                        )
                        if not confirmed:
                            return
                        try:
                            with get_session() as api:
                                api.delete(f'/sessions/{sid}')
                        except Exception as exc:
                            await info_dialog(str(exc), title=t('sessions.not_possible'), danger=True)
                            return
                        notify(t('sessions.revoked'), type='warning')
                        # The kicked session may be the caller's own: the
                        # refresh then runs unauthenticated and must not raise.
                        safe_auto_refresh(sessions_table.refresh)()

                    with ui.button(icon='logout', on_click=_kick).props('flat dense color=negative'):
                        pass

    sessions_table()

    ui.timer(15.0, safe_auto_refresh(sessions_table.refresh))
